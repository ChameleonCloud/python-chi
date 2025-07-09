import logging
import os
import re
import sys
import time
from typing import List, Optional

import ipywidgets as widgets
import openstack
import requests
from IPython.display import display
from keystoneauth1 import loading, session
from keystoneauth1.identity.v3 import OidcAccessToken
from keystoneauth1.loading.conf import _AUTH_SECTION_OPT, _AUTH_TYPE_OPT
from keystoneclient import exceptions as keystone_exceptions
from keystoneclient.v3.client import Client as KeystoneClient
from oslo_config import cfg

from . import jupyterhub
from .exception import CHIValueError, ResourceError

LOG = logging.getLogger(__name__)

DEFAULT_SITE = "CHI@UC"
DEFAULT_IMAGE_NAME = "CC-Ubuntu22.04"
DEFAULT_NODE_TYPE = "compute_skylake"
DEFAULT_AUTH_TYPE = "v3token"
DEFAULT_NETWORK = "sharednet1"
CONF_GROUP = "chi"
RESOURCE_API_URL = os.getenv("CHI_RESOURCE_API_URL", "https://api.chameleoncloud.org")
EDGE_RESOURCE_API_URL = os.getenv(
    "EDGE_RESOURCE_API_URL", "https://chameleoncloud.org/edge-hw-discovery/devices"
)


def default_key_name():
    username = os.getenv("USER")
    return f"{username}-jupyter" if username else None


session_opts = loading.get_session_conf_options()
adapter_opts = loading.get_adapter_conf_options()

# Settings that do not affect authentication, but are used  to define defaults
# for other operations.
#
# NOTE: any deprecated options must be defined using the underscore form.
extra_opts = [
    cfg.StrOpt(
        "keypair-name",
        default=default_key_name(),
        deprecated_opts=[cfg.DeprecatedOpt("key_name")],
        help=("Name of the SSH keypair to allow access to launched instances"),
    ),
    cfg.StrOpt("image", help=("Name of disk image to use when launching instances")),
    cfg.StrOpt("keypair-private-key", help="Path to the SSH private key file"),
    cfg.StrOpt("keypair-public-key", help="Path to the SSH public key file"),
]
global_options = session_opts + adapter_opts + extra_opts
global_option_names = [opt.dest for opt in global_options]
for extra_opt in extra_opts:
    # Explicitly add deprecated names so we can issue warnings in get/set.
    # We only have to do this for our extra_opts, as that's the API we are
    # advertising/maintain.
    global_option_names.extend([o.name for o in extra_opt.deprecated_opts])

deprecated_extra_opts = {
    deprecated_opt.name: current_opt.dest
    for current_opt in extra_opts
    for deprecated_opt in (current_opt.deprecated_opts or [])
}

_auth_plugin = None
_session = None
_sites = {}
_lease_id = None

version = "1.1"


def printerr(msg):
    return print(msg, file=sys.stderr)


class _SessionWithAccessTokenRefresh(session.Session):
    # How many seconds before expiration should we try to refresh
    REFRESH_THRESHOLD = 60  # seconds

    def __init__(self, auth=None, **kwargs):
        def get_access_token(_auth):
            expires_at = getattr(_auth, "_expires_at", time.time())
            should_refresh = expires_at - time.time() < self.REFRESH_THRESHOLD
            if not getattr(_auth, "_access_token", None) or should_refresh:
                try:
                    access_token, expires_at = jupyterhub.refresh_access_token()
                    _auth._access_token = access_token
                    _auth._expires_at = expires_at
                except Exception as e:
                    LOG.error("Failed to refresh access_token: %s", e)
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
        if (
            auth
            and isinstance(auth, OidcAccessToken)
            and jupyterhub.is_jupyterhub_env()
        ):
            auth._access_token = None
            auth._expires_at = 0
            # Monkey-patch access_token to be @property dynamic lookup
            auth.__class__.access_token = property(get_access_token, set_access_token)

        super().__init__(auth=auth, **kwargs)


class SessionLoader(loading.session.Session):
    plugin_class = _SessionWithAccessTokenRefresh


