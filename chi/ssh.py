from __future__ import print_function

from fabric import Connection

from . import context

class Remote(object):
    def __init__(self, ip=None, server=None, user='cc'):
        if ip is None:
            if server is None:
                raise RuntimeError('ip or server must be provided.')
            ip = server.ip

        self.connection = Connection(ip, user=user, connect_kwargs={
            'key_filename': context.get('private_key_filename')
        })

    def run(self, *args, **kwargs):
        return self.connection.run(*args, **kwargs)

    def sudo(self, *args, **kwargs):
        return self.connection.sudo(*args, **kwargs)
