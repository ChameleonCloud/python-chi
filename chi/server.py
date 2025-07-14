import socket
import time
from datetime import datetime
from operator import attrgetter
from typing import Dict, List, Optional, Union

from fabric import Connection
from IPython.display import HTML, display
from novaclient.exceptions import NotFound
from novaclient.v2.flavor_access import FlavorAccess as NovaFlavor
from novaclient.v2.keypairs import Keypair as NovaKeypair
from novaclient.v2.servers import Server as NovaServer
from openstack.exceptions import SDKException
from packaging.version import Version
from paramiko.client import WarningPolicy

import chi
from chi import context, exception, util
from chi import network as chi_network

from .clients import connection, nova
from .context import DEFAULT_IMAGE_NAME, _is_ipynb, session
from .context import get as get_from_context
from .exception import CHIValueError, ResourceError, ServiceError
from .image import Image, get_image_id, get_image_name
from .keypair import Keypair
from .util import random_base32, retry_create, sshkey_fingerprint

DEFAULT_IMAGE = DEFAULT_IMAGE_NAME
DEFAULT_NETWORK = "sharednet1"
BAREMETAL_FLAVOR = "baremetal"


def instance_create_args(
    reservation,
    name=None,
    image=DEFAULT_IMAGE,
    flavor=None,
    key=None,
    net_ids=None,
    **kwargs,
):
    if name is None:
        name = "instance-{}".format(random_base32(6))

    server_args = {
        "name": name,
        "flavorRef": get_flavor_id(flavor),
        "imageRef": get_image_id(image),
        "scheduler_hints": {},
        "key_name": key,
        "networks": net_ids,
    }
    if reservation is not None:
        server_args["scheduler_hints"]["reservation"] = reservation

    if net_ids is None:
        # automatically binds "the one" unless there's more than one
        server_args["nics"] = None
    else:
        # Not sure what fields are actually required and what they're called.
        # novaclient (and Nova HTTP API) docs seem vague. the command at
        # https://github.com/ChameleonCloud/horizon/blob/stable/liberty/openstack_dashboard/dashboards/project/instances/workflows/create_instance.py#L943
        # appears to POST a JSON akin to
        # {"server": {..., "networks": [{"uuid": "e8c33574-5423-436c-a45b-5bab78071b8a"}] ...}, "os:scheduler_hints": ...},
        server_args["networks"] = [{"uuid": netid} for netid in net_ids]

    server_args.update(kwargs)
    return server_args


