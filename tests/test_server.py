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

    def get_flavor_id(flavor_name):
        assert flavor_name == BAREMETAL_FLAVOR
        return "flavor-id"

    mocker.patch("chi.server.get_network_id", side_effect=get_network_id)
    mocker.patch("chi.server.get_image_id", side_effect=get_image_id)
    mocker.patch("chi.server.get_flavor_id", side_effect=get_flavor_id)
    mocker.patch("chi.lease.get_node_reservation", return_value="reservation-id")

    example_create_server()

    nova.servers.create.assert_called_once_with(
        name="my_server",
        flavor="flavor-id",
        image="image-id",
        key_name=None,
        nics=[{"net-id": "network-id", "v4-fixed-ip": ""}],
        scheduler_hints={"reservation": "reservation-id"},
        max_count=1,
        min_count=1
    )
