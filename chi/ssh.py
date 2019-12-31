from __future__ import print_function

from fabric import Connection
from paramiko.client import WarningPolicy

from . import context


class Remote(Connection):
    def __init__(self, ip=None, server=None, user="cc"):
        if ip is None:
            if server is None:
                raise ValueError("ip or server must be provided.")
            ip = server.ip

        key_filename = context.get("keypair_private_key")
        connect_kwargs = {"key_filename": key_filename}
        super(Remote, self).__init__(ip, user=user, connect_kwargs=connect_kwargs)
        # Default policy is to reject unknown hosts - for our use-case,
        # printing a warning is probably enough, given the host is almost
        # always guaranteed to be unknown.
        self.client.set_missing_host_key_policy(WarningPolicy)
