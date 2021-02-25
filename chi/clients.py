from .context import session

# Import all of the client classes for type annotations.
# We have to do this because we lazy-import the client definitions
# inside each function to reduce runtime dependencies.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from openstack.connection import Connection
    from blazarclient.client import Client as BlazarClient
    from glanceclient.client import Client as GlanceClient
    from gnocchiclient.v1.client import Client as GnocchiClient
    from neutronclient.v2_0.client import Client as NeutronClient
    from novaclient.client import Client as NovaClient
    from ironicclient import client as IronicClient
    from keystoneclient.v3.client import Client as KeystoneClient


session_factory = session

NOVA_API_VERSION = "2.10"


def connection(session=None) -> "Connection":
    """Get connection context for OpenStack SDK.

    The returned :class:`openstack.connection.Connection` object has
    several proxy modules attached for each service provided by the cloud.
    """
    from openstack.config import cloud_region
    from openstack.connection import Connection
    sess = session or session_factory()
    if hasattr(sess, 'session'):
        # Handle Adapters, which have a nested Session
        sess = sess.session
    cloud_config = cloud_region.from_session(sess)
    return Connection(
        config=cloud_config,
        compute_api_version=NOVA_API_VERSION,
    )


def blazar(session=None) -> "BlazarClient":
    from blazarclient.client import Client as BlazarClient
    return BlazarClient('1', service_type='reservation',
        session=(session or session_factory()))


def glance(session=None) -> "GlanceClient":
    from glanceclient.client import Client as GlanceClient
    return GlanceClient('2', session=(session or session_factory()))


def gnocchi(session=None) -> "GnocchiClient":
    from gnocchiclient.v1.client import Client as GnocchiClient
    sess = session or session_factory()
    session_options = dict(auth=sess.session.auth)
    adapter_options = dict(interface=sess.interface, region_name=sess.region_name)
    return GnocchiClient(
        adapter_options=adapter_options, session_options=session_options
    )


def neutron(session=None) -> "NeutronClient":
    from neutronclient.v2_0.client import Client as NeutronClient
    return NeutronClient(session=(session or session_factory()))


def nova(session=None) -> "NovaClient":
    from novaclient.client import Client as NovaClient
    return NovaClient(NOVA_API_VERSION, session=(session or session_factory()))


def ironic(session=None) -> "IronicClient":
    from ironicclient import client as IronicClient
    return IronicClient.get_client(
        '1',
        session=session,
        region_name=getattr(session, 'region_name', None),
        # Ironic client defaults to 1.9 currently,
        # "latest" will be latest the API supports
        os_ironic_api_version='latest'
    )


def keystone(session=None) -> "KeystoneClient":
    from keystoneclient.v3.client import Client as KeystoneClient
    sess = session or session_factory()
    # We have to set interface/region_name also on the Keystone client, as it
    # does not smartly inherit the value sent in on a KSA Adapter instance.
    return KeystoneClient(session=sess,
        interface=getattr(sess, 'interface', None),
        region_name=getattr(sess, 'region_name', None))
