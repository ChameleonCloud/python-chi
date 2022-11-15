from os import environ

import ipywidgets as widgets
import jwt
import keystoneauth1.exceptions.http
import pandas as pd
import requests
from IPython.core.display import display

import chi
from .context import get


SITES_URL = "https://api.chameleoncloud.org/sites/"
NODES_SUFFIX = "/clusters/chameleon/nodes"


class IllegalArgumentError(ValueError):
    pass


def get_site():
    """Get the user's selected site by context parameter.

    Returns:
        The name of the site, if selected.
    """
    return get("region_name")


def get_node():
    """ Get the user's selected node by context parameter.

    Returns:
        The name of the node, if selected.
    """
    return get("node_type")


def get_discovery(site_name: str = None):
    """Get the Chameleon resource registry data for every node in all sites or
    in a specific site.

    Sites and node data should be indexed by their respective names.

    Args:
        site_name (str): An optional name for a specific site from which to get
        discovery data. (Default None).

    Returns:
        A dictionary with the discovery data for every node in all sites or
        in a specific site, if specified.

    Raises:
        HTTPError: If request for discovery data failed.
        ValueError: If ``site_name`` is invalid.
    """
    if site_name == "CHI@Edge":
        return None

    r = requests.get(SITES_URL)
    r.raise_for_status()
    r_json = r.json()
    name_uid = {r_json["items"][i]["name"]: r_json["items"][i]["uid"]
                for i in range(len(r_json["items"]))}

    if site_name:
        if site_name not in name_uid:
            raise ValueError(f"{site_name} is an invalid site name")
        r = requests.get(SITES_URL + name_uid[site_name] + NODES_SUFFIX)
        r.raise_for_status()
        data = r.json()["items"]
        return {data[i]["node_name"]: data[i] for i in range(len(data))}

    discovery_data = {}
    for count, name_uid in enumerate(name_uid.items(), 0):
        name, uid = name_uid
        if uid == "edge":
            continue
        r = requests.get(SITES_URL + uid + NODES_SUFFIX)
        r.raise_for_status()
        data = r.json()['items']
        for i in range(len(data)):
            discovery_data[name] = {data[i]["node_name"]: data[i]}
    return discovery_data


def get_nodes(display: bool = True):
    """Get node availability for all nodes in the user's selected site.

    Args:
        display (bool): An optional specification to display a pandas
        DataFrame of node availability. (Default True).

    Returns:
        A pandas DataFrame of node availability, if ``display=True``, or a
        tuple of available/unavailable nodes dictionaries.

    Raises:
        IllegalArgumentError: If the ``display`` parameter has an invalid type.
    """
    if type(display) is not bool:
        raise IllegalArgumentError(f"parameter 'display' expected type 'bool'"
                                   f", received '{type(display).__name__}'")
    all_nodes, unavail_nodes, avail_nodes, hosts = {}, {}, {}, {}
    discovery = get_discovery(get_site())

    try:
        client = chi.blazar()
        hosts = {host["hypervisor_hostname"]: host for host in
                 client.host.list()}
    except keystoneauth1.exceptions.http.Unauthorized:
        print(f"You lack the required authentication to access {get_site()}.")
        return None

    for uid, blazar_data in hosts.items():
        node_name = blazar_data["node_name"]
        node_type = discovery[node_name]["node_type"]
        free = blazar_data["reservable"]

        # initialize dict schema: { "node_type" : (# avail, # unavail) }
        all_nodes.setdefault(node_type, (0, 0))
        all_nodes[node_type] = (all_nodes[node_type][0] + free,
                                all_nodes[node_type][1] + (not free))
        node_data = discovery[node_name]

        if all_nodes[node_type][0]:
            avail_nodes[node_type] = node_data
        else:
            unavail_nodes[node_type] = node_data

    if display:
        num_avail, num_unavail = map(list, zip(*all_nodes.values()))
        d = {"Type": list(all_nodes.keys()),
             "Free": num_avail,
             "In Use": num_unavail}
        return pd.DataFrame(data=d)

    return avail_nodes, unavail_nodes


