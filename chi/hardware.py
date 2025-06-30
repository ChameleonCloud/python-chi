import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple

import pandas as pd
import requests
from ipydatagrid import DataGrid, Expr, TextRenderer
from IPython.display import display
from ipywidgets import HTML, Box, Layout

from chi import exception

from .clients import blazar, connection
from .context import EDGE_RESOURCE_API_URL, RESOURCE_API_URL, get, session

LOG = logging.getLogger(__name__)

node_types = []


def _get_next_free_timeslot(allocation, minimum_hours):
    now = datetime.now(timezone.utc)

    if not allocation:
        return (now, None)

    reservations = sorted(allocation["reservations"], key=lambda x: x["start_date"])

    buffer = timedelta(hours=minimum_hours)
    # Next time this interval could possibly start
    possible_start = now
    for i in range(len(reservations)):
        # Check we have enough time between last known free period and this reservation
        this_start = _parse_blazar_dt(reservations[i]["start_date"])
        if possible_start + buffer < this_start:
            # We found a gap
            return (possible_start, this_start)

        # Otherwise, no possible start until end of this reservation
        this_end = _parse_blazar_dt(reservations[i]["end_date"])
        possible_start = this_end
    # If there was no gap, use the last reservation's end time
    return (possible_start, None)


@dataclass
class Node:
    """
    Represents the Chameleon hardware that goes into a single node.
    A dataclass for node information directly from the hardware browser.
    """

    site: str
    name: str
    type: str
    architecture: dict
    bios: dict
    cpu: dict
    gpu: dict
    main_memory: dict
    network_adapters: List[dict]
    placement: dict
    storage_devices: List[dict]
    uid: str
    version: str
    reservable: bool

    def next_free_timeslot(
        self, minimum_hours: int = 1
    ) -> Tuple[datetime, Optional[datetime]]:
        """
        Finds the next available timeslot for the hardware using the Blazar client.

        Args:
            minimum_hours (int, optional): The minimum number of hours for this timeslot.

        Returns:
            A tuple containing the start and end datetime of the next available timeslot.
            If no timeslot is available, returns (end_datetime_of_last_allocation, None).
        """

        def get_host_id(items, target_uid):
            for item in items:
                if (
                    item.get("uid") == target_uid
                    or item.get("hypervisor_hostname") == target_uid
                ):
                    return item["id"]
            return None

        blazarclient = blazar()

        # Get allocation for this specific host
        host_id = get_host_id(blazarclient.host.list(), self.uid)
        if not host_id:
            raise exception.ServiceError(f"Host for {self.uid} not found in Blazar")

        return _get_next_free_timeslot(
            blazarclient.host.get_allocation(host_id), minimum_hours
        )

    def _ipython_display_(self):
        """
        Displays information about the node. This function is called passively by the Jupyter display system.
        """

        layout = Layout(padding="4px 10px")
        style = {
            "description_width": "initial",
            "background": "#d3d3d3",
            "white_space": "nowrap",
        }

        reservable_style = {
            "description_width": "initial",
            "background": " #a2d9fe",
            "white_space": "nowrap",
        }

        if not self.reservable:
            reservable_style["background"] = "#f69084"

        children = [
            HTML(f"<b>Node Name:</b> {self.name}", style=style, layout=layout),
            HTML(f"<b>Site:</b> {self.site}", style=style, layout=layout),
            HTML(f"<b>Type:</b> {self.type}", style=style, layout=layout),
        ]
        if getattr(self, "cpu", False) and "clock_speed" in self.cpu:
            children.append(
                HTML(
                    f"<b>Clock Speed:</b> {self.cpu['clock_speed'] / 1e9:.2f} GHz",
                    style=style,
                    layout=layout,
                )
            )

        if (
            getattr(self, "main_memory", False)
            and "humanized_ram_size" in self.main_memory
        ):
            children.append(
                HTML(
                    f"<b>RAM:</b> {self.main_memory['humanized_ram_size']}",
                    style=style,
                    layout=layout,
                )
            )

        if getattr(self, "gpu", False) and "gpu" in self.gpu and self.gpu["gpu"]:
            if "gpu_count" in self.gpu:
                children.append(
                    HTML(
                        f"<b>GPU Count:</b> {self.gpu['gpu_count']}",
                        style=style,
                        layout=layout,
                    )
                )
            else:
                children.append(HTML("<b>GPU:</b> True", style=style, layout=layout))
            if "gpu_model" in self.gpu:
                children.append(
                    HTML(
                        f"<b>GPU Model:</b> {self.gpu['gpu_model']}",
                        style=style,
                        layout=layout,
                    )
                )
        else:
            children.append(HTML("<b>GPU Count:</b> 0", style=style, layout=layout))

        if (
            getattr(self, "storage_devices", False)
            and len(self.storage_devices) > 0
            and "humanized_size" in self.storage_devices[0]
        ):
            children.append(
                HTML(
                    f"<b>Storage Size:</b> {self.storage_devices[0]['humanized_size']}",
                    style=style,
                    layout=layout,
                )
            )

        if getattr(self, "reservable", False):
            children.append(
                HTML(
                    f"<b>Reservable:</b> {'Yes' if self.reservable else 'No'}",
                    style=reservable_style,
                    layout=layout,
                )
            )

        box = Box(children=children)
        box.layout = Layout(flex_flow="row wrap")
        display(box)


