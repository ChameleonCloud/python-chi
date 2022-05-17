from datetime import datetime
from operator import attrgetter
import socket
import time

from novaclient.exceptions import NotFound
from novaclient.v2.flavor_access import FlavorAccess as NovaFlavor
from novaclient.v2.keypairs import Keypair as NovaKeypair
from novaclient.v2.servers import Server as NovaServer

from openstack.compute.v2.server import Server as OpenStackServer

from .clients import connection, glance, nova, neutron
from .context import get as get_from_context, session
from .image import get_image, get_image_id
from .keypair import Keypair
from .network import (get_network_id, get_or_create_floating_ip,
                      get_floating_ip, get_free_floating_ip)
from .util import random_base32, sshkey_fingerprint


__all__ = [
    'get_flavor',
    'get_flavor_id',
    'show_flavor',
    'show_flavor_by_name',
    'list_flavors',

    'get_server',
    'get_server_id',
    'list_servers',
    'delete_server',
    'show_server',
    'show_server_by_name',

    'create_server',

    'associate_floating_ip',
    'detach_floating_ip',

    'wait_for_active',
    'wait_for_tcp',

    'update_keypair',
]

DEFAULT_IMAGE = 'CC-Ubuntu20.04'
DEFAULT_NETWORK = 'sharednet1'
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
        "scheduler_hints": {"reservation": reservation, },
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
    """A wrapper object referring to a server instance.

    This class is helpful if you want to use a more object-oriented programming
    approach when building your infrastrucutre. With the Server abstraction,
    you can for example do the following:

    .. code-block:: python

        with Server(lease=my_lease, image=my_image) as server:
            # When entering this block, the server is guaranteed to be
            # in the "ACTIVE" state if it launched successfully.
            server.associate_floating_ip()
            # Interact with the server (via, e.g., SSH), then...
        # When the block exits, the server will be terminated and deleted

    The above example uses a context manager. The class can also be used
    without a context manager:

    .. code-block:: python

        # Triggers the launch of the server instance
        server = Server(lease=my_lease, image=my_image)
        # Wait for server to be active
        server.wait()
        server.associate_floating_ip()
        # Interact with the server, then...
        server.delete()

    Attributes:
        id (str): The ID of an existing server instance. Use this if you have
            already launched the instance and just want a convenient wrapper
            object for it.
        lease (Lease): The Lease the instance will be launched under.
        key (str): The name of the key pair to associate with the image. This
            is only applicable if launching the image; key pairs cannot be
            added to a server that has already been launched and wrapped via
            the ``id`` attribute.
        image (str): The name or ID of the disk iage to use.
        name (str): A name to give the new instance. (Defaults to an
            auto-generated name.)
        net_ids (list[str]): A list of network IDs to associate the instance
            with. The instance will obtain an IP address on each network
            during boot.

            .. note::
               For bare metal instances, the number of network IDs cannot
               exceed the number of enabled NICs on the bare metal node.

        kwargs: Additional keyword arguments to pass to Nova's server
            :meth:`~novaclient.v2.servers.ServerManager.create` function.
    """

    def __init__(self, id=None, lease=None, key=None, image=DEFAULT_IMAGE,
                 **kwargs):
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
        net_name = kwargs.pop("net_name", DEFAULT_NETWORK)
        if net_ids is None and net_name is not None:
            net_ids = [get_network_id(net_name)]

        if id is not None:
            self._preexisting = True
            self.server = self.conn.compute.get_server(id)
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
            self.server = self.conn.compute.create_server(**server_kwargs)
        else:
            raise ValueError(
                "Missing required argument: 'id' or 'lease' required.")

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
        """Poll the latest state of the server instance."""
        now = datetime.now()
        try:
            lr = self._last_refresh
        except AttributeError:
            pass  # expected failure on first pass
        else:
            # limit refreshes to once/sec.
            if (now - lr).total_seconds() < 1:
                return

        self.server = self.conn.compute.get_server(self.server)
        self._last_refresh = now

    @property
    def status(self) -> str:
        """Get the instance status."""
        self.refresh()
        return self.server.status

    @property
    def ready(self) -> bool:
        """Check if the instance is marked as active."""
        return self.status == "ACTIVE"

    @property
    def error(self) -> bool:
        """Check if the instance is in an error state."""
        return self.status == "ERROR"

    def wait(self):
        """Wait for the server instance to finish launching.

        If the server goes into an error state, this function will return early.
        """
        self.conn.compute.wait_for_server(self.server, wait=(60 * 20))

    def associate_floating_ip(self):
        """Attach a floating IP to this server instance."""
        if self.ip is not None:
            return self.ip

        self._fip, self._fip_created = get_or_create_floating_ip()
        self.ip = self._fip["floating_ip_address"]
        self.conn.compute.add_floating_ip_to_server(self.server.id, self.ip)
        return self.ip

    def disassociate_floating_ip(self):
        """Detach the floating IP attached to this server instance, if any."""
        if self.ip is None:
            return

        self.conn.compute.remove_floating_ip_from_server(
            self.server.id, self.ip)
        if self._fip_created:
            self.neutron.delete_floatingip(self._fip["id"])

        self.ip = None
        self._fip = None
        self._fip_created = False

    def delete(self):
        """Delete this server instance."""
        self.conn.compute.delete_server(self.server)
        self.conn.compute.wait_for_delete(self.server)

    def rebuild(self, image_ref):
        """Rebuild this server instance.

        .. note::
           For bare metal instances, this effectively redeploys to the host and
           overwrites the local disk.
        """
        self.image = get_image(image_ref)
        self.conn.compute.rebuild_server(self.server, image=self.image.id)