def choose_node(gpu: bool = None, gpu_count: int = None,
                ssd: bool = None, storage_size_gb: int = None,
                architecture: str = None, verbose=False):
    """Display an IPyWidget Select object with a selectable dropdown of all
    available nodes of the given parameters.

    Args:
        gpu (bool): An optional specification to include either nodes with at
        least 1 GPU or nodes with no GPUs. (Default None).
        gpu_count (int): An optional count of the exact desired number of node
        GPUs. (Default None).
        ssd (bool): An optional specification to include either nodes with at
        least 1 SSD or nodes with no SSDs. (Default None).
        storage_size_gb (int): An optional count of the minimum specified total
        node storage size in GB. (Default None).
        architecture (str): An optional name of the exact desired node
        architecture. (Default None).
        verbose (bool): An optional specification to display the data of
        each node when it is selected in the Select object. (Default False).

    Returns:
        IPyWidget Select object with nodes as options.

    Raises:
        IllegalArgumentError: If any combination of or single parameter(s)
        have an invalid type.
    """

    def node_dropdown_callback(change):
        update_selected_node(change["new"])

    def update_selected_node(node_type):
        node_output.clear_output()
        with node_output:
            chi.use_node(node_type, avail_nodes[node_type], verbose)

    if get_nodes(display=False) is None:
        return
    avail_nodes = get_nodes(display=False)[0]

    def _find_gpu_helper(nodes, req_count: int = None):
        """Find all nodes with or without GPUs, and restrict the set to nodes
        with a certain number of GPUs if specified.
        """
        new_nodes = {}
        for node_type, data in nodes.items():
            if req_count is None:
                if "gpu" in data and data["gpu"]["gpu"] is True:
                    new_nodes[node_type] = data
            elif req_count == 0 and ("gpu" not in data or
                                     data["gpu"]["gpu"] is False):
                new_nodes[node_type] = data
            elif req_count > 0 and "gpu" in data and data["gpu"]["gpu"] is \
                    True:
                true_count = data["gpu"]["gpu_count"]
                if true_count == req_count:
                    new_nodes[node_type] = data
        return new_nodes

    def _minimum_storage_helper(nodes, req_storage: int):
        """Find all nodes with a minimum total storage of REQ_STORAGE."""
        new_nodes = {}
        for node_type, data in nodes.items():
            total_storage = 0
            for device in data["storage_devices"]:
                total_storage += int(device["humanized_size"][:-3])
            if total_storage >= req_storage:
                new_nodes[node_type] = data
        return new_nodes

    def _find_architecture_helper(nodes, req_arc):
        """Find all nodes with an architecture platform type of REQ_ARC."""
        new_nodes = {}
        for node_type, data in nodes.items():
            if data["architecture"]["platform_type"] == req_arc:
                new_nodes[node_type] = data
        return new_nodes

    def _find_ssd_helper(nodes, ssd_req: bool):
        """Find all nodes with or without at least 1 SSD."""
        new_nodes = {}
        for node_type, data in nodes.items():
            for device in data["storage_devices"]:
                if "media_type" in device:
                    ssd_present = device["media_type"] == "SSD"
                    if ssd_req and ssd_present:
                        new_nodes[node_type] = data
                    if not ssd_req and not ssd_present:
                        new_nodes[node_type] = data
                elif not ssd_req:
                    new_nodes[node_type] = data
        return new_nodes

    if gpu_count is None:
        pass
    elif type(gpu_count) is int and gpu_count > 0:
        if gpu is False:
            raise IllegalArgumentError(f"input 'gpu' not compatible with "
                                       f"input 'gpu_count': False and"
                                       f" {gpu_count} contradict each other")

        avail_nodes = _find_gpu_helper(avail_nodes, gpu_count)
    elif type(gpu_count) is int and gpu_count == 0:
        if gpu is True:
            raise IllegalArgumentError(f"input 'gpu' not compatible with "
                                       f"input 'gpu_count': True and"
                                       f" 0 contradict one another")
        gpu = False
    else:
        raise IllegalArgumentError(f"parameter 'gpu_count' expected type 'int'"
                                   f" > 0, received input '{gpu_count}' of "
                                   f"type '{type(gpu_count).__name__}'")

    if gpu is None:
        pass
    elif gpu is True and gpu_count is None:
        avail_nodes = _find_gpu_helper(avail_nodes)
    elif gpu is False:
        avail_nodes = _find_gpu_helper(avail_nodes, 0)
    else:
        raise IllegalArgumentError(f"parameter 'gpu' expected type 'bool'"
                                   f", received type "
                                   f"'{type(gpu).__name__}'")

    if storage_size_gb is None:
        pass
    elif type(storage_size_gb) is int and storage_size_gb >= 0:
        avail_nodes = _minimum_storage_helper(avail_nodes, storage_size_gb)
    else:
        raise IllegalArgumentError(f"parameter 'storage_size_gb' expected type"
                                   f" 'int' > 0, received input "
                                   f"'{storage_size_gb}' of type "
                                   f"'{type(storage_size_gb).__name__}'")

    if architecture is None:
        pass
    elif type(architecture) is str:
        avail_nodes = _find_architecture_helper(avail_nodes, architecture)
    else:
        raise IllegalArgumentError(f"parameter 'architecture' expected type"
                                   f" 'str', received type"
                                   f" '{type(architecture).__name__}'")

    if ssd is None:
        pass
    elif type(ssd) is bool:
        avail_nodes = _find_ssd_helper(avail_nodes, ssd)
    else:
        raise IllegalArgumentError(f"parameter 'ssd' expected type"
                                   f" 'bool', received type"
                                   f" '{type(ssd).__name__}'")

    if not avail_nodes.keys():
        print("All nodes of the given parameters are currently reserved. "
              "Please try again later.")
        return

    node_output = widgets.Output()
    node_chooser = widgets.Select(options=avail_nodes.keys())

    # update selected node on callback
    node_chooser.observe(node_dropdown_callback, names="value")

    # initialize values before selection is made
    update_selected_node(node_chooser.value)

    return widgets.VBox([node_chooser, node_output])