class Server:
    """
    Represents an instance.

    Args:
        name (str): The name of the server.
        reservation_id (Optional[str]): The reservation ID associated with the server. Defaults to None.
        image_name (str): The name of the image to use for the server. Defaults to DEFAULT_IMAGE_NAME.
        image (Optional[str]): The image ID or name to use for the server. Defaults to None.
        flavor_name (str): The name of the flavor to use for the server. Defaults to BAREMETAL_FLAVOR.
        key_name (str): The name of the keypair to use for the server. Defaults to None.
        keypair (Optional[Keypair]): The keypair object to use for the server. Defaults to None.
        network_name (str): The name of the network to use for the server. Defaults to DEFAULT_NETWORK.

    Attributes:
        name (str): The name of the server.
        reservation_id (Optional[str]): The reservation ID associated with the server.
        image_name (str): The name of the image used for the server.
        flavor_name (str): The name of the flavor used for the server.
        keypair (Optional[Keypair]): The keypair object used for the server.
        network_name (str): The name of the network used for the server.
        id (Optional[str]): The ID of the server.
        addresses (Dict[str, List[str]]): The IP addresses associated with the server.
        created_at (Optional[datetime]): The timestamp when the server was created.
        host_id (Optional[str]): The ID of the host where the server is running.
        host_status (Optional[str]): The status of the host where the server is running.
        hypervisor_hostname (Optional[str]): The hostname of the hypervisor where the server is running.
        is_locked (bool): Indicates whether the server is locked.
        status (Optional[str]): The status of the server.
    """

    def __init__(
        self,
        name: str,
        reservation_id: Optional[str] = None,
        image_name: str = DEFAULT_IMAGE_NAME,
        image: Optional[Image] = None,
        flavor_name: str = BAREMETAL_FLAVOR,
        key_name: str = None,
        keypair: Optional[Keypair] = None,
        network_name: str = DEFAULT_NETWORK,
    ):
        self.name = name
        self.reservation_id = reservation_id or None
        # Add this once chi.image is implemented
        self.image = image or chi.image.get_image(image_name)
        self.image_name = self.image.name
        self.flavor_name = flavor_name

        if keypair:
            self.keypair = keypair
        elif key_name:
            self.keypair = get_keypair(key_name)
        else:
            self.keypair = update_keypair()

        self.network_name = network_name

        self.conn = connection(session=session())

        self.id: Optional[str] = None
        self._addresses: Dict[str, List[str]] = {}
        self.created_at: Optional[datetime] = None
        self.host_id: Optional[str] = None
        self.host_status: Optional[str] = None
        self.hypervisor_hostname: Optional[str] = None
        self.is_locked: bool = False
        self._status: Optional[str] = None

    @property
    def addresses(self) -> Dict[str, List[str]]:
        if self.id:
            self.refresh()
        return self._addresses

    @property
    def status(self) -> Optional[str]:
        if self.id:
            self.refresh()
        return self._status

    def submit(
        self,
        wait_for_active: bool = True,
        show: str = "widget",
        idempotent: bool = False,
        retry_on_error: bool = False,
        wait_timeout: int = 20 * 60,
        **kwargs,
    ) -> "Server":
        """
        Submits a server creation request to the Nova API.

        Args:
            wait_for_active (bool, optional): Whether to wait for the server to become active before returning. Defaults to True.
            show (str, optional): The type of server information to display after creation. Defaults to "widget".
            idempotent (bool, optional): Whether to create the server only if it doesn't already exist. Defaults to False.
            retry_on_error (bool, optional): Whether to retry the server creation if creation fails. Defaults to False.
            wait_timeout (int): How long to wait for server to start in seconds. Default 20 minutes.

        Raises:
            Conflict: If the server creation fails due to a conflict and idempotent mode is not enabled.
        """
        nova_client = nova()

        if idempotent:
            server_id = get_server_id(self.name)
            existing_server = nova_client.servers.get(server_id) if server_id else None
            if existing_server:
                server = Server._from_nova_server(existing_server)
                if wait_for_active:
                    self.wait(show=show)
                if show:
                    server.show(type=show)
                return server

        server_args = instance_create_args(
            reservation=self.reservation_id,
            name=self.name,
            image=self.image_name,
            flavor=self.flavor_name,
            key=self.keypair.name,
            net_ids=[chi_network.get_network_id(self.network_name)],
            **kwargs,
        )

        def _server_create_func():
            self.conn.compute.create_server(**server_args)
            if wait_for_active:
                self.wait(timeout=wait_timeout)
            if show:
                self.show(type=show)

        def _server_cleanup_func():
            try:
                self.delete(idempotent=True, delete_ips=False)
                time.sleep(10)
            except Exception:
                # Ignore any cleanup errors
                pass

        retry_create(
            3 if retry_on_error else 1, _server_create_func, _server_cleanup_func
        )

    @classmethod
    def _from_nova_server(cls, nova_server):
        try:
            image_id = nova_server.image["id"]
        except Exception:
            image_id = nova_server.image_id
        flavor_name = nova_server.flavor.get("original_name", "")

        try:
            network_id = (
                list(nova_server.networks.keys())[0]
                if len(nova_server.networks) > 0
                else None
            )
        except Exception:
            network_id = (
                nova_server.networks[0]["uuid"]
                if len(nova_server.networks) > 0
                else None
            )

        server = cls(
            name=nova_server.name,
            reservation_id=None,
            image_name=get_image_name(image_id),
            flavor_name=flavor_name,
            key_name=nova_server.key_name,
            network_name=(
                chi_network.get_network(network_id)["name"]
                if network_id is not None
                else None
            ),
        )

        try:
            created_at = nova_server.created
        except Exception:
            created_at = nova_server.created_at

        try:
            host_id = nova_server.hostId
        except Exception:
            host_id = nova_server.host_id

        try:
            host_status = nova_server.host_status
        except Exception:
            host_status = None

        try:
            hypervisor_hostname = nova_server.hypervisor_hostname
        except Exception:
            hypervisor_hostname = None

        try:
            is_locked = nova_server.is_locked
        except Exception:
            is_locked = None

        server.id = nova_server.id
        server._status = nova_server.status
        server._addresses = nova_server.addresses
        server.created_at = created_at
        server.host_id = host_id
        server.host_status = host_status
        server.hypervisor_hostname = hypervisor_hostname
        server.is_locked = is_locked

        return server

    def delete(self, idempotent: bool = False, delete_ips: bool = True) -> None:
        """
        Deletes the server.

        Args:
            idempotent (bool, optional): Whether to create the server only if it doesn't already exist. Defaults to False.
            delete_ips (bool, optional): Whether to delete the server IPs from this project. Defauls to False
        """
        if delete_ips:
            conn = connection(session=session())
            for addr in self.get_all_floating_ips():
                floating_ip_obj = chi_network.get_floating_ip(addr)
                conn.network.delete(floating_ip_obj["id"])
        try:
            delete_server(self.id)
        except NotFound:
            if not idempotent:
                raise ResourceError(f"Server {self.name} not found")

    def refresh(self):
        """
        Refreshes the server's information by retrieving the latest details from the server provider.

        Raises:
            ResourceError: If the server refresh fails.
        """
        try:
            nova_server = nova().servers.get(get_server_id(self.name))
            conn_server = self.conn.compute.get_server(get_server_id(self.name))

            self.id = nova_server.id
            self._status = nova_server.status
            self._addresses = nova_server.addresses
            self.created_at = nova_server.created
            self.host_id = nova_server.hostId
            self.host_status = conn_server.host_status
            self.hypervisor_hostname = conn_server.hypervisor_hostname
            self.is_locked = conn_server.is_locked
        except Exception as e:
            raise ResourceError(f"Could not refresh server: {e}")

    def wait(
        self, status: str = "ACTIVE", show: str = "widget", timeout: int = 20 * 60
    ) -> None:
        """
        Waits for the server's status to reach the specified status.

        Args:
            status (str): The status to wait for. Defaults to "ACTIVE".
            show (str, optional): The type of server information to display after creation. Defaults to "widget".
            timeout (int): How long to wait for server to start in seconds. Default 20 minutes.

        Raises:
            ServiceError: If the server does not reach the specified status within the timeout period.

        Returns:
            None
        """
        print(
            f"Waiting for server {self.name}'s status to become {status}. This typically takes 10 minutes for baremetal, but can take up to 20 minutes."
        )

        pb = util.TimerProgressBar()
        if show == "widget" and _is_ipynb():
            pb.display()

        def _callback():
            self.refresh()
            if self.status == status.upper() or self.status == "ERROR":
                print(f"Server has moved to status {self.status}")
                return True
            return False

        res = pb.wait(_callback, 10 * 60, timeout)
        if not res:
            raise ServiceError(f"Timeout waiting for server to reach {status} status")

    def show(self, type: str = "text", wait_for_active: bool = False) -> None:
        """
        Display the content of the server.

        Args:
            type (str, optional): The type of content to display. options are ["text","widget"]. Defaults to "text".
            wait_for_active (bool, optional): Whether to wait for the server to be active before displaying the content. Defaults to False.

        Raises:
            CHIValueError: If an invalid show type is provided.

        Returns:
            None
        """
        if wait_for_active:
            self.wait("ACTIVE")

        if type == "text":
            self._show_text(self)
        elif type == "widget" and _is_ipynb():
            self._show_widget(self)
        else:
            raise CHIValueError("Invalid show type. Use 'text' or 'widget'.")

    def _show_text(self, server):
        print(f"Server: {server.name}")
        print(f"  ID: {server.id}")
        print(f"  Status: {server.status}")
        print(f"  Image Name: {server.image_name}")
        print(f"  Flavor Name: {server.flavor_name}")
        print(f"  Network Name: {server.network_name}")
        print(f"  Addresses: {server.addresses}")
        print(f"  Created at: {server.created_at}")
        print(f"  Keypair: {server.keypair.name if server.keypair else 'N/A'}")
        print(f"  Host ID: {server.host_id}")
        print(f"  Reservation ID: {server.reservation_id}")
        print(f"  Host Status: {server.host_status}")
        print(f"  Hypervisor Hostname: {server.hypervisor_hostname}")
        print(f"  Is Locked: {server.is_locked}")

    def _show_widget(self, server):
        html = "<table style='border-collapse: collapse; width: 100%;'>"
        html += "<tr style='background-color: #f2f2f2;'>"
        html += "<th style='border: 1px solid #ddd; padding: 8px;'>Attribute</th>"
        html += f"<th style='border: 1px solid #ddd; padding: 8px;'>{server.name}</th>"
        html += "</tr>"

        attributes = [
            "id",
            "status",
            "image_name",
            "flavor_name",
            "addresses",
            "network_name",
            "created_at",
            "keypair",
            "reservation_id",
            "host_id",
            "host_status",
            "hypervisor_hostname",
            "is_locked",
        ]

        for attr in attributes:
            html += "<tr>"
            html += f"<td style='border: 1px solid #ddd; padding: 8px;'>{attr.replace('_', ' ').title()}</td>"
            value = getattr(server, attr)
            if attr == "addresses":
                value = self._format_addresses(value)
            elif attr == "keypair":
                value = value.name if value else "N/A"
            html += f"<td style='border: 1px solid #ddd; padding: 8px;'>{value}</td>"
            html += "</tr>"

        html += "</table>"
        display(HTML(html))

    def _format_addresses(self, addresses):
        formatted = ""
        for network, address_list in addresses.items():
            formatted += f"<strong>{network}:</strong><br>"
            for address in address_list:
                formatted += (
                    f"&nbsp;&nbsp;IP: {address['addr']} (v{address['version']})<br>"
                    f"&nbsp;&nbsp;Type: {address['OS-EXT-IPS:type']}<br>"
                    f"&nbsp;&nbsp;MAC: {address['OS-EXT-IPS-MAC:mac_addr']}<br>"
                )
        return formatted

    def associate_floating_ip(
        self, fip: Optional[str] = None, port_id: Optional[str] = None
    ) -> None:
        """
        Associates a floating IP with the server.

        Args:
            fip (str, optional): The floating IP to associate with the server. If not provided, a new floating IP will be allocated.
            port_id (str): Optional port ID to assign the floating IP to. If not
                provided, the will use the first routable port on the server.

        Returns:
            None
        """
        fip = associate_floating_ip(self.id, fip, port_id)
        self.refresh()
        return fip

    def detach_floating_ip(self, fip: str, delete: Optional[bool] = True) -> None:
        """
        Detaches a floating IP from the server.

        Args:
            fip (str): The floating IP to detach.
            delete (Optional[bool], optional): Whether to delete the floating IP after disassociation. Defaults to True.

        Returns:
            None
        """
        detach_floating_ip(self.id, fip)
        if delete:
            conn = connection(session=session())
            floating_ip_obj = chi_network.get_floating_ip(fip)
            conn.network.delete(floating_ip_obj["id"])
        self.refresh()

    def _can_connect_to_port(self, host, port, timeout):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def get_floating_ip(self):
        """Get an attached floating ip of this server, if exists

        Returns:
            str: Floating IP address of server
        """
        fips = self.get_all_floating_ips()
        if fips:
            return fips[0]
        return None

    def get_all_floating_ips(self):
        """Get a list of attached floating ips of this server

        Returns:
            List[str[]: Floating IP addresses of server
        """
        fips = []
        for net, addresses in self.addresses.items():
            for address in addresses:
                if address.get("OS-EXT-IPS:type") == "floating":
                    fips.append(address["addr"])
        return fips

    def check_connectivity(
        self,
        wait: bool = True,
        host: str = None,
        port: int = 22,
        timeout: int = 500,
        show: str = "widget",
    ) -> bool:
        """Checks for server TCP connectivity from the local runtime.

        Args:
            wait (bool, optional): Should this method block. Defaults to True.
            host (str, optional): The IP to connect to. Defaults to the value of `get_floating_ip()`, which returns the first floating IP of this server.
            port (int, optional): The TCP port to connect to. Defaults to 22.
            timeout (int, optional): The number of seconds to wait before timeout. Defaults to 500.
            show (str, optional): The type of server information to display after creation. Defaults to "widget".

        Raises:
            ResourceError: If timeout occurs.

        Returns:
            bool: whether connectivity could be established
        """
        if not host:
            host = self.get_floating_ip()
        if show:
            print(f"Checking connectivity to {host} port {port}.")

        def _callback():
            return self._can_connect_to_port(host, port, timeout)

        pb = util.TimerProgressBar()
        if show == "widget" and _is_ipynb():
            pb.display()

        if wait:
            res = pb.wait(_callback, timeout * 0.9, timeout)
            if not res:
                raise ResourceError(
                    (
                        f"Waited too long for the port {port} on host {host} to "
                        "start accepting connections."
                    )
                )
        else:
            res = _callback()
        if show:
            if res:
                print("Connection successful")
            else:
                print("Connection failed")

    def ssh_connection(self, user="cc", **kwargs) -> Connection:
        """
            Args:
                kwargs: Arguments for the Fabric Connection

            Returns:
                `Fabric Connection
        <https://docs.fabfile.org/en/latest/api/connection.html#fabric.connection.Connection>`__ to this server.
        """
        if not kwargs.get("connect_kwargs"):
            kwargs["connect_kwargs"] = {}
        key_filename = get_from_context("keypair_private_key")
        # Set key file only if user did not specify
        if not kwargs["connect_kwargs"].get("key_filename") and not kwargs[
            "connect_kwargs"
        ].get("pkey"):
            kwargs["connect_kwargs"].setdefault("key_filename", key_filename)
        ip = self.get_floating_ip()
        conn = Connection(ip, user=user, **kwargs)
        # Default policy is to reject unknown hosts - for our use-case,
        # printing a warning is probably enough, given the host is almost
        # always guaranteed to be unknown.
        conn.client.set_missing_host_key_policy(WarningPolicy)
        return conn

    def upload(self, file: str, remote_path: str = "", **kwargs) -> None:
        """Upload a local file to this server

        Args:
            file (str): the path of the local file
            remote_path (str, optional): the remote path. Defaults to "".
        """
        # Implementation for uploading files to the server
        with self.ssh_connection(**kwargs) as conn:
            conn.put(file, remote_path)

    def execute(self, command: str, **kwargs):
        """Execute a command on this server

        Args:
            command (str): the shell command to execute.
        """
        with self.ssh_connection(**kwargs) as conn:
            return conn.run(command)

    def get_metadata(self) -> Dict[str, str]:
        """Get the metadata dictionary of this server

        Returns:
            Dict[str, str]: The metadata dictionary of the server.
        """
        return nova().servers.list_meta(self.id)["metadata"]

    def set_metadata_item(self, key, value):
        """Set a metadata item for the server.

        Args:
            key (str): The metadata key
            value (str): The metadata value
        """
        return nova().servers.set_meta_item(self.id, key, value)

    def add_security_group(self, security_group_name: str):
        """Add a security group to the server."""
        return nova().servers.add_security_group(self.id, security_group_name)

    def remove_security_group(self, security_group_name: str):
        """Removes a security group to the server."""
        return nova().servers.remove_security_group(self.id, security_group_name)

    def attach_volume(self, volume_id: str) -> None:
        """Attach a Cinder volume to the server. Only supported at KVM@TACC.

        Args:
            volume_id (str): The volume to attach.
        """
        nova().volumes.create_server_volume(self.id, volume_id)

    def detach_volume(self, volume_id: str) -> None:
        """Detach a Cinder volume from the server. Only supported at KVM@TACC.

        Args:
            volume_id (str): The volume to detach.
        """
        nova().volumes.delete_server_volume(self.id, volume_id)

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.name}'>"


