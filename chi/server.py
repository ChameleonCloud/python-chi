from datetime import datetime

from glanceclient.exc import NotFound as GlanceNotFound
from novaclient.exceptions import NotFound as NovaNotFound

from . import session, connection, glance, nova, neutron
from .keypair import Keypair
from .network import get_network_id, get_or_create_floating_ip
from .util import random_base32

__all__ = [
    'get_image',
    'get_image_id',
    'list_images',
    'show_image',
    'show_image_by_name',

    'get_flavor',
    'get_flavor_id',
    'show_flavor',
    'show_flavor_by_name',

    'get_server',
    'get_server_id',
    'list_servers',
    'delete_server',
    'show_server',
    'show_server_by_name',

    'create_server',
]

DEFAULT_IMAGE = 'CC-CentOS7'
BAREMETAL_FLAVOR = 'baremetal'

class ServerError(RuntimeError):
    def __init__(self, msg, server):
        super().__init__(msg)
        self.server = server


def instance_create_args(
    reservation,
    name=None,
    image=DEFAULT_IMAGE,
    flavor=None,
    key=None,
    net_ids=None,
    **kwargs
):
    if name is None:
        name = "instance-{}".format(random_base32(6))

    server_args = {
        "name": name,
        "flavor": flavor,
        "image": image,
        "scheduler_hints": {"reservation": reservation,},
        "key_name": key,
    }

    if net_ids is None:
        # automatically binds "the one" unless there's more than one
        server_args["nics"] = None
    else:
        # Not sure what fields are actually required and what they're called.
        # novaclient (and Nova HTTP API) docs seem vague. the command at
        # https://github.com/ChameleonCloud/horizon/blob/stable/liberty/openstack_dashboard/dashboards/project/instances/workflows/create_instance.py#L943
        # appears to POST a JSON akin to
        # {"server": {..., "networks": [{"uuid": "e8c33574-5423-436c-a45b-5bab78071b8a"}] ...}, "os:scheduler_hints": ...},
        server_args["nics"] = [
            {"net-id": netid, "v4-fixed-ip": ""} for netid in net_ids
        ]

    server_args.update(kwargs)
    return server_args


class Server(object):
    """
    Launches an instance on a lease.
    """

    def __init__(self, id=None, lease=None, key=None, image=DEFAULT_IMAGE, **kwargs):
        kwargs.setdefault("session", session())
        self.session = kwargs.pop("session")
        self.conn = connection(session=self.session)
        self.neutron = neutron(session=self.session)
        self.nova = nova(session=self.session)
        self.glance = glance(session=self.session)
        self.image = get_image(image)
        self.flavor = show_flavor_by_name(BAREMETAL_FLAVOR)

        self.ip = None
        self._fip = None
        self._fip_created = False
        self._preexisting = False

        kwargs.setdefault("_no_clean", False)
        self._noclean = kwargs.pop("_no_clean")

        net_ids = kwargs.pop("net_ids", None)
        net_name = kwargs.pop("net_name", "sharednet1")
        if net_ids is None and net_name is not None:
            net_ids = [get_network_id(net_name)]

        if id is not None:
            self._preexisting = True
            self.server = self.nova.servers.get(id)
        elif lease is not None:
            if key is None:
                key = Keypair().key_name
            server_kwargs = instance_create_args(
                lease.node_reservation,
                image=self.image,
                flavor=self.flavor,
                key=key,
                net_ids=net_ids,
                **kwargs
            )
            self.server = self.nova.servers.create(**server_kwargs)
        else:
            raise ValueError("Missing required argument: 'id' or 'lease' required.")

        self.id = self.server.id
        self.name = self.server.name

    def __repr__(self):
        return "<{} '{}' ({})>".format(self.__class__.__name__, self.name, self.id)

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        if exc is not None and self._noclean:
            print("Instance existing uncleanly (noclean = True).")
            return

        self.disassociate_floating_ip()
        if not self._preexisting:
            self.delete()

    def refresh(self):
        now = datetime.now()
        try:
            lr = self._last_refresh
        except AttributeError:
            pass  # expected failure on first pass
        else:
            # limit refreshes to once/sec.
            if (now - lr).total_seconds() < 1:
                return

        self.server = self.conn.compute.get_sever(self.server)
        self._last_refresh = now

    @property
    def status(self):
        self.refresh()
        return self.server.status

    @property
    def ready(self):
        return self.status == "ACTIVE"

    @property
    def error(self):
        return self.status == "ERROR"

    def wait(self):
        self.conn.compute.wait_for_server(self.server, wait=(60 * 20))

    def associate_floating_ip(self):
        if self.ip is not None:
            return self.ip

        self._fip, self._fip_created = get_or_create_floating_ip()
        self.ip = self._fip["floating_ip_address"]
        self.conn.compute.add_floating_ip_to_server(self.server.id, self.ip)
        return self.ip

    def disassociate_floating_ip(self):
        if self.ip is None:
            return

        self.conn.compute.remove_floating_ip_from_server(self.server.id, self.ip)
        if self._fip_created:
            self.neutron.delete_floatingip(self._fip["id"])

        self.ip = None
        self._fip = None
        self._fip_created = False

    def delete(self):
        self.conn.compute.delete_server(self.server)
        self.conn.compute.wait_for_server(self.server, status='DELETED')

    def rebuild(self, image_ref):
        self.image = get_image(image_ref)
        self.conn.compute.rebuild_server(self.server, image=self.image.id)


