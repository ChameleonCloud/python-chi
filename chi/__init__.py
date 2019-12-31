from blazarclient.client import Client as BlazarClient
from glanceclient.client import Client as GlanceClient
from gnocchiclient.v1.client import Client as GnocchiClient
from neutronclient.v2_0.client import Client as NeutronClient
from novaclient.client import Client as NovaClient

from .context import reset, set, get, session


def blazar():
    return BlazarClient("1", service_type="reservation", session=session())


def glance():
    return GlanceClient("2", session=session())


def gnocchi():
    sess = session()
    session_options = dict(auth=sess.session.auth)
    adapter_options = dict(interface=sess.interface, region_name=sess.region_name)
    return GnocchiClient(
        adapter_options=adapter_options, session_options=session_options
    )


def neutron():
    return NeutronClient(session=session())


def nova():
    return NovaClient("2", session=session())
