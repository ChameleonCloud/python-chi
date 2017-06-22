import datetime
import json
import numbers
import time
import urllib.parse

from dateutil import tz

from blazarclient.client import Client as _BlazarClient # installed from github
# from heatclient.client import Client as HeatClient

from .server import Server
from .util import random_base32


BLAZAR_TIME_FORMAT = '%Y-%m-%d %H:%M'
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

DEFAULT_LEASE_LENGTH = datetime.timedelta(days=1)


def lease_create_args(name=None, start='now', length=None, end=None, nodes=1, resource_properties=''):
    if name is None:
        name = 'lease-{}'.format(random_base32(6))

    if start == 'now':
        start = datetime.datetime.now(tz=tz.tzutc()) + datetime.timedelta(seconds=70)

    if length is None and end is None:
        length = DEFAULT_LEASE_LENGTH
    elif length is not None and end is not None:
        raise ValueError("provide either 'length' or 'end', not both")

    if end is None:
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
    # kwargs['resource_properties'] = ['=', '$node_type', node_type]
    return lease_create_args(*args, **kwargs)


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


class Lease(object):
    def __init__(self, keystone_session, **lease_kwargs):
        self.session = keystone_session
        self.blazar = BlazarClient('1', self.session)
        self.servers = []
        self.lease = None

        lease_kwargs.setdefault('_preexisting', False)
        self._preexisting = lease_kwargs.pop('_preexisting')

        lease_kwargs.setdefault('_no_clean', False)
        self._noclean = lease_kwargs.pop('_no_clean')

        if self._preexisting:
            self.id = lease_kwargs['_id']
            self.refresh()
        else:
            lease_kwargs.setdefault('node_type', 'compute')
            self._lease_kwargs = lease_create_nodetype(**lease_kwargs)
            self.lease = self.blazar.lease.create(**self._lease_kwargs)
            self.id = self.lease['id']

        self.name = self.lease['name']
        self.reservation = self.lease['reservations'][0]['id']
        # print('created lease {}'.format(self.id))

    @classmethod
    def from_existing(cls, keystone_session, id):
        return cls(keystone_session, _preexisting=True, _id=id)

    def __repr__(self):
        netloc = urllib.parse.urlsplit(self.session.auth.auth_url).netloc
        if netloc.endswith(':5000'):
            # drop if default port
            netloc = netloc[:-5]
        return '<{} \'{}\' on {} ({})>'.format(self.__class__.__name__, self.name, netloc, self.id)

    def __enter__(self):
        if self.lease is None:
            # don't support reuse in multiple with's.
            raise RuntimeError('Lease context manager not reentrant')
        self.wait()
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        if exc is not None and self._noclean:
            print('Lease existing uncleanly (noclean = True).')
            return

        for server in self.servers:
            server.delete()
        if not self._preexisting:
            # don't auto-delete pre-existing leases
            self.delete()

    def refresh(self):
        self.lease = self.blazar.lease.get(self.id)

    @property
    def status(self):
        self.refresh()
        return self.lease['action'], self.lease['status']

    @property
    def ready(self):
        return self.status == ('START', 'COMPLETE')

    def wait(self):
        for _ in range(15):
            time.sleep(10)
            if self.ready:
                break
        else:
            raise RuntimeError('timeout, lease failed to start')

    def delete(self):
        self.blazar.lease.delete(self.id)
        self.lease = None

    def create_server(self, *sargs, **skwargs):
        server = Server(self, *sargs, **skwargs)
        self.servers.append(server)
        return server
