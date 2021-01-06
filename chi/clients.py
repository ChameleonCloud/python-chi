from .context import session

session_factory = session


def connection(session=None):
    """Get connection context for OpenStack SDK.

    The returned :class:`openstack.connection.Connection` object has
    several proxy modules attached for each service provided by the cloud.
    """
    import openstack
    return openstack.connect(session=(session or session_factory()))


def blazar(session=None):
    from blazarclient.client import Client as BlazarClient
    return BlazarClient('1', service_type='reservation',
        session=(session or session_factory()))


def glance(session=None):
    from glanceclient.client import Client as GlanceClient
    return GlanceClient('2', session=(session or session_factory()))


def gnocchi(session=None):
    from gnocchiclient.v1.client import Client as GnocchiClient
    sess = session or session_factory()
    session_options = dict(auth=sess.session.auth)
    adapter_options = dict(interface=sess.interface, region_name=sess.region_name)
    return GnocchiClient(
        adapter_options=adapter_options, session_options=session_options
    )


def neutron(session=None):
    from neutronclient.v2_0.client import Client as NeutronClient
    return NeutronClient(session=(session or session_factory()))


def nova(session=None):
    from novaclient.client import Client as NovaClient
    return NovaClient('2', session=(session or session_factory()))


def ironic(session=None):
    from ironicclient import client as IronicClient
    return IronicClient.get_client(
        '1',
        session=session,
        region_name=getattr(session, 'region_name', None),
        # Ironic client defaults to 1.9 currently,
        # "latest" will be latest the API supports
        os_ironic_api_version='latest'
    )


def keystone(session=None):
    from keystoneclient.v3.client import Client as KeystoneClient
    sess = session or session_factory()
    # We have to set interface/region_name also on the Keystone client, as it
    # does not smartly inherit the value sent in on a KSA Adapter instance.
    return KeystoneClient(session=sess,
        interface=getattr(sess, 'interface', None),
        region_name=getattr(sess, 'region_name', None))
