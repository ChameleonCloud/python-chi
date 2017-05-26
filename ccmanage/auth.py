import os
import sys

import keystoneauth1 as ksa
import keystoneauth1.loading
import keystoneauth1.session

from hammers.osapi import load_osrc


OS_ENV_PREFIX = 'OS_'


def add_arguments(parser):
    """
    Inject our args into the user's parser
    """
    parser.add_argument('--osrc', type=str,
        help='OpenStack parameters file that overrides envvars.')


def auth_from_rc(rc):
    """
    Generates a Keystone Auth object from an OS parameter dictionary.  Dict
    key format is the same as environment variables.

    We do some dumb gymnastics because everything expects the parameters
    in their own cap/delim format:
    * envvar name:          OS_AUTH_URL
    * loader option name:      auth-url
    * loader argument name:    auth_url
    """
    assert all(key.startswith(OS_ENV_PREFIX) for key in rc)
    rc_opt_keymap = {key[3:].lower().replace('_', '-'): key for key in rc}
    loader = ksa.loading.get_plugin_loader('password')
    credentials = {}
    for opt in loader.get_options():
        if opt.name not in rc_opt_keymap:
            continue
        credentials[opt.name.replace('-', '_')] = rc[rc_opt_keymap[opt.name]]
    auth = loader.load_from_options(**credentials)
    return auth


def session_from_vars(os_vars):
    return ksa.session.Session(auth=auth_from_rc(os_vars))


def session_from_args(args, rc=False):
    """
    Combine the provided args with the environment vars and produce a Keystone
    session for use by clients. Optionally return the RC dictionary with the OS
    vars used to construct the session.
    """
    os_vars = {k: os.environ[k] for k in os.environ if k.startswith(OS_ENV_PREFIX)}
    if args.osrc:
        os_vars.update(load_osrc(args.osrc))
    try:
        session = ksa.session.Session(auth=auth_from_rc(os_vars))
    except ksa.exceptions.auth_plugins.MissingRequiredOptions as e:
        raise RuntimeError('Missing required OS values in env/rcfile ({})'.format(str(e)))

    if rc:
        return session, os_vars
    else:
        return session
