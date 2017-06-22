import base64
from . import secrets


def random_base32(n_bytes):
    tok = secrets.token_bytes(n_bytes)
    return base64.b32encode(tok).decode('ascii').strip('=')