def get_sites():
    """Get the user's sites by HTTP request.

    Returns:
        The list of sites, if found.

    Raises:
        HTTPError: If request for user's site data failed.
    """
    api_ret = requests.get(SITES_URL[:-1] + ".json")
    api_ret.raise_for_status()
    sites_ret = api_ret.json().get("items")

    for i in range(len(sites_ret) - 1):
        if sites_ret[i]["name"] == "CHI@Edge":
            del sites_ret[i]
    return sites_ret


def get_projects():
    """Get the user's projects by OS access token.

    Returns:
        The list of projects, if found.
    """
    os_token = environ.get("OS_ACCESS_TOKEN")
    jwt_info = jwt.decode(os_token, options={"verify_signature": False})
    return jwt_info.get("project_names")


def choose_site():
    """Display an IPyWidget Select object with a selectable dropdown of all
    available sites.

    Returns:
        IPyWidget Select object with sites as options.
    """

    def site_dropdown_callback(change):
        site_dict = change["new"]
        site_name = site_dict.get("name")
        update_selected_site(site_name)

    def update_selected_site(site_name):
        site_output.clear_output()
        with site_output:
            chi.use_site(site_name)

    site_output = widgets.Output()

    chooser_options = [(s.get("name"), s) for s in get_sites()]
    site_chooser = widgets.Select(
        options=chooser_options,
        value=chooser_options[0][1],
        rows=8
    )

    # update selected site on callback
    site_chooser.observe(site_dropdown_callback, names="value")

    # initialize values before selection is made
    update_selected_site(site_chooser.label)

    return widgets.VBox([site_chooser, site_output])


def choose_project():
    """Display an IPyWidget Select object with a selectable dropdown of all
    available projects.

    Returns:
        IPyWidget Select object with projects as options.
    """

    def project_dropdown_callback(change):
        update_selected_project(change["new"])

    def update_selected_project(project_name):
        chi.set("project_name", project_name)
        project_output.clear_output()
        with project_output:
            print(f"Using project: {project_name}")

    project_output = widgets.Output()
    project_names = get_projects()
    project_chooser = widgets.Select(
        options=project_names,
        rows=8,
        value=project_names[0]
    )

    # update selected project on callback
    project_chooser.observe(project_dropdown_callback, names="value")

    # initialize values before selection is made
    update_selected_project(project_chooser.value)

    return widgets.VBox([project_chooser, project_output])


def setup():
    """Horizontally display two IPyWidget Select objects with selectable
    dropdowns of all available projects and sites.

    Returns:
        IPyWidget HBox object of Select objects.
    """
    display(widgets.HBox([choose_project(), choose_site()]))