##########
# Flavors
##########


class Flavor:
    """
    Represents a flavor in the system.

    Attributes:
        name (str): The name of the flavor.
        description (str): The description of the flavor.
        disk (int): The disk size in GB.
        ram (int): The RAM size in MB.
        vcpus (int): The number of virtual CPUs.
        extras (dict): Extra traits associated with this flavor.
    """

    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        disk: int,
        ram: int,
        vcpus: int,
        extras: dict,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.disk = disk
        self.ram = ram
        self.vcpus = vcpus
        self.extras = extras

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.name}' {self.description} (disk={self.disk}) (ram={self.ram}) (vcpus={self.vcpus})>"


def list_flavors(reservable=None, reservation_id=None) -> List[Flavor]:
    """Get a list of all available flavors.

    Args:
        reservable (bool): Whether to filter by reservable flavors. Defaults to True.
        reservation_id (str, optional): The reservation ID to filter by. Defaults to None.

    Returns:
        A list of all flavors.
    """
    if Version(context.version) >= Version("1.0"):
        nova_client = nova()
        flavors = nova_client.flavors.list(detailed=True)
        chi_flavors = []
        for f in flavors:
            extras = f.get_keys()
            # include a flavor if:
            # - not filtering by reservable
            # - is reservable in blazar & not an active reservation flavor
            if not reservable or (
                extras.get("aggregate_instance_extra_specs:reservation")
                == reservation_id
                and extras.get("trait:CUSTOM_BLAZAR_FLAVOR_RESERVATION") == "required"
            ):
                chi_flavors.append(
                    Flavor(
                        id=f.id,
                        name=f.name,
                        description=f.description,
                        disk=f.disk,
                        ram=f.ram,
                        vcpus=f.vcpus,
                        extras=extras,
                    )
                )
        return chi_flavors
    return nova().flavors.list()


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
        raise CHIValueError(f"No flavors found matching name {name}")
    return flavor.id


