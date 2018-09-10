from keystoneauth1 import adapter, session
from keystoneauth1.identity import v3
from os import getenv

_context = {}
_keys = [
    'auth_url',     # THe OpenStack Keystone authentication URL
    'key_filename', # The path to the SSH private key
    'key_name',     # The OpenStack SSH key name
    'image',        # The OpenStack image name
    'project_name', # The OpenStack project name
    'token',        # A valid OpenStack auth token
]

# Automatically set context from environment.
for key in _keys:
    _context[key] = getenv('OS_{}'.format(key.upper()))

def set(key, value):
    if not key in _keys:
        raise KeyError('Unknown setting "{}"'.format(key))
    _context[key] = value

def get(key, default=None):
    if not key in _keys:
        raise KeyError('Unknown setting "{}"'.format(key))
    return _context.get(key, default)

def session():
    auth = v3.Token(auth_url=fetch('auth_url'),
                    token=fetch('token'),
                    project_name=fetch('project_name'),
                    project_domain_name='default')
    sess = session.Session(auth=auth)
    return adapter.Adapter(session=sess, region_name=fetch('region_name'))
