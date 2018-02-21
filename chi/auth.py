"""
Generate "real" Keystone auth objects versus the DIY methods like in
:py:mod:`hammers.osapi`
"""
import os
import sys

import keystoneauth1 as ksa
import keystoneauth1.loading
import keystoneauth1.session

from hammers.osapi import load_osrc


OS_ENV_PREFIX = 'OS_'


def add_arguments(parser):
    """
    Inject our args into the user's :py:class:`~argparse.ArgumentParser`
    `parser`. The resulting argument namespace can be inspected by
    :py:func:`session_from_args`.
    """
    parser.add_argument('--osrc', type=str,
        help='OpenStack parameters file that overrides envvars.')


def check_make_equal(m, k1, k2):
    """
    Checks that keys `k1` and `k2` in mutable mapping `m` are equal. If they
    differ, a ``ValueError`` is raised. If one is missing, it is set to the
    value of the other. If both are missing, nothing happens.

    No value is returned, `m` is modified in-place.
    """
    try:
        if m[k1] == m[k2]:
            return
        else:
            raise ValueError('values differ for keys {!r} and {!r}'.format(k1, k2))
    except KeyError:
        # one or both of them isn't there
        if k1 in m:
            m[k2] = m[k1]
        elif k2 in m:
            m[k1] = m[k2]
        #else:
            #both missing.../shrug


def auth_from_rc(rc):
    """
    Generates a Keystone Auth object from an OS parameter dictionary.  Dict
    key format is the same as environment variables (``OS_AUTH_URL``, et al.)

    We do some dumb gymnastics because everything expects the parameters
    in their own cap/delim format:

    * envvar name:          ``OS_AUTH_URL``
    * loader option name:      ``auth-url``
    * loader argument name:    ``auth_url``
    """
    if not all(key.startswith(OS_ENV_PREFIX) for key in rc):
        raise ValueError('unknown options without OS_ prefix')

    check_make_equal(rc, 'OS_PROJECT_NAME', 'OS_TENANT_NAME')
    check_make_equal(rc, 'OS_PROJECT_ID', 'OS_TENANT_ID')

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
    """
    Generates a :py:class:`keystoneauth1.session.Session` object from an
    OS parameter dictionary akin to :py:func:`auth_from_rc`. This one is
    generally more useful as the session object can be used directly with most
    clients:

    >>> from novaclient.client import Client as NovaClient
    >>> from ccmanage.auth import session_from_vars
    >>> session = session_from_vars({'OS_AUTH_URL': ...})
    >>> nova = NovaClient('2', session=session)
    """
    return ksa.session.Session(auth=auth_from_rc(os_vars))


def session_from_args(args=None, rc=False):
    """
    Combine the ``osrc`` attribute in the namespace `args` (if provided) with
    the environment vars and produce a Keystone session for use by clients.

    Optionally return the RC dictionary with the OS vars used to construct the
    session as the second value in a 2-tuple if `rc` is true.
    """
    os_vars = {k: os.environ[k] for k in os.environ if k.startswith(OS_ENV_PREFIX)}
    if args and args.osrc:
        os_vars.update(load_osrc(args.osrc))
    try:
        session = ksa.session.Session(auth=auth_from_rc(os_vars))
    except ksa.exceptions.auth_plugins.MissingRequiredOptions as e:
        raise RuntimeError('Missing required OS values in env/rcfile ({})'.format(str(e)))

    if rc:
        return session, os_vars
    else:
        return session