def _auth_plugins():
    return [
        (name, [o._to_oslo_opt() for o in loader.get_options()])
        for name, loader in loading.get_available_plugin_loaders().items()
        if name.startswith("v3")
    ]


def _default_from_env(opts, group=None):
    def _default(opt):
        all_opts = [opt] + (
            getattr(opt, "deprecated_opts", getattr(opt, "deprecated", None)) or []
        )
        for o in all_opts:
            v = os.environ.get(f"OS_{o.name.replace('-', '_').upper()}")
            if v:
                return v

    if not group:
        group = CONF_GROUP

    for opt in opts:
        default = _default(opt)
        if default:
            cfg.CONF.set_default(opt.dest, default, group=group)


def _auth_section(auth_plugin):
    return f"{CONF_GROUP}.auth.{auth_plugin}"


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


def _check_deprecated(key):
    if key not in deprecated_extra_opts:
        return key

    LOG.warning(
        f"Option '{key}' is deprecated; please use '{deprecated_extra_opts[key]}' instead."
    )
    return deprecated_extra_opts[key]


def _is_ipynb() -> bool:
    try:
        from IPython import get_ipython

        ip = get_ipython()
        if not ip or "IPKernelApp" not in ip.config:
            return False
    except ImportError:
        return False
    return True


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
    elif key in global_option_names:
        key = _check_deprecated(key)
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

    if key in global_option_names:
        key = _check_deprecated(key)
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


def list_sites(show: Optional[str] = None) -> dict:
    """
    Retrieves a list of Chameleon sites.

    Args:
        show (str, optional): Determines how the site names should be displayed.
        Possible values are "widget" to display as a table widget, "text" to print
        as plain text,or None (default) to return the List[str] of site names.

    Returns:
        If `show` is set to "widget", it displays the site names as a text widget.
        If `show` is set to "text", it prints the site names as plain text.
        If `show` is set to None, it returns a dictionary of site names to their properties.

    Raises:
        ValueError: If no sites are returned or if an invalid value is provided for the `show` parameter.
    """
    global _sites

    if not _sites:
        res = requests.get(f"{RESOURCE_API_URL}/sites.json")
        res.raise_for_status()
        items = res.json().get("items", [])
        _sites = {s["name"]: s for s in items}
        _sites = dict(
            sorted(
                _sites.items(),
                key=lambda x: (x[1]["site_class"], x[0] not in ["CHI@TACC", "CHI@UC"]),
            )
        )
        _sites["KVM@TACC"] = {
            "name": "KVM@TACC",
            "web": "https://kvm.tacc.chameleoncloud.org",
            "location": "Austin, Texas, USA",
            "user_support_contact": "help@chameleoncloud.org",
        }
        if not _sites:
            raise ResourceError("No sites returned.")

    if show is None:
        return _sites
    elif show == "widget" and _is_ipynb():
        # Constructing the table HTML
        table_html = """
        <table>
            <tr>
                <th>Name</th>
                <th>URL</th>
                <th>Location</th>
                <th>User Support Contact</th>
            </tr>
        """

        for site_name in _sites.keys():
            table_html += f"""
            <tr>
                <td>{site_name}</td>
                <td>{_sites[site_name]["web"]}</td>
                <td>{_sites[site_name]["location"]}</td>
                <td>{_sites[site_name]["user_support_contact"]}</td>
            </tr>
            """

        table_html += "</table>"
        display(widgets.HTML(value=table_html))
    elif show == "text":
        print("Chameleon Sites:")
        for site_name in _sites.keys():
            site = _sites[site_name]
            print(f"- Name: {site_name}")
            print(f"  URL: {site['web']}")
            print(f"  Location: {site['location']}")
            print(f"  User Support Contact: {site['user_support_contact']}")
    else:
        raise CHIValueError("Invalid value for 'show' parameter.")


