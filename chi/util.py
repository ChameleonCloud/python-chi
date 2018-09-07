import base64
import os

def random_base32(n_bytes):
    rand_bytes = os.urandom(n_bytes)
    return base64.b32encode(rand_bytes).decode('ascii').strip('=')
