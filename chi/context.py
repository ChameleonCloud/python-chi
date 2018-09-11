from keystoneauth1.adapter import Adapter
from keystoneauth1.session import Session
from keystoneauth1.identity import v3
from os import getenv

_overrides = {}
_defaults = {}
_keys = [
    'auth_url',
    'key_name',
    'interface',
    'image',
    'keypair_private_key', # The path to the SSH private key
    'keypair_public_key',  # The path to the SSH public key
    'project_name',
    'project_domain_name',
    'region_name',
    'token',                # A valid OpenStack auth token
]

# Automatically set context from environment.
for key in _keys:
    _defaults[key] = getenv('OS_{}'.format(key.upper()))

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
    auth = v3.Token(auth_url=get('auth_url'),
                    token=get('token'),
                    project_name=get('project_name'),
                    project_domain_name=get('project_domain_name'))
    sess = Session(auth=auth)
    return Adapter(session=sess,
                   interface=get('interface'),
                   region_name=get('region_name'))
