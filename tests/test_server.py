from datetime import datetime

import pytest


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