##########
# Flavors
##########

def get_flavor(ref) -> NovaFlavor:
    """Get a flavor by its ID or name.

    Args:
        ref (str): The ID or name of the flavor.

    Returns:
        The flavor matching the ID or name.

    Raises:
        NotFound: If the flavor could not be found.
    """
    try:
        return show_flavor(ref)
    except NotFound:
        return show_flavor(get_flavor_id(ref))


def get_flavor_id(name) -> str:
    """Look up a flavor's ID from its name.

    Args:
        name (str): The name of the flavor.

    Returns:
        The ID of the found flavor.

    Raises:
        NotFound: If the flavor could not be found.
    """
    flavor = next((f for f in nova().flavors.list() if f.name == name), None)
    if not flavor:
        raise NotFound(f'No flavors found matching name {name}')
    return flavor


def show_flavor(flavor_id) -> NovaFlavor:
    """Get a flavor by its ID.

    Args:
        flavor_id (str): the ID of the flavor

    Returns:
        The flavor with the given ID.
    """
    return nova().flavors.get(flavor_id)


def show_flavor_by_name(name) -> NovaFlavor:
    """Get a flavor by its name.

    Args:
        name (str): The name of the flavor.

    Returns:
        The flavor with the given name.

    Raises:
        NotFound: If the flavor could not be found.
    """
    flavor_id = get_flavor_id(name)
    return show_flavor(flavor_id)


def list_flavors() -> 'list[NovaFlavor]':
    """Get a list of all available flavors.

    Returns:
        A list of all flavors.
    """
    return nova().flavors.list()


##########
# Servers
##########

def get_server(ref) -> NovaServer:
    """Get a server by its ID.

    Args:
        ref (str): The ID or name of the server.

    Returns:
        The server matching the ID.

    Raises:
        NotFound: If the server could not be found.
    """
    try:
        return show_server(ref)
    except NotFound:
        return show_server(get_server_id(ref))


def get_server_id(name) -> str:
    """Look up a server's ID from its name.

    Args:
        name (str): The name of the server.

    Returns:
        The ID of the found server.

    Raises:
        NotFound: If the server could not be found.
    """
    servers = [s for s in nova().servers.list() if s.name == name]
    if not servers:
        raise ValueError(f'No matching servers found for name "{name}"')
    elif len(servers) > 1:
        raise ValueError(f'Multiple matching servers found for name "{name}"')
    return servers[0].id