def _call_api(endpoint):
    url = "{0}/{1}.{2}".format(RESOURCE_API_URL, endpoint, "json")
    LOG.info("Requesting %s from reference API ...", url)
    resp = requests.get(url)
    LOG.info("Response received. Parsing to json ...")
    data = resp.json()
    return data


def get_nodes(
    all_sites: bool = False,
    filter_reserved: bool = False,
    gpu: Optional[bool] = None,
    min_number_cpu: Optional[int] = None,
    node_type: Optional[str] = None,
) -> List[Node]:
    """
    Retrieve a list of nodes based on the specified criteria.

    Args:
        all_sites (bool, optional): Flag to indicate whether to retrieve nodes from all sites.
            Defaults to False.
        filter_reserved (bool, optional): Flag to indicate whether to filter out reserved nodes.
            Defaults to False.
        gpu (bool, optional): Flag to indicate whether to filter nodes based on GPU availability.
            Defaults to None.
        min_number_cpu (int, optional): Minimum number of CPU logical cores per node.
            Defaults to None.
        node_type (str, optional): The node type to filter by

    Returns:
        List[Node]: A list of Node objects that match the specified criteria.
    """

    sites = []
    if all_sites:
        sites = [site.get("name") for site in _call_api("sites")["items"]]
    else:
        sites.append(get("region_name"))

    nodes = []

    for site in sites:
        # Soufiane: Skipping CHI@EDGE since it is not enrolled in the hardware API,
        if site == "CHI@Edge":
            print("See `hardware.get_devices` for information about CHI@Edge devices")
            continue

        allocations = defaultdict(list)
        reserved_now = set()
        blazarclient = blazar()
        now = datetime.now(timezone.utc)

        endpoint = f"sites/{site.split('@')[1].lower()}/clusters/chameleon/nodes"

        with ThreadPoolExecutor() as executor:
            f1 = executor.submit(_call_api, endpoint)
            f2 = executor.submit(blazarclient.host.list)
            data = f1.result()
            blazar_hosts = f2.result()

        blazar_hosts_by_id = {}
        for host in blazar_hosts:
            blazar_hosts_by_id[host["id"]] = host
        blazar_hosts_by_hypervisor_hostname = {}
        for host in blazar_hosts:
            blazar_hosts_by_hypervisor_hostname[host["hypervisor_hostname"]] = host

        if filter_reserved:
            for resource in blazarclient.host.list_allocations():
                for allocation in resource["reservations"]:
                    blazar_host = blazar_hosts_by_id.get(resource["resource_id"], None)
                    if blazar_host:
                        allocations[blazar_host["hypervisor_hostname"]].append(
                            allocation
                        )
                        if _reserved_now(allocation, now):
                            reserved_now.add(blazar_host["hypervisor_hostname"])

        for node_data in data["items"]:
            blazar_host = blazar_hosts_by_hypervisor_hostname.get(
                node_data.get("uid"), {}
            )
            node = Node(
                site=site,
                name=node_data.get("node_name"),
                type=node_data.get("node_type"),
                architecture=node_data.get("architecture"),
                bios=node_data.get("bios"),
                cpu=node_data.get("processor"),
                gpu=node_data.get("gpu"),
                main_memory=node_data.get("main_memory"),
                network_adapters=node_data.get("network_adapters"),
                placement=node_data.get("placement"),
                storage_devices=node_data.get("storage_devices"),
                uid=node_data.get("uid"),
                version=node_data.get("version"),
                reservable=blazar_host.get("reservable"),
            )
            if node.type not in node_types:
                node_types.append(node.type)

            if isinstance(node.gpu, list):
                gpu_filter = gpu is None or (
                    node.gpu and gpu == bool(node.gpu[0].get("gpu"))
                )
            else:
                gpu_filter = gpu is None or (
                    node.gpu and gpu == bool(node.gpu.get("gpu"))
                )

            cpu_filter = (
                min_number_cpu is None
                or node.architecture.get("smt_size", 0) >= min_number_cpu
            )

            free_and_reservable = node.uid not in reserved_now and node.reservable
            if (
                gpu_filter
                and cpu_filter
                and (not filter_reserved or free_and_reservable)
                and (node_type is None or node.type == node_type)
            ):
                nodes.append(node)

    if node_type is not None and node_type not in node_types:
        if all_sites:
            raise exception.CHIValueError(
                f"Unknown node_type '{node_type}' at all sites."
            )
        else:
            raise exception.CHIValueError(
                f"Unknown node_type '{node_type}' at {get('region_name')}."
            )

    return nodes


