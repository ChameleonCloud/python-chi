import json
import logging
import numbers
import os
import re
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Union

import pandas
from blazarclient.exception import BlazarClientException
from ipydatagrid import DataGrid, Expr, TextRenderer
from IPython.display import display
from ipywidgets import HTML, Box, Layout
from packaging.version import Version

from chi import context, server, util

from .clients import blazar, connection
from .context import _is_ipynb, get_project_name
from .exception import CHIValueError, ResourceError, ServiceError
from .hardware import Device, Node
from .network import PUBLIC_NETWORK, get_network_id, list_floating_ips
from .util import retry_create, utcnow

if TYPE_CHECKING:
    from typing import Pattern


LOG = logging.getLogger(__name__)


class ErrorParsers:
    NOT_ENOUGH_RESOURCES: "Pattern" = re.compile(
        r"not enough (?P<resource_type>([\w\s\-\._]+)) available"
    )


BLAZAR_TIME_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_NODE_TYPE = "compute_skylake"
DEFAULT_LEASE_LENGTH = timedelta(days=1)
DEFAULT_NETWORK_RESOURCE_PROPERTIES = ["==", "$physical_network", "physnet1"]


def lease_create_args(
    neutronclient,
    name=None,
    start="now",
    end=None,
    length=None,
    nodes=1,
    node_resource_properties=None,
    fips=0,
    networks=0,
    network_resource_properties=DEFAULT_NETWORK_RESOURCE_PROPERTIES,
):
    """
    .. deprecated:: 1.0

    Generates the nested object that needs to be sent to the Blazar client
    to create the lease. Provides useful defaults for Chameleon.

    :param str name: name of lease. If ``None``, generates a random name.
    :param str/datetime start: when to start lease as a
        :py:class:`datetime.datetime` object, or if the string ``'now'``,
        starts in about a minute.
    :param length: length of time as a :py:class:`datetime.timedelta` object or
        number of seconds as a number. Defaults to 1 day.
    :param datetime.datetime end: when to end the lease. Provide only this or
        `length`, not both.
    :param int nodes: number of nodes to reserve.
    :param resource_properties: object that is JSON-encoded and sent as the
        ``resource_properties`` value to Blazar. Commonly used to specify
        node types.
    """
    if start == "now":
        start = utcnow() + timedelta(seconds=70)

    if length is None and end is None:
        length = DEFAULT_LEASE_LENGTH
    elif length is not None and end is not None:
        raise CHIValueError("provide either 'length' or 'end', not both")

    if end is None:
        if isinstance(length, numbers.Number):
            length = timedelta(seconds=length)
        end = start + length

    reservations = []

    if nodes > 0:
        if node_resource_properties:
            node_resource_properties = json.dumps(node_resource_properties)

        reservations += [
            {
                "resource_type": "physical:host",
                "resource_properties": node_resource_properties or "",
                "hypervisor_properties": "",
                "min": str(nodes),
                "max": str(nodes),
            }
        ]

    if fips > 0:
        reservations += [
            {
                "resource_type": "virtual:floatingip",
                "network_id": get_network_id(PUBLIC_NETWORK),
                "amount": fips,
            }
        ]

    if networks > 0:
        if network_resource_properties:
            network_resource_properties = json.dumps(network_resource_properties)

        reservations += [
            {
                "resource_type": "network",
                "resource_properties": network_resource_properties or "",
                "network_name": f"{name}-net{idx}",
            }
            for idx in range(networks)
        ]

    return {
        "name": name,
        "start": start.strftime(BLAZAR_TIME_FORMAT),
        "end": end.strftime(BLAZAR_TIME_FORMAT),
        "reservations": reservations,
        "events": [],
    }


def lease_create_nodetype(*args, **kwargs):
    """
    .. deprecated:: 1.0

    Wrapper for :py:func:`lease_create_args` that adds the
    ``resource_properties`` payload to specify node type.

    :param str node_type: Node type to filter by, ``compute_skylake``, et al.
    :raises ValueError: if there is no `node_type` named argument.
    """
    try:
        node_type = kwargs.pop("node_type")
    except KeyError:
        raise CHIValueError("no node_type specified")
    kwargs["node_resource_properties"] = ["==", "$node_type", node_type]
    return lease_create_args(*args, **kwargs)


