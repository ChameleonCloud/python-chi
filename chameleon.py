#!/usr/bin/env python
import argparse
import base64
import datetime
import json
import numbers
import os
import secrets
import sys
import time

from dateutil import tz

from blazarclient.client import Client as _BlazarClient # installed from github
from heatclient.client import Client as HeatClient
import keystoneauth1 as ksa
import keystoneauth1.loading
import keystoneauth1.session
from novaclient.client import Client as NovaClient
from novaclient import exceptions as novaexceptions

from hammers import osapi

OS_ENV_PREFIX = 'OS_'

BLAZAR_TIME_FORMAT = '%Y-%m-%d %H:%M'
DEFAULT_IMAGE = '0f216b1f-7841-451b-8971-d383364e01a6' # CC-CentOS7 as of 4/6/17
NODE_TYPES = {
    'compute',
    'compute_ib',
    'storage',
    'storage_hierarchy',
    'gpu_p100',
    'gpu_k80',
    'gpu_m40',
    'fpga',
    'lowpower_xeon',
    'atom',
    'arm64',
}


def auth_from_rc(rc):
    """
    Fun with naming schemes:
    * envvar name:          OS_AUTH_URL
    * loader option name:      auth-url
    * loader argument name:    auth_url
    """
    rc_opt_keymap = {key[3:].lower().replace('_', '-'): key for key in rc}
    loader = ksa.loading.get_plugin_loader('password')
    credentials = {}
    for opt in loader.get_options():
        if opt.name not in rc_opt_keymap:
            continue
        credentials[opt.name.replace('-', '_')] = rc[rc_opt_keymap[opt.name]]
    auth = loader.load_from_options(**credentials)
    return auth


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


def lease_create_args(name=None, start='now', length=60*60*24, nodes=1, resource_properties=''):
    if name is None:
        name = 'lease-{}'.format(random_base32(6))

    if start == 'now':
        start = datetime.datetime.now(tz=tz.tzutc()) + datetime.timedelta(seconds=70)
    if isinstance(length, numbers.Number):
        length = datetime.timedelta(seconds=length)

    end = start + length

    if resource_properties:
        resource_properties = json.dumps(resource_properties)

    reservations = [{
        'resource_type': 'physical:host',
        'resource_properties': resource_properties,
        'hypervisor_properties': '',
        'min': str(nodes), 'max': str(nodes),
    }]

    query = {
        'name': name,
        'start': start.strftime(BLAZAR_TIME_FORMAT),
        'end': end.strftime(BLAZAR_TIME_FORMAT),
        'reservations': reservations,
        'events': [],
    }
    return query


def lease_create_nodetype(*args, **kwargs):
    try:
        node_type = kwargs.pop('node_type')
    except KeyError:
        raise ValueError('no node_type specified')
    if node_type not in NODE_TYPES:
        raise ValueError('unknown node_type ("{}")'.format(node_type))
    kwargs['resource_properties'] = ['=', '$node_type', node_type]
    return lease_create_args(*args, **kwargs)


def random_base32(n_bytes):
    tok = secrets.token_bytes(n_bytes)
    return base64.b32encode(tok).decode('ascii').strip('=')


def resolve_image_idname(novaclient, idname):
    try:
        return novaclient.images.find(id=idname)
    except novaclient.exceptions.NotFound:
        return novaclient.images.find(name=idname)


class BlazarClient(object):
    """
    Current BlazarClient doesn't support sessions, just a token, so it
    behaves poorly after its token expires. This is a thin wrapper that
    recreates the real client every X minutes to avoid expiration.
    """
    def __init__(self, version, session):
        self._version = version
        self._session = session
        self._client_age = None
        self._create_client()

    def _create_client(self):
        self._bc = _BlazarClient(
            self._version,
            blazar_url=self._session.get_endpoint(service_type='reservation'),
            auth_token=self._session.get_token(),
        )
        self._client_age = time.monotonic()

    def __getattr__(self, attr):
        if time.monotonic() - self._client_age > 20*60:
            self._create_client()
        return getattr(self._bc, attr)


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser()

    parser.add_argument('--node-type', type=str, default='compute')
    parser.add_argument('--osrc', type=str,
        help='Connection parameter file. Should include password. envars used '
        'if not provided by this file.')
    parser.add_argument('--key-name', type=str, default='default',
        help='SSH keypair name on OS used to create an instance.')

    args = parser.parse_args()

    os_vars = {k: os.environ[k] for k in os.environ if k.startswith(OS_ENV_PREFIX)}
    if args.osrc:
        os_vars.update(osapi.load_osrc(args.osrc))
    try:
        sess = ksa.session.Session(auth=auth_from_rc(os_vars))
    except ksa.exceptions.auth_plugins.MissingRequiredOptions as e:
        print(
            'Missing required OS values in env/rcfile ({})'
            .format(str(e)),
            file=sys.stderr
        )
        return -1

    nc = NovaClient('2', session=sess)
    bc = BlazarClient('1', session=sess)

    lease_kwargs = lease_create_nodetype(node_type=args.node_type)
    lease = bc.lease.create(**lease_kwargs)
    lease_id = lease['id']

    print('created lease {}'.format(lease_id))

    for _ in range(10):
        time.sleep(10)
        lease = bc.lease.get(lease_id)
        if lease['action'] == 'START' and lease['status'] == 'COMPLETE':
            break
    else:
        raise RuntimeError('timeout, lease failed to start')

    image = resolve_image_idname(nc, DEFAULT_IMAGE)
    server_kwargs = instance_create_args(lease, key=args.key_name, image=image)
    server = nc.servers.create(**server_kwargs)

    print('created instance {}'.format(server.id))
    # check a couple for fast failures
    for _ in range(3):
        time.sleep(10)
        server.get()
        if server.status == 'ERROR':
            raise RuntimeError(server.fault)
    time.sleep(5 * 60)
    for _ in range(100):
        time.sleep(10)
        server.get()
        if server.status == 'ERROR':
            raise RuntimeError(server.fault)
        if server.status == 'ACTIVE':
            break
    else:
        raise RuntimeError('timeout, server failed to start')
    print('server active')

    created, fip = get_create_floatingip(nc)
    server.add_floating_ip(fip)
    print('bound ip {ip} to server. \'ssh cc@{ip}\' available'.format(ip=fip.ip))

    input('Press enter to terminate lease/server.')

    fip.delete()
    server.delete()
    bc.lease.delete(lease_id)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
