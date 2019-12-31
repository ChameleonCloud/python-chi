from keystoneauth1.adapter import Adapter
from keystoneauth1.session import Session
from keystoneauth1.identity import v3
from os import getenv

_overrides = {}
_defaults = {}
_keys = [
    "auth_url",
    "key_name",
    "interface",
    "image",
    "keypair_private_key",  # The path to the SSH private key
    "keypair_public_key",  # The path to the SSH public key
    "project_id",  # Project Keystone ID
    "project_name",  # Project Keystone name (if not using ID)
    "project_domain_name",  # Project Keystone domain (if not using ID)
    "region_name",
    "token",  # A valid OpenStack auth token
    "username",  # Auth user (if not using token)
    "user_domain_name",  # Auth user domain (if not using token)
    "password",  # Auth password (if not using token)
]

# Automatically set context from environment.
for key in _keys:
    _defaults[key] = getenv("OS_{}".format(key.upper()))


def reset():
    global _overrides
    global _session
    _overrides = {}
    _session = None


def set(key, value):
    global _overrides
    if not key in _keys:
        raise KeyError('Unknown setting "{}"'.format(key))
    _overrides[key] = value


def get(key, default=None):
    global _defaults
    global _overrides
    if not key in _keys:
        raise KeyError('Unknown setting "{}"'.format(key))
    return _overrides.get(key, _defaults.get(key, default))


def session():
    auth_kwargs = dict(auth_url=get("auth_url"))

    token = get("token")

    if token:
        auth_klass = v3.Token
        auth_kwargs.update(token=token)
    else:
        auth_klass = v3.Password
        auth_kwargs.update(
            username=get("username"),
            user_domain_name=get("user_domain_name"),
            password=get("password"),
        )

    project_id = get("project_id")

    if project_id:
        auth_kwargs.update(project_id=project_id)
    else:
        auth_kwargs.update(
            project_name=get("project_name"),
            project_domain_name=get("project_domain_name"),
        )

    auth = auth_klass(**auth_kwargs)
    sess = Session(auth=auth)
    return Adapter(
        session=sess, interface=get("interface"), region_name=get("region_name")
    )
