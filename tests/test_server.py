from datetime import datetime
from unittest.mock import Mock

import pytest

from chi.server import Server


@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


@pytest.fixture(autouse=True)
def mock_server_deps(mocker):
    def _fake_get_image(name):
        img = Mock()
        img.name = name
        return img

    mocker.patch("chi.server.chi.image.get_image", side_effect=_fake_get_image)
    mocker.patch("chi.server.get_keypair", return_value=Mock(name="test-key"))
    mocker.patch("chi.server.connection")
    mocker.patch("chi.server.session")
    mocker.patch(
        "chi.server.chi_network.get_network", return_value={"name": "sharednet1"}
    )


def _nova_server_mock():
    return Mock(
        spec=[
            "image",
            "flavor",
            "networks",
            "name",
            "key_name",
            "id",
            "status",
            "addresses",
            "created",
            "hostId",
            "host_status",
            "hypervisor_hostname",
            "is_locked",
        ]
    )


def test_from_nova_server_no_image(mocker):
    mocker.patch("chi.server.get_image_name")
    ns = _nova_server_mock()
    ns.image = None
    ns.flavor = {"original_name": "m1.small"}
    ns.networks = {"net1": []}

    server = Server._from_nova_server(ns)

    assert server.image is None
    assert server.image_name is None


def test_from_nova_server_with_image_dict(mocker):
    mock_get_name = mocker.patch(
        "chi.server.get_image_name", return_value="CC-Ubuntu22.04"
    )
    ns = _nova_server_mock()
    ns.image = {"id": "img-123"}
    ns.flavor = {"original_name": "m1.small"}
    ns.networks = {"net1": []}

    server = Server._from_nova_server(ns)

    mock_get_name.assert_called_once_with("img-123")
    assert server.image_name == "CC-Ubuntu22.04"


def test_from_nova_server_with_image_string(mocker):
    mock_get_name = mocker.patch(
        "chi.server.get_image_name", return_value="CC-Ubuntu22.04"
    )
    ns = _nova_server_mock()
    ns.image = "img-123"
    ns.flavor = {"original_name": "m1.small"}
    ns.networks = {"net1": []}

    server = Server._from_nova_server(ns)

    mock_get_name.assert_called_once_with("img-123")
    assert server.image_name == "CC-Ubuntu22.04"


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
    create_server(server_name, reservation_id=reservation_id)


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