def _parse_blazar_dt(datetime_string):
    d = datetime.strptime(datetime_string, "%Y-%m-%dT%H:%M:%S.%f")
    return d.replace(tzinfo=timezone.utc)


def _reserved_now(allocation, now=datetime.now(timezone.utc)):
    start_dt_object = _parse_blazar_dt(allocation["start_date"])
    end_dt_object = _parse_blazar_dt(allocation["end_date"])
    return start_dt_object < now and now < end_dt_object


def get_node_types() -> List[str]:
    """
    Retrieve a list of unique node types.

    Returns:
        List[str]: A list of unique node types.
    """
    if len(node_types) < 1:
        get_nodes()
    return list(set(node_types))


def _reservable_color(cell):
    return "#a2d9fe" if cell.value else "#f69084"


def _gpu_background_color(cell):
    return "#d3d3d3" if not cell.value else None


def show_nodes(nodes: Optional[List[Node]] = None) -> None:
    """
    Display a sortable, filterable table of available nodes.

    Args:
        nodes (Optional[List[Node]], optional): A list of Node objects to display.
            If not provided, defaults to the output of hardware.get_nodes().

    Returns:
        None
    """

    def estimate_column_width(df, column, char_px=7, padding=0):
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in DataFrame.")
        max_chars = df[column].astype(str).map(len).max()
        return max(max_chars * char_px + padding, 80)

    if not nodes:
        nodes = get_nodes()

    rows = []
    for n in nodes:
        rows.append(
            {
                "Node Name": n.name,
                "Type": n.type,
                "Clock Speed (GHz)": round(n.cpu.get("clock_speed", 0) / 1e9, 2),
                "RAM": n.main_memory.get("humanized_ram_size", "N/A"),
                "GPU Model": (n.gpu or {}).get("gpu_model") or "",
                "GPU Count": (n.gpu or {}).get("gpu_count") or "",
                "Storage Size": n.storage_devices[0].get("humanized_size", "N/A")
                if n.storage_devices
                else "N/A",
                "Site": n.site,
                "Reservable": bool(n.reservable),
            }
        )

    df = pd.DataFrame(rows)
    renderers = {
        "Reservable": TextRenderer(
            text_color="black",
            background_color=Expr(_reservable_color),
        ),
        "GPU Model": TextRenderer(
            background_color=Expr(_gpu_background_color),
        ),
        "GPU Count": TextRenderer(
            background_color=Expr(_gpu_background_color),
        ),
    }

    grid = DataGrid(
        df,
        layout=Layout(height="400px"),
        selection_mode="row",
        renderers=renderers,
        column_widths={
            "Node Name": int(estimate_column_width(df, "Node Name")),
            "Site": int(estimate_column_width(df, "Site")),
            "Type": int(estimate_column_width(df, "Type")),
            "RAM": int(estimate_column_width(df, "RAM")),
            "Storage Size": int(estimate_column_width(df, "Storage Size")),
            "Clock Speed (GHz)": 55,
            "GPU Model": 90,
            "GPU Count": 30,
            "key": 30,
            "Reservable": 55,
        },
        df=pd.DataFrame(rows),
    )

    display(grid)


