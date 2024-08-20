from typing import Optional, List
from datetime import timedelta
from IPython.display import display

from .server import Server
from .container import Container
from .lease import Lease
from .context import DEFAULT_NODE_TYPE, DEFAULT_IMAGE_NAME, DEFAULT_SITE

def create_container(
    container_name: str,
    device_type: str,
    container_image: str,
    device_name: Optional[str] = None,
    reserve_fip: bool = True,
    exposed_ports: Optional[List[str]] = None,
    runtime: Optional[str] = None,
    duration: timedelta = timedelta(hours=24),
    show: str = "widget",
) -> Container:
    """Creates a lease for a device and then creates a container on it.

    Args:
        container_name (str): The name of the container.
        device_type (str): The type of device (e.g., compute, storage).
        container_image (str): The image to use for the container.
        device_name (str, optional): The name of the device. Defaults to None.
        reserve_fip (bool, optional): Whether to reserve a floating IP for the container. Defaults to True.
        duration (timedelta, optional): Duration for the lease. Defaults to 6 hours.
        show (str, optional): Determines whether to display information as a widget. Defaults to "widget".
        exposed_ports (List[str], optional): List of ports to expose on the container. Defaults to None.
        runtime (str, optional): can be set to nvidia to enable GPU support on supported devices. Defaults to None.

    Returns:
        Container: The created container object.
    """

    lease = Lease(
        name=f"lease-{container_name}",
        duration=duration
    )

    lease.add_device_reservation(amount=1,
                                 machine_type=device_type,
                                 device_name=device_name)
    lease.submit(idempotent=True)

    if show == "widget":
        lease.show(type="widget")

    container_name = container_name.replace('_', '-')
    container_name = container_name.lower()

    container = Container(
        name=container_name,
        reservation_id=lease.device_reservations[0]['id'],
        image_ref=container_image,
        exposed_ports=exposed_ports,
        runtime=runtime
    )

    container.submit(wait_for_active=True, show=show)

    if reserve_fip:
        container.associate_floating_ip()

    return container

def create_server(
    server_name: str,
    node_type: Optional[str] = None,
    image_name: Optional[str] = None,
    reserve_fip: bool = True,
    duration: timedelta = timedelta(hours=24),
    show: str = "widget"
) -> Server:
    """
    Creates a server with the given parameters.

    Args:
        server_name (str): The name of the server.
        node_type (str, optional): The type of the server node. If not provided, the user will be prompted to choose from available options.
        image_name (str, optional): The name of the server image. If not provided, the user will be prompted to choose from available options.
        reserve_fip (bool, optional): Whether to reserve a floating IP for the server. Defaults to True.
        duration (timedelta, optional): The duration of the server lease. Defaults to 24 hours.
        show (str, optional): The type of output to show. Defaults to "widget".

    Returns:
        Server: The created server object.

    """
    if node_type is None:
        node_type = get_user_input(
            options=["compute_skylake", "storage_nvme"],
            description="Node Type"
        )

    if image_name is None:
        image_name = get_user_input(
            options=["CC-Ubuntu22.04", "CC-Ubuntu22.04-CUDA"],
            description="Image"
        )

    lease = Lease(
        name=f"lease-{server_name}",
        duration=duration
    )

    lease.add_node_reservation(amount=1, node_type=node_type)
    lease.submit(idempotent=True)

    if show == "widget":
        lease.show(type="widget")

    server = Server(
        name=server_name,
        reservation_id=lease.node_reservations[0]['id'],
        image_name=image_name,
        network_name="sharednet1"  # Change this to a DEFAULT var ASAP
    )

    server = server.submit(wait_for_active=True, show=show)

    if reserve_fip:
        server.associate_floating_ip()

    return server

def get_user_input(options: List[str], description: str) -> str:
    print(f"Available {description}s:")
    for option in options:
        print(f"- {option}")

    selected_value = input(f"Please enter the {description} from the list above: ")

    while selected_value not in options:
        print(f"Invalid {description}. Please choose from the list.")
        selected_value = input(f"Please enter the {description} from the list above: ")

    return selected_value