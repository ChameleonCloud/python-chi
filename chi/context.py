import os
import sys
import time

from keystoneauth1.identity.v3 import OidcAccessToken
from keystoneauth1 import loading
from keystoneauth1.loading.conf import _AUTH_SECTION_OPT, _AUTH_TYPE_OPT
from keystoneauth1 import session
from oslo_config import cfg
import requests

from . import jupyterhub

import logging
LOG = logging.getLogger(__name__)

DEFAULT_AUTH_TYPE = 'v3token'
CONF_GROUP = 'chi'
RESOURCE_API_URL = os.getenv('CHI_RESOURCE_API_URL',
                             'https://api.chameleoncloud.org')


def default_key_name():
    username = os.getenv('USER')
    return f'{username}-jupyter' if username else None


session_opts = loading.get_session_conf_options()
adapter_opts = loading.get_adapter_conf_options()
# Settings that do not affect authentication, but are used  to define defaults
# for other operations.
extra_opts = [
    cfg.StrOpt('key-name', default=default_key_name(), help=(
        'Name of the SSH keypair to allow access to launched instances')),
    cfg.StrOpt('image', help=(
        'Name of disk image to use when launching instances')),
    cfg.StrOpt('keypair-private-key', help='Path to the SSH private key file'),
    cfg.StrOpt('keypair-public-key', help='Path to the SSH public key file'),
]
global_options = session_opts + adapter_opts + extra_opts

_auth_plugin = None
_session = None
_sites = {}


def printerr(msg):
    return print(msg, file=sys.stderr)


class SessionWithAccessTokenRefresh(session.Session):
    # How many seconds before expiration should we try to refresh
    REFRESH_THRESHOLD = 60  # seconds

    def __init__(self, auth=None, **kwargs):
        def get_access_token(_auth):
            should_refresh = (
                _auth._expires_at - time.time() < self.REFRESH_THRESHOLD)
            if not _auth._access_token or should_refresh:
                try:
                    access_token, expires_at = jupyterhub.refresh_access_token()
                    _auth._access_token = access_token
                    _auth._expires_at = expires_at
                except Exception as e:
                    LOG.error('Failed to refresh access_token: %s', e)
            return _auth._access_token

        def set_access_token(_auth, access_token):
            _auth._access_token = access_token

        # Override the access_token property to support dynamically refreshing
        # it if close to expiring. Uses the @property decorator, but called
        # explicitly and overridden on the class (it must be on the class,
        # as Python will bind this as a class descriptor.) It has to also
        # provide a setter so auth.access_token = ... works.
        #
        # TODO(jason): this is definitely a hack :) -- but it's the best
        # thing I could come up with, given how many places the code will need
        # a fresh access token. The auth plugin is hard to override b/c it is
        # being dynamically loaded via an entry point, and overriding on the
        # Session.request function is not enough because there are many other
        # points at which an authentication is performed (e.g., looking up an
        # endpoint.)
        if (auth and isinstance(auth, OidcAccessToken)
            and jupyterhub.is_jupyterhub_env()):
            auth._access_token = None
            auth._expires_at = 0
            # Monkey-patch access_token to be @property dynamic lookup
            auth.__class__.access_token = (
                property(get_access_token, set_access_token))

        super().__init__(auth=auth, **kwargs)


class SessionLoader(loading.session.Session):
    plugin_class = SessionWithAccessTokenRefresh


def _auth_plugins():
    return [
        (name, [o._to_oslo_opt() for o in loader.get_options()])
        for name, loader in loading.get_available_plugin_loaders().items()
        if name.startswith('v3')
    ]


def _default_from_env(opts, group=None):
    def _default(opt):
        all_opts = [opt] + (getattr(opt, 'deprecated_opts', getattr(opt, 'deprecated', None)) or [])
        for o in all_opts:
            v = os.environ.get(f'OS_{o.name.replace("-", "_").upper()}')
            if v:
                return v

    if not group:
        group = CONF_GROUP

    for opt in opts:
        default = _default(opt)
        if default:
            cfg.CONF.set_default(opt.dest, default, group=group)


def _auth_section(auth_plugin):
    return f'{CONF_GROUP}.auth.{auth_plugin}'


def _set_auth_plugin(auth_plugin):
    global _auth_plugin
    auth_section = _auth_section(auth_plugin)
    cfg.CONF.set_override(_AUTH_SECTION_OPT.dest, auth_section, group=CONF_GROUP)
    # Re-register the auth conf options so that the auth_type option is
    # registered in the proper auth_section. An alternative would be to register
    # the auth_type option explicitly within every auth_section we use, but
    # this is an idempotent operation, so we just (ab)use the register function.
    loading.register_auth_conf_options(cfg.CONF, CONF_GROUP)
    cfg.CONF.set_override(_AUTH_TYPE_OPT.dest, auth_plugin, group=auth_section)
    _auth_plugin = auth_plugin


