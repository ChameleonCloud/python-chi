"""
Keypair management
"""
import base64
import hashlib

from novaclient.client import Client as NovaClient
from novaclient.exceptions import NotFound

from . import context


def ssh_fingerprint(key):
    key = base64.b64decode(key.split()[1].encode("ascii"))
    fingerprint = hashlib.md5(key).hexdigest()
    return fingerprint


def key_pair_name(fingerprint):
    return "keypair-{}".format(fingerprint)


class Keypair(object):
    def __init__(self, **kwargs):
        kwargs.setdefault("session", context.session())

        key_filename = kwargs.get(
            "keypair_public_key", context.get("keypair_public_key")
        )
        session = kwargs.get("session")

        self.nova = NovaClient("2", session=session)

        with open(key_filename) as f:
            self.key = [line.strip() for line in f.readlines() if line.strip()][0]
            fingerprint = ssh_fingerprint(self.key)
            self.key_name = key_pair_name(fingerprint)

        try:
            self.key_pair = self.nova.keypairs.get(self.key_name)
        except NotFound:
            self.key_pair = self.nova.keypairs.create(
                self.key_name, public_key=self.key
            )
