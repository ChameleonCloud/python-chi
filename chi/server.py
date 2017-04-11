import time
import urllib.parse

from novaclient.client import Client as NovaClient
from novaclient.exceptions import NotFound

from .util import random_base32


DEFAULT_IMAGE = '0f216b1f-7841-451b-8971-d383364e01a6' # CC-CentOS7 as of 4/6/17


def instance_create_args(lease, name=None, image=DEFAULT_IMAGE, key=None):
    if name is None:
        name = 'instance-{}'.format(random_base32(6))

    return {
        'name': name,
        'flavor': 'baremetal',
        'image': image,
        # 'reservation_id': lease['reservations'][0]['id'],
        'scheduler_hints': {
            'reservation': lease['reservations'][0]['id'],
        },
        # 'nics': '', # automatically binds one, not needed unless want non-default?
        'key_name': key,
    }


def get_create_floatingip(novaclient):
    created = False
    ips = novaclient.floating_ips.list()
    unbound = (ip for ip in ips if ip.instance_id is None)
    try:
        fip = next(unbound)
    except StopIteration:
        fip = novaclient.floating_ips.create('ext-net')
        created = True
    return created, fip


def resolve_image_idname(novaclient, idname):
    try:
        return novaclient.images.find(id=idname)
    except NotFound:
        return novaclient.images.find(name=idname)


class Server(object):
    def __init__(self, lease, key='default', image=DEFAULT_IMAGE):
        self.lease = lease
        self.session = self.lease.session
        self.nova = NovaClient('2', session=self.session)
        self.ip = None
        self._fip = None

        self.image = resolve_image_idname(self.nova, image)
        self.server_kwargs = instance_create_args(self.lease.lease, key=key, image=self.image)
        self.server = self.nova.servers.create(**self.server_kwargs)
        self.id = self.server.id
        self.name = self.server.name
        # print('created instance {}'.format(self.server.id))

    def __repr__(self):
        netloc = urllib.parse.urlsplit(self.session.auth.auth_url).netloc
        if netloc.endswith(':5000'):
            # drop if default port
            netloc = netloc[:-5]
        return '<{} \'{}\' on {} ({})>'.format(self.__class__.__name__, self.name, netloc, self.id)

    def refresh(self):
        now = time.monotonic()
        try:
            lr = self._last_refresh
        except AttributeError:
            pass # expected failure on first pass
        else:
            # limit refreshes to once/sec.
            if now - lr < 1:
                return

        self.server.get()
        self._last_refresh = now

    @property
    def status(self):
        self.refresh()
        return self.server.status

    @property
    def ready(self):
        return self.status == 'ACTIVE'

    @property
    def error(self):
        return self.status == 'ERROR'

    def wait(self):
        # check a couple for fast failures
        for _ in range(3):
            time.sleep(10)
            if self.error:
                raise RuntimeError(self.server.fault)
        time.sleep(5 * 60)
        for _ in range(100):
            time.sleep(10)
            if self.ready:
                break
            if self.error:
                raise RuntimeError(self.server.fault)
        else:
            raise RuntimeError('timeout, server failed to start')
        # print('server active')

    def associate_floating_ip(self):
        created, self._fip = get_create_floatingip(self.nova)
        self.server.add_floating_ip(self._fip)
        self.ip = self._fip.ip
        return self.ip

    def delete(self):
        if self._fip:
            self._fip.delete()
        self.server.delete()

    def run(self, cmd):
        pass

    def sudo(self, cmd):
        pass
