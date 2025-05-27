from datetime import timedelta
from typing import List, Optional

import matplotlib.pyplot as plt
import networkx as nx

from .container import Container
from .context import (
    DEFAULT_NETWORK,
    get,
)
from .exception import ResourceError
from .hardware import get_node_types
from .image import list_images
from .lease import Lease, delete_lease
from .server import Server


def visualize_resources(leases: List[Lease]):
    """
    Displays a visualization of the resources associated with the leases in a graph.

    Parameters:
    leases (List[Lease]): A list of Lease objects.

    Returns:
    None
    """

    G = nx.Graph()

    # Colors for different resource types
    colors = {
        "node": "#ADD8E6",  # Light Blue
        "network": "#90EE90",  # Light Green
        "fip": "#FFB6C1",  # Light Pink
        "device": "#FAFAD2",  # Light Goldenrod
        "idle": "#D3D3D3",  # Light Gray
    }

    node_positions = {}
    node_colors = []
    node_labels = {}

    # Counter for positioning
    node_count = 0
    network_count = 0
    fip_count = 0
    device_count = 0

    for lease in leases:
        for node_res in lease.node_reservations:
            node_name = f"Node_{node_count}"
            G.add_node(node_name)
            node_positions[node_name] = (node_count, 0)
            node_colors.append(colors["node"])
            node_labels[node_name] = (
                f"Node\n{node_res.get('min', 'N/A')}-{node_res.get('max', 'N/A')}"
            )
            node_count += 1

        for net_res in lease.network_reservations:
            net_name = f"Net_{network_count}"
            G.add_node(net_name)
            node_positions[net_name] = (network_count, 1)
            node_colors.append(colors["network"])
            node_labels[net_name] = f"Network\n{net_res.get('network_name', 'N/A')}"
            network_count += 1

        for fip_res in lease.fip_reservations:
            fip_name = f"FIP_{fip_count}"
            G.add_node(fip_name)
            node_positions[fip_name] = (fip_count, 2)
            node_colors.append(colors["fip"])
            node_labels[fip_name] = f"FIP\n{fip_res.get('amount', 'N/A')}"
            fip_count += 1

        for device_res in lease.device_reservations:
            device_name = f"Device_{device_count}"
            G.add_node(device_name)
            node_positions[device_name] = (device_count, 3)
            node_colors.append(colors["device"])
            node_labels[device_name] = (
                f"Device\n{device_res.get('min', 'N/A')}-{device_res.get('max', 'N/A')}"
            )
            device_count += 1

    idle_resources = max(node_count, network_count, fip_count, device_count)
    for i in range(idle_resources):
        idle_name = f"Idle_{i}"
        G.add_node(idle_name)
        node_positions[idle_name] = (i, 4)
        node_colors.append(colors["idle"])
        node_labels[idle_name] = "Idle"

    plt.figure(figsize=(12, 8))
    nx.draw(G, pos=node_positions, node_color=node_colors, node_size=3000, alpha=0.8)
    nx.draw_networkx_labels(G, pos=node_positions, labels=node_labels, font_size=8)

    legend_elements = [
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            label=f"{key.capitalize()}",
            markerfacecolor=value,
            markersize=10,
        )
        for key, value in colors.items()
    ]
    plt.legend(handles=legend_elements, loc="upper right")

    plt.title("Resource Visualization")
    plt.axis("off")
    plt.tight_layout()
    plt.show()


def cleanup_resources(lease_name: str):
    """
    Cleans up resources associated with the given lease name.

    Args:
        lease_name (str): The name of the lease to be cleaned up.
    """
    delete_lease(lease_name)


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
    if get("region_name") != "CHI@Edge":
        raise ResourceError(
            "Launching containers is only supported on CHI@Edge, please launch servers or change site"
        )

    lease = Lease(name=f"lease-{container_name}", duration=duration)

    lease.add_device_reservation(
        amount=1, machine_type=device_type, device_name=device_name
    )
    lease.submit(idempotent=True)

    if show == "widget":
        lease.show(type="widget")

    container_name = container_name.replace("_", "-")
    container_name = container_name.lower()

    container = Container(
        name=container_name,
        reservation_id=lease.device_reservations[0]["id"],
        image_ref=container_image,
        exposed_ports=exposed_ports,
        runtime=runtime,
    )

    container = container.submit(wait_for_active=True, show=show, idempotent=True)

    if reserve_fip:
        container.associate_floating_ip()

    return container


def create_server(
    server_name: str,
    network_name: Optional[str] = DEFAULT_NETWORK,
    node_type: Optional[str] = None,
    image_name: Optional[str] = None,
    reserve_fip: bool = True,
    duration: timedelta = timedelta(hours=24),
    show: str = "widget",
) -> Server:
    """
    Creates a server with the given parameters. Will automatically create a reservation.

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
    if get("region_name") == "CHI@Edge":
        raise ResourceError(
            "Launching servers is not supported on CHI@Edge, please launch containers or change site"
        )

    if node_type is None:
        node_type = _get_user_input(options=get_node_types(), description="Node Type")

    if image_name is None:
        image_name = _get_user_input(
            options=[image.name for image in list_images()], description="Image"
        )

    lease = Lease(name=f"lease-{server_name}", duration=duration)

    lease.add_node_reservation(amount=1, node_type=node_type)
    lease.submit(idempotent=True)

    if show == "widget":
        lease.show(type="widget")

    server = Server(
        name=server_name,
        reservation_id=lease.node_reservations[0]["id"],
        image_name=image_name,
        network_name=network_name,  # Change this to a DEFAULT var ASAP
    )

    server = server.submit(wait_for_active=True, show=show, idempotent=True)

    if reserve_fip:
        server.associate_floating_ip()

    return server


def _get_user_input(options: List[str], description: str) -> str:
    print(f"Available {description}s:")
    for option in options:
        print(f"- {option}")

    selected_value = input(f"Please enter the {description} from the list above: ")

    while selected_value not in options:
        print(f"Invalid {description}. Please choose from the list.")
        selected_value = input(f"Please enter the {description} from the list above: ")

    return selected_value