def show_flavor(flavor_id) -> NovaFlavor:
    """
    .. deprecated:: 1.0

    Get a flavor by its ID.

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


##########
# Servers
##########


def list_servers(**kwargs) -> List[Server]:
    """
    Returns a list of all servers in the current project.

    :return: A list of Server objects representing the servers.
    """
    if Version(context.version) >= Version("1.0"):
        nova_servers = nova().servers.list()
        servers = [Server._from_nova_server(server) for server in nova_servers]
        return servers
    return nova().servers.list(**kwargs)


def get_server(name: str) -> Server:
    """
    Retrieves a server object by its name.

    Args:
        name (str): The name of the server to retrieve.

    Returns:
        Server: The server object corresponding to the given name.

    Raises:
        Exception: If the server with the given name does not exist.

    """
    if Version(context.version) >= Version("1.0"):
        nova_server = nova().servers.get(get_server_id(name))
        return Server._from_nova_server(nova_server)
    try:
        return show_server(name)
    except NotFound:
        return show_server(get_server_id(name))


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
        return None
    elif len(servers) > 1:
        raise ResourceError(f'Multiple matching servers found for name "{name}"')
    return servers[0].id


def delete_server(server_id):
    """
    .. deprecated:: 1.0

    Delete a server by its ID.

    Args:
        server_id (str): The ID of the server to delete.
    """
    return nova().servers.delete(server_id)


def show_server(server_id) -> NovaServer:
    """
    .. deprecated:: 1.0

    Get a server by its ID.

    Args:
        server_id (str): the ID of the server

    Returns:
        The server with the given ID.
    """
    return nova().servers.get(server_id)


def show_server_by_name(name) -> NovaServer:
    """
    .. deprecated:: 1.0

    Get a server by its name.

    Args:
        name (str): The name of the server.

    Returns:
        The server with the given name.

    Raises:
        NotFound: If the server could not be found.
    """
    server_id = get_server_id(name)
    return show_server(server_id)


def associate_floating_ip(server_id, floating_ip_address=None, port_id=None):
    """
    .. deprecated:: 1.0

    Associate an allocated Floating IP with a server.

    If no Floating IP is specified, one will be allocated dynamically.

    Args:
        server_id (str): The ID of the server.
        floating_ip_address (str): The IPv4 address of the Floating IP to
            assign. If specified, this Floating IP must already be allocated
            to the project.
        port_id (str): Optional port ID to assign the floating IP to. If not
            provided, the will use the first routable port on the server.

    """
    if not floating_ip_address:
        floating_ip_obj = chi_network.get_free_floating_ip()
    else:
        floating_ip_obj = chi_network.get_floating_ip(floating_ip_address)

    conn = connection(session=session())
    ports = list(conn.network.ports(device_id=server_id))
    if port_id:
        port_obj = next(port for port in ports if port["id"] == port_id)
        if not port_obj:
            raise exception.ResourceError(
                f"Port {port_id} not found on server {server_id}"
            )
        ports = [port_obj]
    else:
        for port in ports:
            floating_ip_args = {"port_id": port["id"]}
            try:
                return conn.network.update_ip(
                    floating_ip_obj["id"], **floating_ip_args
                )["floating_ip_address"]
            except SDKException:
                # Ignore errors and try the next port
                pass
    floating_ip_address = floating_ip_obj["floating_ip_address"]
    raise exception.ResourceError(
        f"None of the ports can route to floating ip {floating_ip_address} on server {server_id}"
    )


def detach_floating_ip(server_id, floating_ip_address):
    """
    .. deprecated:: 1.0

    Remove an allocated Floating IP from a server by name.

    Args:
        server_id (str): The name of the server.
        floating_ip_address (str): The IPv4 address of the Floating IP to
            remove from the server.

    """
    connection().compute.remove_floating_ip_from_server(server_id, floating_ip_address)


def wait_for_active(server_id, timeout=(60 * 20)):
    """
    .. deprecated:: 1.0

    Wait for the server to go in to the ACTIVE state.

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
    """
    .. deprecated:: 1.0

    Wait until a port on a server starts accepting TCP connections.

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
                raise ServiceError(
                    (
                        f"Waited too long for the port {port} on host {host} to "
                        "start accepting connections."
                    )
                ) from ex


############
# Key pairs
############


class Keypair:
    """
    Represents a keypair object.

    Attributes:
        name (str): The name of the keypair.
        public_key (str): The public key associated with the keypair.
    """

    def __init__(self, name: str, public_key: str):
        self.name = name
        self.public_key = public_key

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.name}' ({self.public_key})>"


def get_keypair(name=None) -> Keypair:
    """
    Retrieves a keypair by name.

    Args:
        name (str, optional): The name of the keypair to retrieve. If not provided,
            it will use the JupyterHub keypair for the current user.

    Returns:
        Keypair: An instance of the Keypair class representing the retrieved keypair.
    """
    if name is None:
        name = get_from_context("keypair_name")

    nova_client = nova()
    try:
        keypair = nova_client.keypairs.get(name)
        return Keypair(name=keypair.name, public_key=keypair.public_key)
    except NotFound:
        return Keypair(name=name, public_key=None)


def list_keypair() -> List[Keypair]:
    """
    Retrieve a list of keypairs from the Nova client.

    Returns:
        A list of Keypair objects, containing the name and public key of each keypair.
    """
    nova_client = nova()
    keypairs = nova_client.keypairs.list()
    return [Keypair(name=kp.name, public_key=kp.public_key) for kp in keypairs]


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

    if not key_name or not public_key:
        return None

    _nova = nova()
    try:
        existing = _nova.keypairs.get(key_name)
        if existing.fingerprint == sshkey_fingerprint(public_key):
            return existing
        _nova.keypairs.delete(key_name)
        return _nova.keypairs.create(key_name, public_key=public_key, key_type="ssh")
    except NotFound:
        return _nova.keypairs.create(key_name, public_key=public_key, key_type="ssh")


##########
# Wizards
##########


def create_server(
    server_name,
    reservation_id=None,
    key_name=None,
    network_id=None,
    network_name=DEFAULT_NETWORK,
    nics=[],
    image_id=None,
    image_name=DEFAULT_IMAGE,
    flavor_id=None,
    flavor_name=None,
    count=1,
    hypervisor_hostname=None,
) -> "Union[NovaServer,list[NovaServer]]":
    """
    .. deprecated:: 1.0

    Launch a new server instance.

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
        raise CHIValueError("Must launch at least one server.")
    if not key_name:
        key_name = update_keypair().id
    if not network_id:
        network_id = chi_network.get_network_id(network_name)
    if not nics:
        nics = [{"net-id": network_id, "v4-fixed-ip": ""}]
    if not image_id:
        image_id = get_image_id(image_name)
    if not flavor_id:
        if flavor_name:
            flavor_id = get_flavor_id(flavor_name)
        else:
            flavor_id = next((f.id for f in list_flavors()), None)
            if not flavor_id:
                raise ResourceError("Could not auto-select flavor to use")

    scheduler_hints = {}
    if reservation_id:
        scheduler_hints["reservation"] = reservation_id

    server = nova().servers.create(
        name=server_name,
        image=image_id,
        flavor=flavor_id,
        scheduler_hints=scheduler_hints,
        key_name=key_name,
        nics=nics,
        min_count=count,
        max_count=count,
        hypervisor_hostname=hypervisor_hostname,
    )
    if count > 1:
        matching = list_servers(search_opts={"name": f"{server_name}-"})
        # In case there are others matching the name, just get the latest
        # batch of instances.
        return sorted(matching, key=attrgetter("created"), reverse=True)[:count]
    else:
        return server
