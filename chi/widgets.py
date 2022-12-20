from os import environ

import ipywidgets as widgets
import jwt
import keystoneauth1.exceptions.http
import pandas as pd
import requests
from IPython.core.display import display

import chi
from .context import get, RESOURCE_API_URL


def _build_request(sites: bool = False,
                   nodes: bool = False,
                   uid: str = "",
                   json: bool = False):
    """Construct resource API request URL.

    Returns:
        Resource API request URL.
    """
    url = RESOURCE_API_URL
    if sites:
        url += "/sites/"
    url += uid
    if nodes:
        url += "/clusters/chameleon/nodes"
    if json:
        url = url[:-1] + ".json"
    return url


def get_selected_site():
    """Get the user's selected site by context parameter.

    Returns:
        The name of the site, if selected.
    """
    return get("region_name")


def get_selected_node_type():
    """ Get the user's selected node by context parameter.

    Returns:
        The node type, if selected.
    """
    return get("node_type")


def get_resource_data(site_name: str = None):
    """Get the Chameleon resource registry data for every node in all sites or
    in a specific site.

    Sites and node data should be indexed by their respective names.

    Args:
        site_name (str): An optional name for a specific site from which to get
        resource data. (Default None).

    Returns:
        A dictionary with the resource data for every node in all sites or
        in a specific site, if specified.

    Raises:
        ValueError: If ``site_name`` is invalid.
    """
    if site_name == "CHI@Edge":
        return None

    r = requests.get(_build_request(sites=True))
    r.raise_for_status()
    r_json = r.json()
    node_names_to_uids = {r_json["items"][i]["name"]: r_json["items"][i]["uid"]
                          for i in range(len(r_json["items"]))}

    if site_name:
        if site_name not in node_names_to_uids:
            raise ValueError(f"{site_name} is an invalid site name")
        r = requests.get(_build_request(sites=True, nodes=True,
                                        uid=node_names_to_uids[site_name]))
        r.raise_for_status()
        data = r.json()["items"]
        return {data[i]["node_name"]: data[i] for i in range(len(data))}

    resource_data = {}
    for name_uid in node_names_to_uids.items():
        name, uid = name_uid
        if uid == "edge":
            continue
        r = requests.get(_build_request(sites=True, uid=uid, nodes=True))
        r.raise_for_status()
        data = r.json()['items']
        for i in range(len(data)):
            resource_data[name] = {data[i]["node_name"]: data[i]}
    return resource_data


def get_nodes(display: bool = True):
    """Get node availability for all nodes in the user's selected site.

    Args:
        display (bool): An optional specification to display a pandas
        DataFrame of node availability. (Default True).

    Returns:
        A pandas DataFrame of node availability, if ``display=True``, or a
        tuple of available/unavailable nodes dictionaries.

    Raises:
        Unauthorized: If user lacks required authentication.
    """
    all_nodes, unavail_nodes, avail_nodes, hosts = {}, {}, {}, {}
    resource_data = get_resource_data(get_selected_site())

    try:
        client = chi.blazar()
    except keystoneauth1.exceptions.http.Unauthorized as e:
        print(f"You lack the required authentication to access "
              f"{get_selected_site()}. Your user credentials "
              f"may have expired and need to be refreshed at "
              f"https://jupyter.chameleoncloud.org/auth/refresh.")
        raise e

    for blazar_data in client.host.list():
        node_name = blazar_data["node_name"]
        if node_name not in resource_data.keys():
            # skip blazar hosts not in resource data
            continue
        node_type = resource_data[node_name]["node_type"]
        free = blazar_data["reservable"]
        all_nodes.setdefault(node_type, {"avail": 0, "unavail": 0})
        all_nodes[node_type]["avail"] = all_nodes[node_type]["avail"] + (
            not free)
        all_nodes[node_type]["unavail"] = all_nodes[node_type][
                                              "unavail"] + free
        node_data = resource_data[node_name]

        if all_nodes[node_type]["avail"]:
            avail_nodes[node_type] = node_data
        else:
            unavail_nodes[node_type] = node_data

    if display:
        num_avail, num_unavail = map(list, zip(*[(i['avail'], i['unavail'])
                                                 for i in all_nodes.values()]))
        d = {"Type": list(all_nodes.keys()),
             "Free": num_avail,
             "In Use": num_unavail}
        return pd.DataFrame(data=d)

    return {"avail": avail_nodes, "unavail": unavail_nodes}


