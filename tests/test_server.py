from contextlib import nullcontext
from collections import namedtuple
from datetime import datetime

import pytest

from chi.server import BAREMETAL_FLAVOR, DEFAULT_IMAGE, DEFAULT_NETWORK

@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


def example_create_server():
    """Launch a bare metal instance.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [create_server](../modules/server.html#chi.server.create_server)
    * [get_node_reservation](../modules/lease.html#chi.lease.get_node_reservation)

    </div>

    """
    from chi.lease import get_node_reservation
    from chi.server import create_server

    # We assume a lease has already been created, for example with
    # ``chi.lease.create_lease```
    lease_name = "my_lease"
    server_name = "my_server"
    reservation_id = get_node_reservation(lease_name)
    server = create_server(server_name, reservation_id=reservation_id)


def test_example_create_server(mocker):
    nova = mocker.patch("chi.server.nova")()

    def get_network_id(network_name):
        assert network_name == DEFAULT_NETWORK
        return "network-id"

    def get_image_id(image_name):
        assert image_name == DEFAULT_IMAGE
        return "image-id"

    def list_flavors():
        return [namedtuple("Flavor", ["id"])("flavor-id")]

    def update_keypair(key_name=None, public_key=None):
        return namedtuple("Keypair", ["id"])("fake-key")

    mocker.patch("chi.server.get_network_id", side_effect=get_network_id)
    mocker.patch("chi.server.get_image_id", side_effect=get_image_id)
    mocker.patch("chi.server.list_flavors", side_effect=list_flavors)
    mocker.patch("chi.lease.get_node_reservation", return_value="reservation-id")
    mocker.patch("chi.server.update_keypair", side_effect=update_keypair)

    example_create_server()

    nova.servers.create.assert_called_once_with(
        name="my_server",
        flavor="flavor-id",
        image="image-id",
        key_name="fake-key",
        nics=[{"net-id": "network-id", "v4-fixed-ip": ""}],
        scheduler_hints={"reservation": "reservation-id"},
        max_count=1,
        min_count=1
    )


def example_wait_for_connectivity():
    """Wait for a server's port to come up before proceeding.

    Sometimes you want to interact with the server over a remote interface
    and need to wait until it's up and accepting connections. The
    :func:`~chi.server.wait_for_tcp` function allows you to do just that.
    This example also illustrates how you can bind a Floating IP (public IP)
    to the server so it can be reached over the internet.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [associate_floating_ip](../modules/server.html#chi.server.associate_floating_ip)
    * [wait_for_tcp](../modules/server.html#chi.server.wait_for_tcp)

    </div>
    """
    from chi.server import associate_floating_ip, wait_for_tcp

    # Note: this is a placeholder server ID. Yours will be different!
    # server_id can be obtained like `server.id` if you created the server
    # with `create_server`. It can also be obtained via `get_server_id(name)`
    server_id = "6b2bae1e-0311-493f-836c-a9da0cb9e0c0"
    ip = associate_floating_ip(server_id)

    # Wait for SSH connectivity over port 22
    wait_for_tcp(ip, port=22)


def test_example_wait_for_connectivity(mocker):
    connection = mocker.patch("chi.server.connection")()

    def get_free_floating_ip():
        return {"floating_ip_address": "fake-floating-ip"}

    mocker.patch("chi.server.get_free_floating_ip", side_effect=get_free_floating_ip)
    socket_create = mocker.patch("chi.server.socket.create_connection")
    socket_create.return_value = nullcontext()

    example_wait_for_connectivity()

    connection.compute.add_floating_ip_to_server.assert_called_once_with(
        "6b2bae1e-0311-493f-836c-a9da0cb9e0c0", "fake-floating-ip")
    socket_create.assert_called_once_with(
        ("fake-floating-ip", 22), timeout=(60*20))
