from blazarclient.client import Client as BlazarClient
from glanceclient.client import Client as GlanceClient
from gnocchiclient.v1.client import Client as GnocchiClient
from neutronclient.v2_0.client import Client as NeutronClient
from novaclient.client import Client as NovaClient

from .context import reset, set, get, session


__all__ = [
    'reset', 'set', 'get', 'session',
    'blazar', 'glance', 'gnocchi', 'neutron', 'nova'
]

session_factory = session


def blazar(session=None):
    return BlazarClient('1', service_type='reservation',
        session=(session or session_factory()))


def glance(session=None):
    return GlanceClient('2', session=(session or session_factory()))


def gnocchi(session=None):
    sess = session or session_factory()
    session_options = dict(auth=sess.session.auth)
    adapter_options = dict(interface=sess.interface, region_name=sess.region_name)
    return GnocchiClient(
        adapter_options=adapter_options, session_options=session_options
    )


def neutron(session=None):
    return NeutronClient(session=(session or session_factory()))


def nova(session=None):
    return NovaClient('2', session=(session or session_factory()))