def choose_node_type(has_gpu: bool = None, gpu_count: int = None,
                     ssd: bool = None,
                     storage_size_gb: int = None, architecture: str = None,
                     verbose=False):
    """Display an IPyWidget Select object with a selectable dropdown of all
    available nodes of the given parameters.

    Args:
        has_gpu (bool): An optional specification to include either nodes with
        at least 1 GPU or nodes with no GPUs. (Default None).
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
        ValueError: If any parameter(s) or combination thereof are invalid.
    """

    def node_dropdown_callback(change):
        update_selected_node(change["new"])

    def update_selected_node(node_type):
        node_output.clear_output()
        with node_output:
            chi.use_node(node_type, avail_nodes[node_type], verbose)

    avail_nodes = get_nodes(display=False)["avail"]

    def has_gpu_helper(nodes, req_gpu):
        """Find all nodes with or without GPUs."""
        new_nodes = {}
        for node_type, data in nodes.items():
            gpu_exists = "gpu" in data and data["gpu"]["gpu"]
            if gpu_exists == req_gpu:
                new_nodes[node_type] = data
            if not gpu_exists and not req_gpu:
                new_nodes[node_type] = data
        return new_nodes

    def gpu_count_helper(nodes, req_count):
        """Find all nodes with exactly REQ_COUNT GPUs."""
        new_nodes = {}
        for node_type, data in nodes.items():
            gpu_exists = "gpu" in data and data["gpu"]["gpu"]
            if gpu_count < 0:
                raise ValueError(
                    f"'gpu_count' should be a non-negative integer")
            else:
                if gpu_exists:
                    true_count = data["gpu"]["gpu_count"]
                    if true_count == req_count:
                        new_nodes[node_type] = data
        return new_nodes

    def storage_size_gb_helper(nodes, req_storage: int):
        """Find all nodes with a minimum total storage of REQ_STORAGE."""
        new_nodes = {}
        if req_storage < 0:
            raise ValueError(
                f"'storage_size_gb' should be a non-negative integer")
        for node_type, data in nodes.items():
            total_storage = sum(int(device["humanized_size"][:-3]) for device
                                in data["storage_devices"])
            if total_storage >= req_storage:
                new_nodes[node_type] = data
        return new_nodes

    def architecture_helper(nodes, req_arc):
        """Find all nodes with an architecture platform type of REQ_ARC."""
        new_nodes = {}
        for node_type, data in nodes.items():
            if data["architecture"]["platform_type"] == req_arc:
                new_nodes[node_type] = data
        return new_nodes

    def ssd_helper(nodes, ssd_req: bool):
        """Find all nodes with or without at least 1 SSD."""
        new_nodes = {}
        for node_type, data in nodes.items():
            for device in data["storage_devices"]:
                if "media_type" in device:
                    ssd_present = device["media_type"] == "SSD"
                    if ssd_req == ssd_present:
                        new_nodes[node_type] = data
                elif not ssd_req:
                    new_nodes[node_type] = data
        return new_nodes

    if has_gpu is not None:
        avail_nodes = has_gpu_helper(avail_nodes, has_gpu)
    if gpu_count is not None:
        if has_gpu and gpu_count <= 0:
            raise ValueError("'has_gpu' specified, but requested nodes "
                             "with 0 GPUs")
        if not has_gpu and gpu_count > 0:
            raise ValueError("'gpu_count' specified, but requested nodes "
                             "without GPU")
        avail_nodes = gpu_count_helper(avail_nodes, gpu_count)
    if storage_size_gb is not None:
        avail_nodes = storage_size_gb_helper(avail_nodes, storage_size_gb)
    if architecture is not None:
        avail_nodes = architecture_helper(avail_nodes, architecture)
    if ssd is not None:
        avail_nodes = ssd_helper(avail_nodes, ssd)
    if not avail_nodes.keys():
        print("All nodes of the given parameters are currently reserved, "
              "or no nodes matched the constraints. See "
              "https://chameleoncloud.org/hardware for all node information.")
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
    """
    api_ret = requests.get(_build_request(sites=True, json=True))
    api_ret.raise_for_status()
    api_json = api_ret.json()
    if "items" not in api_json:
        raise ValueError("Malformed response from sites endpoint. Is the API "
                         "working correctly?")
    return [site for site in api_json.get("items") if site["name"] !=
            "CHI@Edge"]


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
