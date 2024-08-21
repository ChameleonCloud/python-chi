from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .clients import blazar
from .context import get, RESOURCE_API_URL

import requests
import logging

LOG = logging.getLogger(__name__)

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

    def next_free_timeslot(self) -> Tuple[datetime, Optional[datetime]]:
        """
        Finds the next available timeslot for the hardware using the Blazar client.

        Returns:
            A tuple containing the start and end datetime of the next available timeslot.
            If no timeslot is available, returns (end_datetime_of_last_allocation, None).
        """
        def get_host_id(items, target_uid):
            for item in items:
                if item.get('uid') == target_uid:
                    return item['id']
            return None

        blazarclient = blazar()

        # Get allocation for this specific host
        host_id = get_host_id(blazarclient.host.list(), self.uid)

        allocation = blazarclient.host.get_allocation(host_id)

        now = datetime.now(timezone.utc)

        if not allocation:
            return (now, None)

        reservations = sorted(allocation['reservations'], key=lambda x: x['start_date'])

        def parse_datetime(dt_str: str) -> datetime:
            dt = datetime.fromisoformat(dt_str)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        if parse_datetime(reservations[0]['start_date']) > now:
            return (now, parse_datetime(reservations[0]['start_date']))

        for i in range(len(reservations) - 1):
            current_end = parse_datetime(reservations[i]['end_date'])
            next_start = parse_datetime(reservations[i+1]['start_date'])

            if current_end < next_start:
                return (current_end, next_start)

        last_end = parse_datetime(reservations[-1]['end_date'])
        return (last_end, None)


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

    Returns:
        List[Node]: A list of Node objects that match the specified criteria.
    """

    sites = []
    if all_sites:
        sites = [site.get("name") for site in _call_api("sites")['items']]
    else:
        sites.append(get("region_name"))

    nodes = []

    for site in sites:
        # Soufiane: Skipping CHI@EDGE since it is not enrolled in the hardware API,
        if site == "CHI@Edge":
            print("Please visit the Hardware discovery page for information about CHI@Edge devices")
            continue

        endpoint = f"sites/{site.split('@')[1].lower()}/clusters/chameleon/nodes"
        data = _call_api(endpoint)

        for node_data in data['items']:
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
            )

            if isinstance(node.gpu, list):
                gpu_filter = gpu is None or (node.gpu and gpu == bool(node.gpu[0]['gpu']))
            else:
                gpu_filter = gpu is None or (node.gpu and gpu == bool(node.gpu['gpu']))

            cpu_filter = min_number_cpu is None or node.architecture['smt_size'] >= min_number_cpu

            if gpu_filter and cpu_filter:
                nodes.append(node)

    return nodes