def set(key, value):
    """Set a context parameter by name.

    Args:
        key (str): the parameter name.
        value (any): the parameter value.

    Raises:
        cfg.NoSuchOptError: if the parameter is not supported.
    """
    global _session
    # Special handling for auth_type setting as we have to also tell KSA to
    # start reading auth parameters from the plugin's auth section.
    if key == _AUTH_TYPE_OPT.dest:
        _set_auth_plugin(value)
    elif key in [o.dest for o in global_options]:
        cfg.CONF.set_override(key, value, group=CONF_GROUP)
    else:
        valid_for_some_plugin = False
        # Set for all auth plugins that define this option.
        for auth_plugin, opts in _auth_plugins():
            matches = [o for o in opts if key in [o.name, o.dest]]
            for opt in matches:
                cfg.CONF.set_override(opt.dest, value, group=_auth_section(auth_plugin))
            valid_for_some_plugin |= len(matches) > 0
        if not valid_for_some_plugin:
            raise cfg.NoSuchOptError(key)
    # Invalidate session if setting affects session
    if key not in [o.dest for o in extra_opts]:
        _session = None


def get(key):
    """Get a context parameter by name.

    Args:
        key (str): the parameter name.

    Returns:
        any: the parameter value.

    Raises:
        cfg.NoSuchOptError: if the parameter is not supported.
    """
    global _auth_plugin
    if key in [o.dest for o in global_options]:
        return cfg.CONF[CONF_GROUP][key]
    else:
        return cfg.CONF[_auth_section(_auth_plugin)][key]


def params():
    """List all parameters currently set on the context.

    Returns:
        List[str]: a list of parameter names.
    """
    global _auth_plugin
    keys = list(cfg.CONF[CONF_GROUP].keys())
    keys.extend(list(cfg.CONF[_auth_section(_auth_plugin)].keys()))
    return keys


def use_site(site_name):
    global _sites
    if not _sites:
        res = requests.get(f'{RESOURCE_API_URL}/sites.json')
        try:
            res.raise_for_status()
            items = res.json().get('items', [])
            _sites = {s['name']: s for s in items}
            if not _sites:
                raise ValueError('No sites returned.')
        except Exception:
            printerr("""Failed to fetch list of available Chameleon sites.
                You can still set the site information manually like this,
                if you know the URL and name:

                    chi.set('auth_url', 'https://chi.uc.chameleoncloud.org:5000/v3')
                    chi.set('region_name', 'CHI@UC')
                """)
            return

    site = _sites.get(site_name)
    if not site:
        raise ValueError((
            f'No site named "{site_name}" exists! Possible values: '
            ', '.join(_sites.keys())))

    # Set important parameters
    set('auth_url', f'{site["web"]}:5000/v3')
    set('region_name', site['name'])

    output = [
        f'Now using {site_name}:',
        f'URL: {site.get("web")}',
        f'Location: {site.get("location")}',
        f'Support contact: {site.get("user_support_contact")}',
    ]
    print('\n'.join(output))


def session():
    """Get a Keystone Session object suitable for authenticating a client.

    Returns:
        keystoneauth1.session.Session: the authentication session object.
    """
    global _session
    if not _session:
        auth = loading.load_auth_from_conf_options(cfg.CONF, CONF_GROUP)
        sess = SessionLoader().load_from_conf_options(cfg.CONF, CONF_GROUP, auth=auth)
        _session = loading.load_adapter_from_conf_options(cfg.CONF, CONF_GROUP, session=sess)
    return _session


def reset():
    """Reset the context, removing all overrides and defaults.

    The ``auth_type`` parameter will be defaulted to the value of the
    OS_AUTH_TYPE environment variable, falling back to "v3token" if not defined.

    All context parameters will revert to the default values inferred from
    environment variables.
    """
    global _session
    global _sites
    _session = None
    _sites = {}
    cfg.CONF.reset()
    _set_auth_plugin(
        os.getenv('OS_AUTH_TYPE',
            os.getenv('OS_AUTH_METHOD', DEFAULT_AUTH_TYPE)))
    _default_from_env(global_options, group=CONF_GROUP)
    for auth_plugin, opts in _auth_plugins():
        _default_from_env(opts, group=_auth_section(auth_plugin))


cfg.CONF.register_group(cfg.OptGroup(CONF_GROUP))
loading.register_auth_conf_options(cfg.CONF, CONF_GROUP)
loading.register_session_conf_options(cfg.CONF, CONF_GROUP)
loading.register_adapter_conf_options(cfg.CONF, CONF_GROUP)
cfg.CONF.register_opts(extra_opts, group=CONF_GROUP)

for auth_plugin, opts in _auth_plugins():
    auth_section = _auth_section(auth_plugin)
    cfg.CONF.register_group(cfg.OptGroup(auth_section))
    cfg.CONF.register_opts(opts, group=auth_section)

reset()
