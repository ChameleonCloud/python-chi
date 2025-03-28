from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple

from chi import exception

from .clients import blazar, connection
from .context import get, RESOURCE_API_URL, EDGE_RESOURCE_API_URL, session


import requests
import logging

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