def use_site(site_name: str) -> None:
    """Configure the global request context to target a particular CHI site.

    Targeting a site will mean that leases, instance launch requests, and any
    other API calls will be sent to that site. By default, no site is selected,
    and one must be explicitly chosen.

    .. code-block:: python

       chi.use_site("CHI@UC")

    Changing the site will affect future calls the client makes, implicitly.
    Therefore something like this is possible:

    .. code-block:: python

       chi.use_site("CHI@UC")
       chi.lease.create_lease("my-uc-lease", reservations)
       chi.use_site("CHI@TACC")
       chi.lease.create_lease("my-tacc-lease", reservations)

    Args:
        site_name (str): The name of the site, e.g., "CHI@UC".
    """
    global _sites
    if not _sites:
        try:
            _sites = list_sites()
        except Exception:
            printerr(
                """Failed to fetch list of available Chameleon sites.
                You can still set the site information manually like this,
                if you know the URL and name:

                    chi.set('auth_url', 'https://chi.uc.chameleoncloud.org:5000/v3')
                    chi.set('region_name', 'CHI@UC')
                """
            )
            return

    site = _sites.get(site_name)
    if not site:
        raise CHIValueError(
            (
                f'No site named "{site_name}" exists! Possible values: , '.join(
                    _sites.keys()
                )
            )
        )

    set("auth_url", f"{site['web']}:5000/v3")
    set("region_name", site["name"])

    output = [
        f"Now using {site_name}:",
        f"URL: {site.get('web')}",
        f"Location: {site.get('location')}",
        f"Support contact: {site.get('user_support_contact')}",
    ]
    print("\n".join(output))


def choose_site(default: str = None) -> None:
    """
    Displays a dropdown menu to select a chameleon site.

    Only works if running in a Ipynb notebook environment.

    Args:
        default (str, optional): the site to default to
    """
    if _is_ipynb():
        global _sites
        if not _sites:
            _sites = list_sites()

        if default:
            initial_site = default
        else:
            initial_site = next(iter(_sites.keys()))
        site_dropdown = widgets.Dropdown(
            options=_sites.keys(),
            description="Select Site",
            value=initial_site,
        )

        output = widgets.Output()

        def on_change(change):
            with output:
                output.clear_output()
                use_site(change["new"])

        site_dropdown.observe(on_change, names="value")
        on_change({"new": initial_site})

        display(widgets.VBox([site_dropdown, output]))
    else:
        print("Choose site feature is only available in an ipynb environment.")


def use_lease_id(lease_id: str) -> None:
    """
    Sets the current lease ID to use in the global context.

    This configures the lease so it can be stored for ease
    of restoring suspended sessions. Further lease validation,
    visualizations, and selectors are available in the lease module.

    Args:
        lease_id (str): The ID of the lease to use.
    """
    global _lease_id

    if not re.fullmatch(r"[A-Za-z0-9\-]+", lease_id):
        raise CHIValueError(
            f'Lease ID "{lease_id}" is invalid. It must contain only letters, numbers, and hyphens with no spaces or special characters.'
        )

    _lease_id = lease_id

    print(f"Now using lease with ID {lease_id}.")


def get_lease_id():
    """
    Returns the currently active lease ID, if one has been set.

    Returns:
        str or None: The lease ID currently in use, or None if no lease has been selected.
    """
    if _lease_id is None:
        print("No lease ID has been set. Use `use_lease_id()` to select one.")
    return _lease_id


def get_project_name(project_id: Optional[str] = None) -> str:
    """
    Returns the name of a project by ID, or the current project name if no ID is given.

    Args:
        project_id (str, optional): The ID of the project. If None, uses the current session project.

    Returns:
        str: The name of the project.

    Raises:
        ResourceError: If the project cannot be found or the request fails.
    """
    keystone_session = session()
    keystone_client = KeystoneClient(
        session=keystone_session,
        interface=getattr(keystone_session, "interface", None),
        region_name=getattr(keystone_session, "region_name", None),
    )

    try:
        if project_id:
            project = keystone_client.projects.get(project_id)
        else:
            current_id = keystone_session.get_project_id()
            project = keystone_client.projects.get(current_id)
    except keystone_exceptions.NotFound:
        raise ResourceError("Project not found.")
    except keystone_exceptions.Unauthorized:
        raise ResourceError("Failed to retrieve project. Check your credentials.")

    return project.name


