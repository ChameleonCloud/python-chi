import base64
from datetime import datetime
from dateutil import tz
import os


def random_base32(n_bytes):
    rand_bytes = os.urandom(n_bytes)
    return base64.b32encode(rand_bytes).decode("ascii").strip("=")


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
