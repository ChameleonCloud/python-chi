"""
Lease management
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import json
import numbers
import os
import sys
import time
import urllib.parse

from dateutil import tz

from blazarclient.client import Client as _BlazarClient # installed from github
# from heatclient.client import Client as HeatClient

from .server import Server, ServerError
from .util import random_base32

__all__ = ['lease_create_args', 'lease_create_nodetype', 'Lease',
           'BlazarClient']

BLAZAR_TIME_FORMAT = '%Y-%m-%d %H:%M'
NODE_TYPES = {
    'compute_haswell',
    'compute_skylake',
    'compute_haswell_ib',
    'storage',
    'storage_hierarchy',
    'gpu_p100',
    'gpu_p100_nvlink',
    'gpu_k80',
    'gpu_m40',
    'fpga',
    'lowpower_xeon',
    'atom',
    'arm64',
}
DEFAULT_NODE_TYPE = 'compute_haswell'
DEFAULT_LEASE_LENGTH = datetime.timedelta(days=1)


def lease_create_args(name=None, start='now', length=None, end=None,
        nodes=1, resource_properties=''):
    """
    Generates the nested object that needs to be sent to the Blazar client
    to create the lease. Provides useful defaults for Chameleon.

    :param str name: name of lease. If ``None``, generates a random name.
    :param str/datetime start: when to start lease as a
        :py:class:`datetime.datetime` object, or if the string ``'now'``,
        starts in about a minute.
    :param length: length of time as a :py:class:`datetime.timedelta` object or
        number of seconds as a number. Defaults to 1 day.
    :param datetime.datetime end: when to end the lease. Provide only this or
        `length`, not both.
    :param int nodes: number of nodes to reserve.
    :param resource_properties: object that is JSON-encoded and sent as the
        ``resource_properties`` value to Blazar. Commonly used to specify
        node types.
    """
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
    """
    Wrapper for :py:func:`lease_create_args` that adds the
    ``resource_properties`` payload to specify node type.

    :param str node_type: Node type to filter by, ``compute_haswell``, et al.
    :raises ValueError: if there is no `node_type` named argument.
    """
    try:
        node_type = kwargs.pop('node_type')
    except KeyError:
        raise ValueError('no node_type specified')
    if node_type not in NODE_TYPES:
        print('warning: unknown node_type ("{}")'.format(node_type), file=sys.stderr)
        # raise ValueError('unknown node_type ("{}")'.format(node_type))
    kwargs['resource_properties'] = ['=', '$node_type', node_type]
    return lease_create_args(*args, **kwargs)


class BlazarClient(object):
    """
    Older BlazarClients didn't support sessions, just a token, so it
    behaves poorly after its token expires. This is a thin wrapper that
    recreates the real client every X minutes to avoid expiration.
    """
    def __init__(self, version, session):
        self._version = version
        self._session = session
        self._client_age = None
        self._create_client()

    def _create_client(self):
        try:
            self._bc = _BlazarClient(
                self._version,
                blazar_url=self._session.get_endpoint(service_type='reservation',
                                                      region_name=os.environ.get('OS_REGION_NAME')),
                auth_token=self._session.get_token(),
            )
        except TypeError: # probably a newer version that wants session
            self._bc = _BlazarClient(
                self._version,
                session=self._session,
                service_type='reservation',
                region_name=os.environ.get('OS_REGION_NAME'),
            )

        self._client_age = time.monotonic()

    def __getattr__(self, attr):
        if time.monotonic() - self._client_age > 20*60:
            self._create_client()
        return getattr(self._bc, attr)


class Lease(object):
    '''
    Creates and manages a lease, optionally with a context manager (``with``).

    .. code-block:: python

        with Lease(session, node_type='compute_haswell') as lease:
            instance = lease.create_server()
            ...

    When using the context manager, on entering it will wait for the lease
    to launch, then on exiting it will delete the lease, which in-turn
    also deletes the instances launched with it.

    :param keystone_session: session object
    :param bool sequester: If the context manager catches that an instance
        failed to start, it will not delete the lease, but rather extend it
        and rename it with the ID of the instance that failed.
    :param bool _no_clean: Don't delete the lease at the end of a context
        manager
    :param lease_kwargs: Parameters passed through to
        :py:func:`lease_create_nodetype` and in turn
        :py:func:`lease_create_args`
    '''

    def __init__(self, keystone_session, **lease_kwargs):
        self.session = keystone_session
        self.blazar = BlazarClient('1', self.session)
        self.servers = []
        self.lease = None

        self._sequester = lease_kwargs.pop('sequester', False)

        lease_kwargs.setdefault('_preexisting', False)
        self._preexisting = lease_kwargs.pop('_preexisting')

        lease_kwargs.setdefault('_no_clean', False)
        self._noclean = lease_kwargs.pop('_no_clean')

        if self._preexisting:
            self.id = lease_kwargs['_id']
            self.refresh()
        else:
            lease_kwargs.setdefault('node_type', DEFAULT_NODE_TYPE)
            self._lease_kwargs = lease_create_nodetype(**lease_kwargs)
            self.lease = self.blazar.lease.create(**self._lease_kwargs)
            self.id = self.lease['id']

        self.name = self.lease['name']
        self.reservation = self.lease['reservations'][0]['id']
        # print('created lease {}'.format(self.id))

    @classmethod
    def from_existing(cls, keystone_session, id):
        """
        Attach to an existing lease by ID. When using in conjunction with the
        context manager, it will *not* delete the lease at the end.
        """
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

        if isinstance(exc, ServerError) and self._sequester:
            print('Instance failed to start, sequestering lease')
            self.blazar.lease.update(
                lease_id=self.id,
                name='sequester-error-instance-{}'.format(exc.server.id),
                prolong_for='6d',
            )
            return

        # if lease exists, delete instances
        current_lease = self.blazar.lease.get(self.id)
        if current_lease:
            for server in self.servers:
                server.delete()

        if not self._preexisting:
            # don't auto-delete pre-existing leases
            self.delete()

    def refresh(self):
        """Updates the lease data"""
        self.lease = self.blazar.lease.get(self.id)

    @property
    def status(self):
        """Refreshes and returns the status of the lease."""
        self.refresh()
        # NOTE(priteau): Temporary compatibility with old and new lease status
        if self.lease.get('action') is not None:
            return self.lease['action'], self.lease['status']
        else:
            return self.lease['status']

    @property
    def ready(self):
        """Returns True if the lease has started."""
        # NOTE(priteau): Temporary compatibility with old and new lease status
        if self.lease.get('action') is not None:
            return self.status == ('START', 'COMPLETE')
        else:
            return self.status == 'ACTIVE'

    def wait(self):
        """Blocks for up to 150 seconds, waiting for the lease to be ready.
        Raises a RuntimeError if it times out."""
        for _ in range(15):
            time.sleep(10)
            if self.ready:
                break
        else:
            raise RuntimeError('timeout, lease failed to start')

    def delete(self):
        """Deletes the lease"""
        self.blazar.lease.delete(self.id)
        self.lease = None

    def create_server(self, *sargs, **skwargs):
        """Generates instances using the resource of the lease. Arguments
        are passed to :py:class:`ccmanage.server.Server` and returns same
        object."""
        server = Server(self, *sargs, **skwargs)
        self.servers.append(server)
        return server