def list_projects(show: str = None) -> List[str]:
    """
    Retrieves a list of projects associated with the current user.

    Args:
        show (str, optional): Determines how the project names should be displayed.
        Possible values are "widget" to display as a table widget, "text" to print
        as plain text, or None (default) to return the list of project names.

    Returns:
        If `show` is set to "widget", it displays the project names as a text widget.
        If `show` is set to "text", it prints the project names as plain text.
        If `show` is set to None, it returns a list of project names.

    Raises:
        ValueError: If no projects are returned or an invalid value is provided for the `show` parameter.

    """
    keystone_session = session()
    keystone_client = KeystoneClient(
        session=keystone_session,
        interface=getattr(keystone_session, "interface", None),
        region_name=getattr(keystone_session, "region_name", None),
    )

    try:
        projects = keystone_client.projects.list(user=keystone_session.get_user_id())
    except keystone_exceptions.Unauthorized:
        raise ResourceError("Failed to retrieve projects. Check your credentials.")
    project_names = [project.name for project in projects]

    if show == "widget":
        table_html = "<table>"
        for project in project_names:
            table_html += f"<tr><td>{project}</td></tr>"
        table_html += "</table>"

        display(widgets.HTML(table_html))
    elif show == "text":
        print("\n".join(project_names))
    elif show is None:
        return project_names
    else:
        raise CHIValueError("Invalid value for 'show' parameter.")


def use_project(project: str) -> None:
    """
    Sets the current project name.

    Args:
        project (str): The name of the project to use.

    Returns:
        None
    """
    set("project_name", project)
    print(f"Now using project: {project}")


def choose_project() -> None:
    """
    Displays a dropdown menu to select a project.

    Only works if running in a Ipynb notebook environment.
    """
    if _is_ipynb():
        projects = list_projects()

        project_dropdown = widgets.Dropdown(
            options=projects, description="Select Project"
        )

        output = widgets.Output()

        def on_change(change):
            with output:
                output.clear_output()
                use_project(change["new"])

        project_dropdown.observe(on_change, names="value")
        if projects:
            on_change({"new": projects[0]})

        display(widgets.VBox([project_dropdown, output]))
    else:
        print(
            "Choose project feature is only available in Jupyter notebook environment."
        )


def check_credentials() -> bool:
    """
    Prints authentication metadata (e.g. username, site) and if credentials are currently
    valid and user is authenticated.

    Returns:
        Whether the credentails are valid
    """
    try:
        print(f"Username: {os.getenv('OS_USERNAME')}")
        print(f"Currently site: {get('region_name')}")
        print(f"Currently project: {get('project_name')}")
        print("Projects:")
        for project in list_projects():
            print("\t", project)
        print("Authentication is valid.")
        return True
    except Exception as e:
        print("Authentication failed: ", str(e))
        return False


def set_log_level(level: str = "ERROR") -> None:
    """Configures logger for python-chi. By default, only errors are shown.
    Set to "DEBUG" to see debug level logging, which will show calls to external APIs.

    Args:
        level (str, optional): The log level. Defaults to "ERROR".
    """
    if level == "DEBUG":
        openstack.enable_logging(debug=True, http_debug=True)
        LOG.setLevel(logging.DEBUG)
    elif level == "ERROR":
        openstack.enable_logging(debug=False, http_debug=False)
        LOG.setLevel(logging.ERROR)
    else:
        raise CHIValueError(
            "Invalid log level value, please choose between 'ERROR' and 'DEBUG'"
        )


def session():
    """Get a Keystone Session object suitable for authenticating a client.

    Returns:
        keystoneauth1.session.Session: the authentication session object.
    """
    global _session
    if not _session:
        auth = loading.load_auth_from_conf_options(cfg.CONF, CONF_GROUP)
        sess = SessionLoader().load_from_conf_options(cfg.CONF, CONF_GROUP, auth=auth)
        _session = loading.load_adapter_from_conf_options(
            cfg.CONF, CONF_GROUP, session=sess
        )
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
        os.getenv("OS_AUTH_TYPE", os.getenv("OS_AUTH_METHOD", DEFAULT_AUTH_TYPE))
    )
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
