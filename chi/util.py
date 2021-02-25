import base64
from datetime import datetime
from dateutil import tz
from hashlib import md5
import os


def random_base32(n_bytes):
    rand_bytes = os.urandom(n_bytes)
    return base64.b32encode(rand_bytes).decode("ascii").strip("=")


def sshkey_fingerprint(public_key):
    # See: https://stackoverflow.com/a/6682934
    key = base64.b64decode(public_key.strip().split()[1].encode("ascii"))
    fp_plain = md5(key).hexdigest()
    return ':'.join(a + b for a, b in zip(fp_plain[::2], fp_plain[1::2]))


def get_public_network(neutronclient):
    nets = neutronclient.list_networks()["networks"]
    for net in nets:
        if net["router:external"] != True:
            continue
        pubnet_id = net["id"]
        break
    else:
        raise RuntimeError("couldn't find public net")
    return pubnet_id


def utcnow():
    return datetime.now(tz=tz.tzutc())