def list_servers(**kwargs) -> "list[NovaServer]":
    """List all servers under the current project.

    Args:
        kwargs: Keyword arguments, which will be passed to
            :func:`novaclient.v2.servers.list`. For example, to filter by
            instance name, provide ``search_opts={'name': 'my-instance'}``

    Returns:
        All servers associated with the current project.
    """
    return nova().servers.list(**kwargs)


def delete_server(server_id):
    """Delete a server by its ID.

    Args:
        server_id (str): The ID of the server to delete.
    """
    return nova().servers.delete(server_id)


def show_server(server_id) -> NovaServer:
    """Get a server by its ID.

    Args:
        server_id (str): the ID of the server

    Returns:
        The server with the given ID.
    """
    return nova().servers.get(server_id)


def show_server_by_name(name) -> NovaServer:
    """Get a server by its name.

    Args:
        name (str): The name of the server.

    Returns:
        The server with the given name.

    Raises:
        NotFound: If the server could not be found.
    """
    server_id = get_server_id(name)
    return show_server(server_id)


def associate_floating_ip(server_id, floating_ip_address=None):
    """Associate an allocated Floating IP with a server.

    If no Floating IP is specified, one will be allocated dynamically.

    Args:
        server_id (str): The ID of the server.
        floating_ip_address (str): The IPv4 address of the Floating IP to
            assign. If specified, this Floating IP must already be allocated
            to the project.

    """
    if not floating_ip_address:
        floating_ip_address = get_free_floating_ip()["floating_ip_address"]

    connection().compute.add_floating_ip_to_server(server_id, floating_ip_address)

    return floating_ip_address


def detach_floating_ip(server_id, floating_ip_address):
    """Remove an allocated Floating IP from a server by name.

    Args:
        server_id (str): The name of the server.
        floating_ip_address (str): The IPv4 address of the Floating IP to
            remove from the server.

    """
    connection().compute.remove_floating_ip_from_server(
        server_id, floating_ip_address)


def wait_for_active(server_id, timeout=(60 * 20)):
    """Wait for the server to go in to the ACTIVE state.

    If the server goes in to an ERROR state, this function will terminate. This
    is a blocking function.

    .. note::

       For bare metal servers, when the server transitions to ACTIVE state, this
       actually indicates it has started its final boot. It may still take some
       time for the boot to complete and interfaces e.g., SSH to come up.

       If you want to wait for a TCP service like SSH, refer to
       :func:`wait_for_tcp`.

    Args:
        server_id (str): The ID of the server.
        timeout (int): The number of seconds to wait for before giving up.
            Defaults to 20 minutes.

    """
    compute = connection().compute
    server = compute.get_server(server_id)
    return compute.wait_for_server(server, wait=timeout)


def wait_for_tcp(host, port, timeout=(60 * 20), sleep_time=5):
    """Wait until a port on a server starts accepting TCP connections.

    The implementation is taken from `wait_for_tcp_port.py
    <https://gist.github.com/butla/2d9a4c0f35ea47b7452156c96a4e7b12>`_.

    Args:
        host (str): The host that should be accepting connections. This can
            be either a Floating IP or a hostname.
        port (int): Port number.
        timeout (int): How long to wait before raising errors, in seconds.
            Defaults to 20 minutes.
        sleep_time (int): How long to wait between each attempt in seconds.
            Defaults to 5 seconds.

    Raises:
        TimeoutError: If the port isn't accepting connection after time
            specified in `timeout`.
    """
    start_time = time.perf_counter()

    while True:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                break
        except OSError as ex:
            time.sleep(sleep_time)
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError((
                    f'Waited too long for the port {port} on host {host} to '
                    'start accepting connections.')) from ex

############
# Key pairs
############