class Lease:
    """
    Represents a lease in the CHI system.

    Args:
        name (str): The name of the lease.
        start_date (datetime, optional): The start date of the lease. Defaults to None.
        end_date (datetime, optional): The end date of the lease. Defaults to None.
        duration (timedelta, optional): The duration of the lease. Defaults to None.
        lease_json (dict, optional): JSON representation of the lease. Defaults to None.

    Attributes:
        name (str): The name of the lease.
        start_date (str): The start date of the lease in the format specified by BLAZAR_TIME_FORMAT.
        end_date (str): The end date of the lease in the format specified by BLAZAR_TIME_FORMAT.
        id (str): The ID of the lease.
        status (str): The status of the lease.
        user_id (str): The ID of the user associated with the lease.
        project_id (str): The ID of the project associated with the lease.
        created_at (datetime): The creation date of the lease.
        device_reservations (list): List of device reservations associated with the lease.
        node_reservations (list): List of node reservations associated with the lease.
        fip_reservations (list): List of floating IP reservations associated with the lease.
        network_reservations (list): List of network reservations associated with the lease.
        flavor_reservations (list): List of flavor reservations associated with the lease.
        events (list): List of events associated with the lease.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        duration: Optional[timedelta] = None,
        lease_json: Optional[dict] = None,
    ):
        self.id = None
        self.status = None
        self.user_id = None
        self.project_id = None
        self.created_at = None

        self.device_reservations = []
        self.node_reservations = []
        self.fip_reservations = []
        self.flavor_reservations = []
        self.network_reservations = []
        self._events = []

        if lease_json:
            self._populate_from_json(lease_json)
        else:
            if name is None:
                raise CHIValueError(
                    "Name must be specified when lease_json is not provided"
                )

            self.name = name
            if start_date:
                self.start_date = start_date.strftime(BLAZAR_TIME_FORMAT)
            else:
                self.start_date = "now"

            if end_date and duration:
                raise CHIValueError("Specify either end_date or duration, not both")
            elif end_date:
                self.end_date = end_date.strftime(BLAZAR_TIME_FORMAT)
            elif duration:
                self.end_date = (utcnow() + duration).strftime(BLAZAR_TIME_FORMAT)
            else:
                raise CHIValueError("Either end_date or duration must be specified")

    def _populate_from_json(self, lease_json):
        self.name = lease_json.get("name")
        self.id = lease_json.get("id")
        self.status = lease_json.get("status")
        self.user_id = lease_json.get("user_id")
        self.project_id = lease_json.get("project_id")

        self.created_at = datetime.fromisoformat(lease_json.get("created_at"))
        self.start_date = datetime.strptime(
            lease_json.get("start_date"), "%Y-%m-%dT%H:%M:%S.%f"
        )
        self.end_date = datetime.strptime(
            lease_json.get("end_date"), "%Y-%m-%dT%H:%M:%S.%f"
        )
        self.created_at = datetime.strptime(
            lease_json.get("created_at"), "%Y-%m-%d %H:%M:%S"
        )

        self.device_reservations.clear()
        self.node_reservations.clear()
        self.fip_reservations.clear()
        self.flavor_reservations.clear()
        self.network_reservations.clear()

        for reservation in lease_json.get("reservations", []):
            resource_type = reservation.get("resource_type")
            if resource_type == "device":
                self.device_reservations.append(reservation)
            if resource_type == "physical:host":
                self.node_reservations.append(reservation)
            elif resource_type == "virtual:floatingip":
                self.fip_reservations.append(reservation)
            elif resource_type == "flavor:instance":
                self.flavor_reservations.append(reservation)
            elif resource_type == "network":
                self.network_reservations.append(reservation)

        # self.events = lease_json.get('events', [])

    def _ipython_display_(self):
        """
        Displays a styled summary of the lease when run in a Jupyter notebook.

        This method is called automatically by the Jupyter display system when
        an instance of the Lease object is the final expression in a cell.
        It presents key lease attributes using ipywidgets for readability.
        """
        layout = Layout(padding="4px 10px")
        style = {
            "description_width": "initial",
            "background": "#d3d3d3",
            "white_space": "nowrap",
        }

        status_style = style.copy()
        status_colors = {
            "ACTIVE": "#a2d9fe",
            "PENDING": "#ffe599",
            "TERMINATED": "#f69084",
        }
        if self.status:
            status_style["background"] = status_colors.get(self.status, "#d3d3d3")

        children = [
            # HTML(f"<b>Lease ID:</b> {self.id}", style=style, layout=layout),
            HTML(f"<b>Status:</b> {self.status}", style=status_style, layout=layout),
            HTML(f"<b>Name:</b> {self.name}", style=style, layout=layout),
        ]

        if self.start_date:
            children.append(
                HTML(
                    f"<b>Start:</b> {self.start_date.strftime('%Y-%m-%d %H:%M')}",
                    style=style,
                    layout=layout,
                )
            )
        if self.end_date:
            children.append(
                HTML(
                    f"<b>End:</b> {self.end_date.strftime('%Y-%m-%d %H:%M')}",
                    style=style,
                    layout=layout,
                )
            )

        remaining = None
        if self.end_date and datetime.now() < self.end_date:
            remaining = self.end_date - datetime.now()

        if remaining:
            days = remaining.days
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            children.append(
                HTML(
                    f"<b>Remaining:</b> {days:02d}d {hours:02d}h {minutes:02d}m",
                    style=style,
                    layout=layout,
                )
            )

        # Reservations
        children.append(
            HTML(
                f"<b>Node Reservations:</b> {len(self.node_reservations)}",
                style=style,
                layout=layout,
            )
        )
        children.append(
            HTML(
                f"<b>FIP Reservations:</b> {len(self.fip_reservations)}",
                style=style,
                layout=layout,
            )
        )
        children.append(
            HTML(
                f"<b>Device Reservations:</b> {len(self.device_reservations)}",
                style=style,
                layout=layout,
            )
        )

        if self.project_id:
            try:
                project_name = context.get_project_name(self.project_id)
                children.append(
                    HTML(
                        f"<b>Project Name:</b> {project_name}",
                        style=style,
                        layout=layout,
                    )
                )
            except ResourceError:
                children.append(
                    HTML(
                        f"<b>Project ID:</b> {self.project_id}",
                        style=style,
                        layout=layout,
                    )
                )
        if self.user_id:
            user_id = connection().get_user_id()
            if self.user_id == user_id:
                label = os.getenv("OS_USERNAME")
                children.append(
                    HTML(f"<b>User Name:</b> {label}", style=style, layout=layout)
                )
            else:
                label = self.user_id  # [:8]  # or just show a truncated ID
                children.append(
                    HTML(f"<b>User ID:</b> {label}", style=style, layout=layout)
                )
        if self.created_at:
            children.append(
                HTML(
                    f"<b>Created At:</b> {self.created_at.strftime('%Y-%m-%d %H:%M')}",
                    style=style,
                    layout=layout,
                )
            )

        box = Box(children=children)
        box.layout = Layout(flex_flow="row wrap")
        display(box)

    def add_device_reservation(
        self,
        amount: int = None,
        machine_type: str = None,
        device_model: str = None,
        device_name: str = None,
        devices: List[Device] = None,
    ):
        """
        Add a IoT device reservation to the list of device reservations.

        Args:
            amount (int, optional): The number of devices to reserve. Defaults to None.
            machine_type (str, optional): The type of machine to reserve. Defaults to None.
            device_model (str, optional): The model of the device to reserve. Defaults to None.
            device_name (str, optional): The name of the device to reserve. Defaults to None.
            devices (List[Device]): A list of Device objects to reserve.

        Raises:
            CHIValueError: If devices are specified, no other arguments should be included.
        """
        if devices:
            if any([amount, machine_type, device_model, device_name]):
                raise CHIValueError(
                    "When specifying nodes, no other arguments should be included"
                )
            for device in devices:
                add_device_reservation(
                    reservation_list=self.device_reservations,
                    device_name=device.device_name,
                )
        else:
            add_device_reservation(
                reservation_list=self.device_reservations,
                count=amount,
                machine_name=machine_type,
                device_model=device_model,
                device_name=device_name,
            )

    def add_node_reservation(
        self,
        amount: int = None,
        node_type: str = None,
        node_name: str = None,
        nodes: List[Node] = None,
    ):
        """
        Add a node reservation to the lease.

        Parameters:
        - amount (int): The number of nodes to reserve.
        - node_type (str): The type of nodes to reserve.
        - node_name (str): The name of the node to reserve.
        - nodes (List[Node]): A list of Node objects to reserve.

        Raises:
        - CHIValueError: If nodes are specified, no other arguments should be included.

        """
        if nodes:
            if any([amount, node_type, node_name]):
                raise CHIValueError(
                    "When specifying nodes, no other arguments should be included"
                )
            for node in nodes:
                add_node_reservation(
                    reservation_list=self.node_reservations, node_name=node.name
                )
        else:
            if not amount or not (node_type or node_name):
                raise CHIValueError(
                    "You must specify amount and either node_type or node_name"
                )
            add_node_reservation(
                reservation_list=self.node_reservations,
                count=amount,
                node_type=node_type,
                node_name=node_name,
            )

    def add_fip_reservation(self, amount: int):
        """
        Add a reservation for a floating IP address to the list of FIP reservations.

        Args:
            amount (int): The number of reservations to add.

        Returns:
            None
        """
        add_fip_reservation(reservation_list=self.fip_reservations, count=amount)

    def add_flavor_reservation(self, id, amount=1):
        """
        Add a reservation for a KVM flavor to the list of reservations.

        Args:
            id (str): The ID of the flavor to reserve
            count (int): The number of floating IPs to reserve.
        """
        self.flavor_reservations.append(
            {
                "resource_type": "flavor:instance",
                "flavor_id": id,
                "amount": amount,
                "affinity": None,
            }
        )

    def add_network_reservation(
        self, network_name: str, usage_type: str = None, stitch_provider: str = None
    ):
        """
        Add a network reservation to the list of network reservations.

        Args:
            network_name (str): The name of the network to be reserved.
            usage_type (str, optional): The type of usage for the network reservation. Defaults to None.
            stitch_provider (str, optional): The stitch provider for the network reservation. Defaults to None.
        """
        add_network_reservation(
            reservation_list=self.network_reservations,
            network_name=network_name,
            usage_type=usage_type,
            stitch_provider=stitch_provider,
        )

    def submit(
        self,
        wait_for_active: bool = True,
        wait_timeout: int = 300,
        show: Optional[str] = None,
        idempotent: bool = False,
        retry_on_error: bool = False,
    ):
        """
        Submits the lease for creation.

        Args:
            wait_for_active (bool, optional): Whether to wait for the lease to become active. Defaults to True.
            wait_timeout (int, optional): The maximum time to wait for the lease to become active, in seconds. Defaults to 300.
            show (Optional[str], optional): The types of lease information to display. Defaults to None, options are "widget", "text".
            idempotent (bool, optional): Whether to create the lease only if it doesn't already exist. Defaults to False.
            retry_on_error (bool, optional): Whether to retry the server creation if creation fails. Defaults to False.

        Raises:
            ResourceError: If unable to create the lease.

        Returns:
            None
        """
        if idempotent:
            existing_lease = _get_lease_from_blazar(self.name)
            if existing_lease and existing_lease["status"] != "TERMINATED":
                print("Found existing lease")
                self._populate_from_json(existing_lease)
                if wait_for_active:
                    self.wait(status="active", timeout=wait_timeout)
                if show:
                    self.show(type=show, wait_for_active=wait_for_active)
                return

        reservations = (
            self.device_reservations
            + self.node_reservations
            + self.fip_reservations
            + self.flavor_reservations
            + self.network_reservations
        )

        def _lease_create_func():
            response = create_lease(
                lease_name=self.name,
                reservations=reservations,
                start_date=self.start_date,
                end_date=self.end_date,
            )
            if response:
                self._populate_from_json(response)
            else:
                raise ResourceError("Unable to make lease")

            if wait_for_active:
                self.wait(status="active", timeout=wait_timeout)

            if show:
                self.show(type=show, wait_for_active=wait_for_active)

        def _lease_cleanup_func():
            try:
                self.delete()
            except Exception:
                # Ignore any cleanup errors
                pass

        retry_create(
            3 if retry_on_error else 1, _lease_create_func, _lease_cleanup_func
        )

    def wait(self, status="active", show: str = "widget", timeout: int = 500):
        """
        Waits for the lease's status to reach the specified status.

        Args:
            status (str): The status to wait for. Defaults to "ACTIVE".
            show (str, optional): The type of server information to display after creation. Defaults to "widget".
            timeout (int): How long to wait for lease to start

        Raises:
            ServiceError: If the server does not reach the specified status within the timeout period.

        Returns:
            None
        """

        print("Waiting for lease to start...")

        pb = util.TimerProgressBar()
        if show == "widget" and _is_ipynb():
            pb.display()

        def _callback():
            self.refresh()
            if self.status == status.upper() or self.status == "ERROR":
                print(f"Lease {self.name} has reached status {self.status.lower()}")
                return True
            return False

        res = pb.wait(_callback, 60, timeout)
        if not res:
            raise ServiceError(
                f"Lease did not reach '{status}' status within 120 seconds, check its start time."
            )

    def refresh(self):
        if self.id:
            lease_data = blazar().lease.get(self.id)
            self._populate_from_json(lease_data)
        else:
            raise ResourceError(
                "Lease object does not yet have a valid id, please submit the object for creation first"
            )

    def delete(self):
        if self.id:
            blazar().lease.delete(self.id)
            self.id = None
            self.status = "DELETED"
        else:
            raise ResourceError(
                "Lease object does not yet have a valid id, please submit the object for creation first"
            )

    def show(self, type=["text", "widget"], wait_for_active=False):
        if wait_for_active:
            self.wait(status="active")

        if "widget" in type and _is_ipynb():
            self._show_widget()
        if "text" in type:
            self._show_text()

    def _show_widget(self):
        html_content = f"""
        <h2>Lease Details</h2>
        <table>
            <tr><th>Name</th><td>{self.name}</td></tr>
            <tr><th>ID</th><td>{self.id or "N/A"}</td></tr>
            <tr><th>Status</th><td>{self.status or "N/A"}</td></tr>
            <tr><th>Start Date</th><td>{self.start_date or "N/A"}</td></tr>
            <tr><th>End Date</th><td>{self.end_date or "N/A"}</td></tr>
            <tr><th>User ID</th><td>{self.user_id or "N/A"}</td></tr>
            <tr><th>Project ID</th><td>{self.project_id or "N/A"}</td></tr>
        </table>


        <h3>Device Reservations</h3>
        <ul>
        {"".join(f"<li>ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Resource type: {r.get('resource_type', 'N/A')}, Min: {r.get('min', 'N/A')}, Max: {r.get('max', 'N/A')}</li>" for r in self.device_reservations)}
        </ul>

        <h3>Node Reservations</h3>
        <ul>
        {"".join(f"<li>ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Resource type: {r.get('resource_type', 'N/A')}, Min: {r.get('min', 'N/A')}, Max: {r.get('max', 'N/A')}</li>" for r in self.node_reservations)}
        </ul>

        <h3>Floating IP Reservations</h3>
        <ul>
        {"".join(f"<li>ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Resource type: {r.get('resource_type', 'N/A')}, Amount: {r.get('amount', 'N/A')}</li>" for r in self.fip_reservations)}
        </ul>

        <h3>Network Reservations</h3>
        <ul>
        {"".join(f"<li>ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Resource type: {r.get('resource_type', 'N/A')}, Network Name: {r.get('network_name', 'N/A')}</li>" for r in self.network_reservations)}
        </ul>

        <h3>Flavor Reservations</h3>
        <ul>
        {"".join(f"<li>ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Resource type: {r.get('resource_type', 'N/A')}, Flavor: {r.get('flavor_id', 'N/A')}, Amount: {r.get('amount', 'N/A')}</li>" for r in self.flavor_reservations)}
        </ul>

        <h3>Events</h3>
        <ul>
        {"".join(f"<li>Type: {e.get('event_type', 'N/A')}, Time: {e.get('time', 'N/A')}, Status: {e.get('status', 'N/A')}</li>" for e in self.events)}
        </ul>
        """

        widget = HTML(html_content)
        display(widget)

    def _show_text(self):
        print("Lease Details:")
        print(f"Name: {self.name}")
        print(f"ID: {self.id or 'N/A'}")
        print(f"Status: {self.status or 'N/A'}")
        print(f"Start Date: {self.start_date or 'N/A'}")
        print(f"End Date: {self.end_date or 'N/A'}")
        print(f"User ID: {self.user_id or 'N/A'}")
        print(f"Project ID: {self.project_id or 'N/A'}")

        print("\nNode Reservations:")
        for r in self.node_reservations:
            print(
                f"ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Min: {r.get('min', 'N/A')}, Max: {r.get('max', 'N/A')}"
            )

        print("\nFloating IP Reservations:")
        for r in self.fip_reservations:
            print(
                f"ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Amount: {r.get('amount', 'N/A')}"
            )

        print("\nNetwork Reservations:")
        for r in self.network_reservations:
            print(
                f"ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Network Name: {r.get('network_name', 'N/A')}"
            )

        print("\nFlavor Reservations:")
        for r in self.flavor_reservations:
            print(
                f"ID: {r.get('id', 'N/A')}, Status: {r.get('status', 'N/A')}, Flavor: {r.get('flavor_id', 'N/A')}, Amount: {r.get('amount', 'N/A')}"
            )

        print("\nEvents:")
        for e in self.events:
            print(
                f"Type: {e.get('event_type', 'N/A')}, Time: {e.get('time', 'N/A')}, Status: {e.get('status', 'N/A')}"
            )

    @property
    def events(self):
        if self.id:
            # TODO Fetch latest events from Blazar API
            pass
        return self._events

    @property
    def status(self):
        if self.id:
            self.refresh()
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    def get_reserved_floating_ips(self):
        """Get reserved floating ips from this lease

        Returns:
            List[str] of fip addresses
        """
        fips = list_floating_ips()
        return [
            fip["floating_ip_address"]
            for fip in fips
            if any(
                f"reservation:{r['id']}" in fip["tags"] for r in self.fip_reservations
            )
        ]

    def get_reserved_flavors(self):
        """Get flavors from flavor reservations in this lease. There will be one
        flavor per flavor reservation.

        Returns:
            List[chi.server.Flavor] of flavor
        """
        flavors = []
        for res in self.flavor_reservations:
            flavors.extend(
                server.list_flavors(reservable=True, reservation_id=res.get("id"))
            )
        return flavors


def _format_resource_properties(user_constraints, extra_constraints):
    if user_constraints:
        if user_constraints[0] == "and":
            # Already a compound constraint
            resource_properties = user_constraints + extra_constraints
        else:
            resource_properties = ["and", user_constraints] + extra_constraints
    else:
        if len(extra_constraints) < 2:
            # Possibly a compount constraint if multiple kwarg helpers used
            resource_properties = extra_constraints[0] if extra_constraints else []
        else:
            resource_properties = ["and"] + extra_constraints

    return resource_properties


def add_node_reservation(
    reservation_list,
    count=1,
    resource_properties=None,
    node_type=None,
    node_name=None,
    architecture=None,
):
    """
    .. deprecated:: 1.0

    Add a node reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        count (int): The number of nodes of the given type to request.
            (Default 1).
        resource_properties (list): A list of resource property constraints. These take
            the form [<operation>, <search_key>, <search_value>], e.g.::

              ["==", "$node_type", "some-node-type"]: filter the reservation to only
                nodes with a `node_type` matching "some-node-type".
              [">", "$architecture.smt_size", 40]: filter to nodes having more than 40
                (hyperthread) cores.
        node_name (str): The specific node name to request. If None, the reservation will
        target any node of the node_type.
        node_type (str): The node type to request. If None, the reservation will not
            target any particular node type. If `resource_properties` is defined, the
            node type constraint is added to the existing property constraints.
        architecture (str): The node architecture to request. If `resource_properties`
            is defined, the architecture constraint is added to the existing property
            constraints.
    """
    user_constraints = (resource_properties or []).copy()
    extra_constraints = []
    if node_type:
        extra_constraints.append(["==", "$node_type", node_type])
    if architecture:
        extra_constraints.append(["==", "$architecture.platform_type", architecture])
    if node_name:
        if (
            count != 1
            or node_type is not None
            or resource_properties is not None
            or architecture is not None
        ):
            raise CHIValueError(
                "If node name is specified, no other resource constraint can be specified"
            )
        extra_constraints.append(["==", "$node_name", node_name])

    resource_properties = _format_resource_properties(
        user_constraints, extra_constraints
    )

    reservation_list.append(
        {
            "resource_type": "physical:host",
            "resource_properties": json.dumps(resource_properties),
            "hypervisor_properties": "",
            "min": count,
            "max": count,
        }
    )


def get_node_reservation(
    lease_ref, count=None, resource_properties=None, node_type=None, architecture=None
):
    """
    .. deprecated:: 1.0

    Retrieve a reservation ID for a node reservation.

    The reservation ID is useful to have when launching bare metal instances.

    Args:
        lease_ref (str): The ID or name of the lease.
        count (int): An optional count of nodes the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        resource_properties (list): An optional set of resource property constraints
            the desired reservation was made under. Use this if you have multiple
            reservations under a lease.
        node_type (str): An optional node type the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        architecture (str): An optional node architecture the desired reservation was
            made for. Use this if you have multiple reservations under a lease.

    Returns:
        The ID of the reservation, if found.

    Raises:
        ValueError: If no reservation was found, or multiple were found.
    """

    def _find_node_reservation(res):
        if res.get("resource_type") != "physical:host":
            return False
        if count is not None and not all(
            int(res.get(key, -1)) == count for key in ["min", "max"]
        ):
            return False
        rp = res.get("resource_properties")
        if node_type is not None and node_type not in rp:
            return False
        if architecture is not None and architecture not in rp:
            return False
        if resource_properties is not None and json.dumps(rp) != resource_properties:
            return False
        return True

    res = _reservation_matching(lease_ref, _find_node_reservation)
    return res["id"]


def get_device_reservation(
    lease_ref, count=None, machine_name=None, device_model=None, device_name=None
):
    """
    .. deprecated:: 1.0

    Retrieve a reservation ID for a device reservation.

    The reservation ID is useful to have when requesting containers.

    Args:
        lease_ref (str): The ID or name of the lease.
        count (int): An optional count of devices the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        machine_name (str): An optional device machine name the desired reservation
            was made for. Use this if you have multiple reservations under a lease.
        device_model (str): An optional device model the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        device_name (str): An optional device name the desired reservation was
            made for. Use this if you have multiple reservations under a lease.

    Returns:
        The ID of the reservation, if found.

    Raises:
        ValueError: If no reservation was found, or multiple were found.
    """

    def _find_device_reservation(res):
        if res.get("resource_type") != "device":
            return False
        # FIXME(jason): Blazar's device plugin uses "min" and "max", but the
        # standard seems to be "min_count" and "max_count"; this should be fixed in
        # Blazar's device plugin.
        if count is not None and not all(
            (key not in res) or int(res.get(key)) == count
            for key in ["min_count", "max_count", "min", "max"]
        ):
            return False
        resource_properties = res.get("resource_properties")
        if machine_name is not None and machine_name not in resource_properties:
            return False
        if device_model is not None and device_model not in resource_properties:
            return False
        if device_name is not None and device_name not in resource_properties:
            return False
        return True

    res = _reservation_matching(lease_ref, _find_device_reservation)
    return res["id"]


def get_reserved_floating_ips(lease_ref) -> "list[str]":
    """
    .. deprecated:: 1.0

    Get a list of Floating IP addresses reserved in a lease.

    Args:
        lease_ref (str): The ID or name of the lease.

    Returns:
        A list of all reserved Floating IP addresses, if any were reserved.
    """

    def _find_fip_reservation(res):
        return res.get("resource_type") == "virtual:floatingip"

    res = _reservation_matching(lease_ref, _find_fip_reservation, multiple=True)
    fips = list_floating_ips()
    return [
        fip["floating_ip_address"]
        for fip in fips
        if any(f"reservation:{r['id']}" in fip["tags"] for r in res)
    ]


def _reservation_matching(lease_ref, match_fn, multiple=False):
    lease = get_lease(lease_ref)
    reservations = lease.get("reservations", [])
    if isinstance(reservations, str):
        LOG.info("Blazar returned nested JSON structure, unpacking.")
        try:
            reservations = json.loads(reservations)
        except Exception as e:
            LOG.error(f"Error loading json data: {e}")

    matches = [r for r in reservations if match_fn(r)]

    if not matches:
        raise ResourceError("No matching reservation found")

    if multiple:
        return matches
    else:
        if len(matches) > 1:
            raise ResourceError("Multiple matching reservations found")
        return matches[0]


def add_network_reservation(
    reservation_list,
    network_name,
    usage_type=None,
    of_controller_ip=None,
    of_controller_port=None,
    vswitch_name=None,
    stitch_provider=None,
    resource_properties=None,
    physical_network="physnet1",
):
    """
    .. deprecated:: 1.0

    Add a network reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        network_name (str): The name of the network to create when the
            reservation starts.
        of_controller_ip (str): The OpenFlow controller IP, if the network
            should be controlled by an external controller.
        of_controller_port (int): The OpenFlow controller port.
        vswitch_name (str): The name of the virtual switch associated with
            this network. See `the virtual forwarding context documentation
            <https://chameleoncloud.readthedocs.io/en/latest/technical/networks/networks_sdn.html#corsa-dp2000-virtual-forwarding-contexts-network-layout-and-advanced-features>`_
            for more details.
        stich_provider (str): specify a stitching provider such as fabric. '
        resource_properties (list): A list of resource property constraints. These take
            the form [<operation>, <search_key>, <search_value>]
        physical_network (str): The physical provider network to reserve from.
            This only needs to be changed if you are reserving a `stitchable
            network <https://chameleoncloud.readthedocs.io/en/latest/technical/networks/networks_stitching.html>`_.
            (Default "physnet1").
    """
    desc_parts = []
    if of_controller_ip and of_controller_port:
        desc_parts.append(f"OFController={of_controller_ip}:{of_controller_port}")
    if vswitch_name:
        desc_parts.append(f"VSwitchName={vswitch_name}")

    user_constraints = (resource_properties or []).copy()
    extra_constraints = []

    if physical_network:
        extra_constraints.append(["==", "$physical_network", physical_network])
    if stitch_provider == "fabric":
        extra_constraints.append(["==", "$stitch_provider", stitch_provider])
    elif stitch_provider is not None:
        raise CHIValueError("stitch_provider must be 'fabric' or None")
    if usage_type == "storage":
        extra_constraints.append(["==", "$usage_type", usage_type])
    elif usage_type is not None:
        raise CHIValueError("usage_type must be 'storage' or None")

    resource_properties = _format_resource_properties(
        user_constraints, extra_constraints
    )

    reservation_list.append(
        {
            "resource_type": "network",
            "network_name": network_name,
            "network_description": ",".join(desc_parts),
            "resource_properties": json.dumps(resource_properties),
            "network_properties": "",
        }
    )


def add_fip_reservation(reservation_list, count=1):
    """
    .. deprecated:: 1.0

    Add a floating IP reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        count (int): The number of floating IPs to reserve.
    """
    reservation_list.append(
        {
            "resource_type": "virtual:floatingip",
            "network_id": get_network_id(PUBLIC_NETWORK),
            "amount": count,
        }
    )


def add_device_reservation(
    reservation_list, count=1, machine_name=None, device_model=None, device_name=None
):
    """
    .. deprecated:: 1.0

    Add an IoT/edge device reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
        count (int): The number of devices to request.
        machine_name (str): The device machine name to reserve. This should match
            a "machine_name" property of the devices registered in Blazar. This
            is the easiest way to reserve a particular device type, e.g.
            "raspberrypi4-64".
        device_model (str): The model of device to reserve. This should match
            a "model" property of the devices registered in Blazar.
        device_name (str): The name of a specific device to reserve. If this
            is provided in conjunction with ``count`` or other constraints,
            an error will be raised, as there is only 1 possible device that
            can match this criteria, because devices have unique names.

    Raises:
        ValueError: If ``device_name`` is provided, but ``count`` is greater
            than 1, or some other constraint is present.
    """
    reservation = {
        "resource_type": "device",
        "min": count,
        "max": count,
    }
    resource_properties = []
    if device_name:
        if count > 1:
            raise ResourceError(
                "Cannot reserve multiple devices if device_name is a constraint."
            )
        resource_properties.append(["==", "$name", device_name])
    if machine_name:
        resource_properties.append(["==", "$machine_name", machine_name])
    if device_model:
        resource_properties.append(["==", "$model", device_model])

    if len(resource_properties) == 1:
        resource_properties = resource_properties[0]
    elif resource_properties:
        resource_properties.insert(0, "and")

    reservation["resource_properties"] = json.dumps(resource_properties)
    reservation_list.append(reservation)


def lease_duration(days=1, hours=0, td=None):
    """
    Compute the start and end dates for a lease given its desired duration.

    When providing both ``days`` and ``hours``, the duration is summed. So,
    the following would be a lease for one and a half days:

    .. code-block:: python

       start_date, end_date = lease_duration(days=1, hours=12)

    Args:
        days (int): The number of days the lease should be for.
        hours (int): The number of hours the lease should be for.
    """
    now = utcnow()
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (now + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date = (now + timedelta(days=days, hours=hours)).strftime(BLAZAR_TIME_FORMAT)
    return start_date, end_date


#########
# Leases
#########


def list_leases() -> List[Lease]:
    """
    Return a list of user leases.

    Returns:
        A list of Lease objects representing user leases.
    """
    blazar_client = blazar()
    lease_dicts = blazar_client.lease.list()

    leases = []
    for lease_dict in lease_dicts:
        lease = Lease(lease_json=lease_dict)
        leases.append(lease)

    return leases


def _status_color(cell):
    return (
        "#a2d9fe"
        if cell.value == "2-ACTIVE"
        else (
            "#ffe599"
            if cell.value == "1-PENDING"
            else ("#f69084" if cell.value == "3-TERMINATED" else "#e0e0e0")
        )
    )


def show_leases() -> DataGrid:
    """
    Displays a table of the user's leases in an interactive, sortable format.

    Uses an ipydatagrid to present key lease attributes such as ID, name, status,
    duration, and reservation counts. The grid supports sorting, filtering, and
    scrolling for easy exploration of lease state.

    Returns:
        DataGrid: An ipydatagrid widget displaying the leases.
    """

    def estimate_column_width(df, column, char_px=7, padding=0):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in DataFrame.")
        max_chars = df[column].astype(str).map(len).max()
        return max(max_chars * char_px + padding, 80)

    leases = list_leases()

    rows = []
    for lease in leases:
        try:
            project_name = get_project_name(lease.project_id)
        except ResourceError:
            project_name = lease.project_id[:8] if lease.project_id else "Unknown"

        if lease.user_id == connection().current_user_id:
            user_label = os.getenv("OS_USERNAME")
        else:
            user_label = lease.user_id if lease.user_id else "Unknown"

        if lease.start_date and lease.end_date:
            duration_hrs = round(
                (lease.end_date - lease.start_date).total_seconds() / 3600, 1
            )
        else:
            duration_hrs = "N/A"

        # Inside your row-building loop:
        if lease.end_date and lease.end_date > datetime.now():
            remaining_td = lease.end_date - datetime.now()
            remaining_str = (
                f"{remaining_td.days:02d}d {(remaining_td.seconds // 3600):02d}h"
            )
        elif lease.end_date and lease.end_date <= datetime.now():
            remaining_str = "Expired"
        else:
            remaining_str = "N/A"

        # prepending status with numeric makes it possible to character sort
        # since ipydatagrid does not allow custom sort functions
        status_order = {
            "PENDING": "1-PENDING",
            "ACTIVE": "2-ACTIVE",
            "TERMINATED": "3-TERMINATED",
        }

        rows.append(
            {
                "Name": lease.name,
                "Status": status_order.get(lease.status, f"4-{lease.status}"),
                "User": user_label,
                "Project": project_name,
                "Start": lease.start_date.strftime("%Y-%m-%d %H:%M")
                if lease.start_date
                else "",
                "End": lease.end_date.strftime("%Y-%m-%d %H:%M")
                if lease.end_date
                else "",
                "Remaining": remaining_str,
                "Total Hours": duration_hrs,
                "# Nodes": len(lease.node_reservations),
                "# FIPs": len(lease.fip_reservations),
                "Created": lease.created_at.strftime("%Y-%m-%d %H:%M")
                if lease.created_at
                else "",
                "Lease ID": lease.id,
                "_is_user_lease": 0
                if lease.user_id == connection().current_user_id
                else 1,
            }
        )

    df = pandas.DataFrame(rows)
    df = pandas.DataFrame(rows)
    df = df.sort_values(by=["_is_user_lease", "Status", "Created"])
    df = df.drop(columns=["_is_user_lease"])

    renderers = {
        "Status": TextRenderer(
            background_color=Expr(_status_color),
            text_color="black",
        ),
    }

    display(
        DataGrid(
            df,
            layout={"height": "400px", "width": "100%"},
            column_widths={
                "key": 30,
                "Name": int(estimate_column_width(df, "Name")),
                "Status": 120,
                "Remaining": 80,
                "Total Hours": 50,
                "# Nodes": 30,
                "# FIPs": 30,
                "Project": 100,
                "User": 75,
                "Start": 95,
                "End": 95,
                "Created": 95,
                "Lease ID": 30,
            },
            renderers=renderers,
        )
    )


def _get_lease_from_blazar(ref: str):
    blazar_client = blazar()

    try:
        lease_dict = blazar_client.lease.get(ref)
        return lease_dict
    except BlazarClientException as err:
        # Blazar's exception class is a bit odd and stores the actual code
        # in 'kwargs'. The 'code' attribute on the exception is just the default
        # code. Prefer to use .kwargs['code'] if present, fall back to .code
        code = getattr(err, "kwargs", {}).get("code", getattr(err, "code", None))
        if code == 404:
            try:
                lease_id = get_lease_id(ref)
                lease_dict = blazar_client.lease.get(lease_id)
                return lease_dict
            except Exception:
                # If we still can't find the lease, return None
                return None
        else:
            raise


def get_lease(ref: str) -> Union[Lease, None]:
    """
    Get a lease by its ID or name.

    Args:
        ref (str): The ID or name of the lease.

    Returns:
        A Lease object matching the ID or name, or None if not found.
    """
    if Version(context.version) >= Version("1.0"):
        blazar_lease = _get_lease_from_blazar(ref)
        if blazar_lease is None:
            raise CHIValueError(f"Lease not found maching {ref}")
        return Lease(lease_json=blazar_lease)
    try:
        return blazar().lease.get(ref)
    except BlazarClientException as err:
        # Blazar's exception class is a bit odd and stores the actual code
        # in 'kwargs'. The 'code' attribute on the exception is just the default
        # code. Prefer to use .kwargs['code'] if present, fall back to .code
        code = getattr(err, "kwargs", {}).get("code", getattr(err, "code", None))
        if code == 404:
            return blazar().lease.get(get_lease_id(ref))


def get_lease_id(lease_name) -> str:
    """Look up a lease's ID from its name.

    Args:
        name (str): The name of the lease.

    Returns:
        The ID of the found lease.

    Raises:
        ValueError: If the lease could not be found, or if multiple leases were
            found with the same name.
    """
    matching = [lease for lease in blazar().lease.list() if lease["name"] == lease_name]
    if not matching:
        raise CHIValueError(f"No leases found for name {lease_name}")
    elif len(matching) > 1:
        raise ResourceError(f"Multiple leases found for name {lease_name}")
    return matching[0]["id"]


def create_lease(lease_name, reservations=[], start_date=None, end_date=None):
    """
    .. deprecated:: 1.0

    Create a new lease with some requested reservations.

    Args:
        lease_name (str): The name to give the new lease.
        reservations (list[dict]): The reservations to request with the lease.
        start_date (datetime): The start date of the lease. (Defaults to now.)
        end_date (datetime): The end date of the lease. (Defaults to 1 day from
            the lease start date.)

    Returns:
        The created lease representation.
    """
    if not (start_date or end_date):
        start_date, end_date = lease_duration(days=1)
    elif not end_date:
        end_date = start_date + timedelta(days=1)
    elif not start_date:
        start_date = utcnow()

    if not reservations:
        raise CHIValueError("No reservations provided.")

    try:
        return blazar().lease.create(
            name=lease_name,
            start=start_date,
            end=end_date,
            reservations=reservations,
            events=[],
        )
    except BlazarClientException as ex:
        msg: "str" = ex.args[0]
        msg = msg.lower()

        match = ErrorParsers.NOT_ENOUGH_RESOURCES.match(msg)
        if match:
            LOG.error(
                f"There were not enough unreserved {match.group('resource_type')} "
                "to satisfy your request."
            )
        else:
            LOG.error(msg)


def delete_lease(ref):
    """
    .. deprecated:: 1.0

    Delete the lease.

    Args:
        ref (str): The name or ID of the lease.
    """
    lease = get_lease(ref)
    lease.delete()
    print(f"Deleted lease {ref}")


def wait_for_active(ref):
    """
    .. deprecated:: 1.0

    Wait for the lease to become active.

    This function will wait for 2.5 minutes, which is a somewhat arbitrary
    amount of time.

    Args:
        ref (str): The name or ID of the lease.

    Returns:
        The lease in ACTIVE state.

    Raises:
        TimeoutError: If the lease fails to become active within the timeout.
    """
    for _ in range(15):
        lease = get_lease(ref)
        status = lease["status"]
        if status == "ACTIVE":
            return lease
        elif status == "ERROR":
            raise ServiceError("Lease went into ERROR state")
        time.sleep(10)
    raise ServiceError("Lease failed to start")
