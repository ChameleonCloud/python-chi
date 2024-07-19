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

    def next_free_timeslot(self) -> datetime:
        """
        (Not implemented yet) Finds the next available timeslot for the hardware.

        Returns:
            A tuple containing the start and end datetime of the next available timeslot.
            If no timeslot is available, returns the end datetime of the last lease.

        """
        raise NotImplementedError()

        blazarclient = blazar()

        # Get all leases
        leases = blazarclient.lease.list()

        # Filter leases for this node
        node_leases = [
            lease for lease in leases
            if any(r['resource_id'] == self.uid for r in lease.get('reservations', [])
                   if r['resource_type'] == 'physical:host')
        ]

        # Sort leases by start time
        node_leases.sort(key=lambda x: x['start_date'])

        now = datetime.now(timezone.utc)

        print(node_leases)

        # Check if there's a free slot now
        if not node_leases or node_leases[0]['start_date'] > now:
            return (now, node_leases[0]['start_date'] if node_leases else None)

        # Find the next free slot
        for i in range(len(node_leases) - 1):
            current_end = datetime.strptime(node_leases[i]['end_date'], "%Y-%m-%d %H:%M:%S")
            next_start = datetime.strptime(node_leases[i+1]['start_date'], "%Y-%m-%d %H:%M:%S")

            if current_end < next_start:
                return (current_end, next_start)

        # If no free slot found, return the end of the last lease
        last_end = datetime.strptime(node_leases[-1]['end_date'], "%Y-%m-%d %H:%M:%S")

        return last_end

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