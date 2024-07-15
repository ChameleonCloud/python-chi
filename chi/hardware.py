from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple


from .clients import blazar
from .context import get, RESOURCE_API_URL

import requests
import json
import logging

LOG = logging.getLogger(__name__)

@dataclass
class Node:
    site_name: str
    node_name: str
    node_type: str
    architecture: dict
    bios: dict
    gpu: dict
    main_memory: dict
    network_adapters: List[dict]
    placement: dict
    processor: dict
    storage_devices: List[dict]
    uid: str
    version: str

    def next_free_timeslot(self) -> Tuple[datetime, datetime]:
        raise NotImplementedError()


def get_nodes(
        all_sites: bool = False,
        filter_reserved: bool = False,
        gpu: Optional[bool] = None,
        number_cpu: Optional[int] = None,
    ) -> List[Node]:

    site = get("region_name")
    endpoint = f"sites/{site.split('@')[1].lower()}/clusters/chameleon/nodes"
    data = _call_api(endpoint)
    nodes = []

    for node_data in data:
        node = Node(
            site_name=site,
            node_name=node_data.get("name"),
            node_type=node_data.get("type"),
            architecture=node_data.get("architecture"),
            bios=node_data.get("bios"),
            gpu=node_data.get("gpu"),
            main_memory=node_data.get("main_memory"),
            network_adapters=node_data.get("network_adapters"),
            placement=node_data.get("placement"),
            processor=node_data.get("processor"),
            storage_devices=node_data.get("storage_devices"),
            uid=node_data.get("uid"),
            version=node_data.get("version"),
        )
        nodes.append(node)
    return nodes

def _call_api(endpoint):
    url = "{0}/{1}.{2}".format(RESOURCE_API_URL, endpoint, "json")
    LOG.info("Requesting %s from reference API ...", url)
    resp = requests.get(url)
    LOG.info("Response received. Parsing to json ...")
    data = resp.json()
    return data