@dataclass
class Device:
    """
    A dataclass for device information directly from the hardware browser.
    """

    device_name: str
    device_type: str
    supported_device_profiles: List[str]
    authorized_projects: Set[str]
    owning_project: str
    uuid: str
    reservable: bool

    def next_free_timeslot(
        self, minimum_hours: int = 1
    ) -> Tuple[datetime, Optional[datetime]]:
        """
        Finds the next available timeslot for the device using the Blazar client.

        Args:
            minimum_hours (int, optional): The minimum number of hours for this timeslot.

        Returns:
            A tuple containing the start and end datetime of the next available timeslot.
            If no timeslot is available, returns (end_datetime_of_last_allocation, None).
        """

        def get_device_id(items, target_uid):
            for item in items:
                if item.get("uid") == target_uid or item.get("uid") == target_uid:
                    return item["id"]
            return None

        blazarclient = blazar()

        # Get allocation for this specific device
        device_id = get_device_id(blazarclient.device.list(), self.uuid)
        if not device_id:
            raise exception.ServiceError(f"Device for {self.uuid} not found in Blazar")

        # Bug in Blazar API for devices means `get_alloction` doesn't work. We get around this with `list`
        allocs = blazarclient.device.list_allocations()
        this_alloc = None
        for alloc in allocs:
            if alloc["resource_id"] == device_id:
                this_alloc = alloc
        return _get_next_free_timeslot(this_alloc, minimum_hours)


def get_devices(
    device_type: Optional[str] = None,
    filter_reserved: bool = False,
    filter_unauthorized: bool = True,
) -> List[Device]:
    """
    Retrieve a list of devices based on the specified criteria.

    Args:
        device_type (str, optional): The device type to filter by
        filter_reserved (bool, optional): Flag to indicate whether to filter out reserved devices. Defaults to False.
        filter_unauthorized (bool, optional): Filter devices that the current project is not authorized to use

    Returns:
        List[Device]: A list of Device objects that match the specified criteria.
    """
    # Query hardware API
    res = requests.get(EDGE_RESOURCE_API_URL)
    try:
        res.raise_for_status()
    except requests.exceptions.HTTPError:
        raise exception.ServiceError(
            f"Failed to get devices. Status code {res.status_code}"
        )

    blazarclient = blazar()
    # Blazar uid matches doni's uuid, so we need to map blazar id to blazar uid for allocations,
    # and uid to id for reservable status
    blazar_devices_by_id = {}
    blazar_devices_by_uid = {}
    for device in blazarclient.device.list():
        blazar_devices_by_id[device["id"]] = device
        blazar_devices_by_uid[device["uid"]] = device

    devices = []
    for dev_json in res.json():
        blazar_host = blazar_devices_by_uid.get(dev_json.get("uuid"), {})
        devices.append(
            Device(
                device_name=dev_json["device_name"],
                device_type=dev_json["device_type"],
                supported_device_profiles=dev_json["supported_device_profiles"],
                authorized_projects=set(dev_json["authorized_projects"]),
                owning_project=dev_json["owning_project"],
                uuid=dev_json["uuid"],
                reservable=blazar_host.get(
                    "reservable", False
                ),  # not all devices will appear in blazar if registration failed
            )
        )

    # Filter based on authorized projects
    authorized_devices = [] if filter_unauthorized else devices
    if filter_unauthorized:
        conn = connection(session=session())
        current_project_id = conn.current_project_id
        for device in devices:
            if (
                "all" in device.authorized_projects
                or current_project_id in device.authorized_projects
            ):
                authorized_devices.append(device)

    # Filter based on device type
    matching_type_devices = [] if device_type else authorized_devices
    if device_type:
        for device in authorized_devices:
            if device.device_type == device_type:
                matching_type_devices.append(device)

    # Filter based on reserved status
    unreserved_devices = [] if filter_reserved else matching_type_devices
    if filter_reserved:
        now = datetime.now(timezone.utc)

        reserved_devices = set()
        for resource in blazarclient.device.list_allocations():
            blazar_device = blazar_devices_by_id.get(resource["resource_id"], None)
            if blazar_device:
                for allocation in resource["reservations"]:
                    if _reserved_now(allocation, now):
                        reserved_devices.add(blazar_device["uid"])
        for device in matching_type_devices:
            # Ensure the device is free and in `reservable` state
            if device.uuid not in reserved_devices and device.reservable:
                unreserved_devices.append(device)

    return unreserved_devices


def get_device_types() -> List[str]:
    """
    Retrieve a list of unique device types.

    Returns:
        List[str]: A list of unique device types.
    """
    return list(set(d.device_type for d in get_devices()))