def update_keypair(key_name=None, public_key=None) -> "NovaKeypair":
    """Update a key pair's public key.

    Due to how OpenStack Nova works, this requires deleting and re-creating the
    key even for public key updates. The key will not be re-created if it
    already exists and the fingerprints match.

    Args:
        key_name (str): The name of the key pair to update. Defaults to value
            of the "key_name" context variable.
        public_key (str): The public key to update the key pair to reference.
            Defaults to the contents of the file specified by the
            "keypair_public_key" context variable.

    Returns:
        The updated (or created) key pair.
    """
    if not key_name:
        key_name = get_from_context("keypair_name")
    if not public_key:
        public_key_path = get_from_context("keypair_public_key")
        if public_key_path:
            with open(public_key_path, "r") as pubkey:
                public_key = pubkey.read().strip()

    assert key_name is not None
    assert public_key is not None

    _nova = nova()
    try:
        existing = _nova.keypairs.get(key_name)
        if existing.fingerprint == sshkey_fingerprint(public_key):
            return existing
        _nova.keypairs.delete(key_name)
        return _nova.keypairs.create(
            key_name, public_key=public_key, key_type="ssh")
    except NotFound:
        return _nova.keypairs.create(
            key_name, public_key=public_key, key_type="ssh")


##########
# Wizards
##########

def create_server(server_name, reservation_id=None, key_name=None, network_id=None,
                  network_name=DEFAULT_NETWORK, nics=[], image_id=None,
                  image_name=DEFAULT_IMAGE, flavor_id=None,
                  flavor_name=None, count=1, hypervisor_hostname=None) -> 'Union[NovaServer,list[NovaServer]]':
    """Launch a new server instance.

    Args:
        server_name (str): A name to give the server.
        reservation_id (str): The ID of the Blazar reservation that will be
            used to select a target host node. It is required to make a
            reservation for bare metal server instances.
        key_name (str): A key pair name to associate with the server. Any user
            holding the private key for the key pair will be able to SSH to
            the instance as the ``cc`` user. Defaults to the key specified
            by the "key_name" context variable.
        network_id (str): The network ID to connect the server to. The server
            will obtain an IP address on this network when it boots.
        network_name (str): The name of the network to connect the server to.
            If ``network_id`` is also set, that takes priority.
        nics (list[dict]): ...
        image_id (str): The image ID to use for the server's disk image.
        image_name (str): The name of the image to user for the server's disk
            image. If ``image_id`` is also set, that takes priority.
            (Default ``DEFAULT_IMAGE``.)
        flavor_id (str): The flavor ID to use when launching the server. If not
            set, and no ``flavor_name`` is set, the first flavor found is used.
        flavor_name (str): The name of the flavor to use when launching the
            server. If ``flavor_id`` is also set, that takes priority. If not
            set, and no ``flavor_id`` is set, the first flavor found is used.
        count (int): The number of instances to launch. When launching bare
            metal server instances, this number must be less than or equal to
            the total number of hosts reserved. (Default 1).

    Returns:
        The created server instance. If ``count`` was larger than 1, then a
            list of all created instances will be returned instead.

    Raises:
        ValueError: if an invalid count is provided.
    """
    if count < 1:
        raise ValueError('Must launch at least one server.')
    if not key_name:
        key_name = update_keypair().id
    if not network_id:
        network_id = get_network_id(network_name)
    if not nics:
        nics = [{'net-id': network_id, 'v4-fixed-ip': ''}]
    if not image_id:
        image_id = get_image_id(image_name)
    if not flavor_id:
        if flavor_name:
            flavor_id = get_flavor_id(flavor_name)
        else:
            flavor_id = next((f.id for f in list_flavors()), None)
            if not flavor_id:
                raise NotFound('Could not auto-select flavor to use')

    scheduler_hints = {}
    if reservation_id:
        scheduler_hints['reservation'] = reservation_id

    server = nova().servers.create(
        name=server_name,
        image=image_id,
        flavor=flavor_id,
        scheduler_hints=scheduler_hints,
        key_name=key_name,
        nics=nics,
        min_count=count,
        max_count=count,
        hypervisor_hostname=hypervisor_hostname
    )
    if count > 1:
        matching = list_servers(search_opts={'name': f'{server_name}-'})
        # In case there are others matching the name, just get the latest
        # batch of instances.
        return sorted(matching, key=attrgetter('created'), reverse=True)[:count]
    else:
        return server