#########
# Images
#########

def get_image(ref):
    try:
        return show_image(ref)
    except GlanceNotFound:
        return show_image(get_image_id(ref))


def get_image_id(name):
    images = glance().images.list(filters={'name': name})
    if not images:
        raise ValueError(f'No images found matching name "{name}"')
    elif len(images) > 1:
        raise ValueError(f'Multiple images found matching name "{name}"')
    return images[0]['id']


def list_images():
    return glance().images.list()


def show_image(image_id):
    return glance().images.get(image_id)


def show_image_by_name(name):
    image_id = get_image_id(name)
    return show_image(image_id)


##########
# Flavors
##########

def get_flavor(ref):
    try:
        return show_flavor(ref)
    except NovaNotFound:
        return show_flavor(get_flavor_id(ref))


def get_flavor_id(name):
    flavor = next((f for f in nova().flavors.list() if f.name == name), None)
    if not flavor:
        raise ValueError(f'No flavors found matching name {name}')
    return flavor


def show_flavor(flavor_id):
    return nova().flavors.get(flavor_id)


def show_flavor_by_name(name):
    flavor_id = get_flavor_id(name)
    return show_flavor(flavor_id)


##########
# Servers
##########

def get_server(ref):
    try:
        return show_server(ref)
    except NovaNotFound:
        return show_server(get_server_id(ref))


def get_server_id(name):
    servers = [s for s in nova().servers.list() if s.name == name]
    if not servers:
        raise ValueError(f'No matching servers found for name "{name}"')
    elif len(servers) > 1:
        raise ValueError(f'Multiple matching servers found for name "{name}"')
    return servers[0]['id']


def list_servers():
    return nova().servers.list()


def delete_server(server_id):
    return nova().servers.delete(server_id)


def show_server(server_id):
    return nova().servers.get(server_id)


def show_server_by_name(name):
    server_id = get_server_id(name)
    return show_server(server_id)

##########
# Wizards
##########

def create_server(server_name, reservation_id, key_name=None, network_id=None,
                  network_name='sharednet1', nics=[], image_id=None,
                  image_name=DEFAULT_IMAGE, flavor_id=None,
                  flavor_name=BAREMETAL_FLAVOR, count=1):
    if not network_id:
        network_id = get_network_id(network_name)
    if not nics:
        nics = [{'net-id': network_id, 'v4-fixed-ip': ''}]
    if not image_id:
        image_id = get_image_id(image_name)
    if not flavor_id:
        flavor_id = get_flavor_id(flavor_name)
    return nova().servers.create(
        name=server_name,
        image=image_id,
        flavor=flavor_id,
        scheduler_hints={'reservation': reservation_id},
        key_name=key_name,
        nics=nics,
        min_count=count,
        max_count=count
    )
