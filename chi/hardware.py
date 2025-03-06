from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from chi import exception

from .clients import blazar
from .context import get, RESOURCE_API_URL

import requests
import logging

LOG = logging.getLogger(__name__)

node_types = []


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
                if item.get("uid") == target_uid or item.get("hypervisor_hostname") == target_uid:
                    return item["id"]
            return None

        blazarclient = blazar()

        # Get allocation for this specific host
        host_id = get_host_id(blazarclient.host.list(), self.uid)

        if not host_id:
            raise exception.ServiceError(f"Host for {self.uid} not found in Blazar")
        allocation = blazarclient.host.get_allocation(host_id)

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
            Defaults to False. (Not Currently implemented)
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
            print(
                "Please visit the Hardware discovery page for information about CHI@Edge devices"
            )
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
            blazar_host = blazar_hosts_by_hypervisor_hostname.get(node_data.get("uid"), {})
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
                gpu_filter = gpu is None or (node.gpu and gpu == bool(node.gpu.get("gpu")))

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
