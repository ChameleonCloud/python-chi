from os import environ

import ipywidgets as widgets
import jwt
import pandas as pd
import requests
import json
from IPython.core.display import display

import chi

from .context import get


def get_node_ids(site):
    """ Get the UIDs associated with each node_type for a given site.

    Not currently used.
    """
    discovery = get_discovery(site)
    return [(key, discovery[key]['uid']) for key in discovery.keys()]


def get_site():
    """ Get user's currently selected site. """
    return get("region_name")


def get_discovery(site_name: str = None):
    """ GET Chameleon resource registry node data for a specific site or
    all sites. Returns the name of the site(s), each node in that site(s),
    and the data associated with that node.

    Returns:
        { 'uid' : { 'node_type': { discovery data} } }
    """
    if site_name == 'CHI@Edge':  # handle edge case
        return None
    r = requests.get('https://api.chameleoncloud.org/sites/')
    jsonified = json.loads(r.text)
    name_uid = {jsonified['items'][i]['name']: jsonified['items'][i]['uid']
                for i in range(len(jsonified['items']))}

    if site_name:  # get site-specific discovery data
        if site_name not in name_uid:
            raise KeyError(f'{site_name} is an invalid site name')
        r = requests.get('https://api.chameleoncloud.org/sites/' +
                         name_uid[site_name] + '/clusters/chameleon/nodes')
        data = json.loads(r.text)['items']
        return {data[i]['node_type']: data[i] for i in range(len(data))}

    discovery_data, nodes = {}, {}
    for count, name_uid in enumerate(name_uid.items(), 0):  # get all discovery data
        name, uid = name_uid
        if uid == "edge":
            continue
        r = requests.get('https://api.chameleoncloud.org/sites/' + uid +
                            '/clusters/chameleon/nodes')
        data = json.loads(r.text)['items'][count]
        node_type = data['node_type']
        if node_type not in nodes.keys():
            nodes[node_type] = data
            continue
        nodes[node_type] = data
        discovery_data[name] = nodes

    return discovery_data


def get_nodes(display=True):
    """ Compute a tuple of available/unavailable nodes and their data
    and display availability for all nodes.

    Returns:
        if display=True:
            pandas df
        if display=False:
            ( { "avail_node": "blazar/disco data" }, { "unavail_node":
            "blazar/disco data" }
    """
    client = chi.blazar()
    allocations = client.host.list_allocations()
    hosts, states = {host["id"]: host for host in client.host.list()}, {}
    for alloc in allocations:
        uid = alloc["resource_id"]
        host = hosts[uid]
        host["reservations"] = alloc["reservations"]
        states[uid] = host

    all_nodes, unavailable_nodes, available_nodes = {}, {}, {}

    discovery = get_discovery(get_site())
    # Assume all unavail, then remove from set if avail
    for uid, blazar_data in hosts.items():
        node_type = blazar_data['node_type']
        free = blazar_data['reservable']
        unavailable_nodes[node_type] = [free, blazar_data['reservations']]

        # Initialize dict schema: { "node_type" : (# avail, # unavail) }
        all_nodes.setdefault(node_type, (0, 0))
        all_nodes[node_type] = (all_nodes[node_type][0] + free,
                                all_nodes[node_type][1] + (not free))
        # update available/unavailable nodes accordingly
        if all_nodes[node_type][0]:
            print(node_type)
            available_nodes[node_type] = unavailable_nodes[node_type]
            unavailable_nodes.pop(node_type)

    # Display availability for all nodes if requested (default)
    if display:
        num_avail, num_unavail = map(list, zip(*all_nodes.values()))
        list(all_nodes.values())
        d = {'Type': list(all_nodes.keys()),
             'In Use': num_avail,
             'Free': num_unavail}
        return pd.DataFrame(data=d)

    return available_nodes, unavailable_nodes


def custom_type_error(expected, received):
    raise TypeError(f"Expected type '{expected.__name__}', got "
                    f"'{received.__name__}' instead")


def choose_node(gpu: bool = None, gpu_count: int = None, ssd: bool = None,
                storage_size_gb: int = None, architecture: str = None):
    """ Return IPyWidget Select object for user to select from
    list of available nodes.

    Parameters: (all optional, default None)

    Display helpful information (TBD) when user selects a node.
    """
    # TODO: replace temporary arg typechecking
    if type(gpu) is not bool and gpu is not None:
        custom_type_error(bool, type(gpu))
    if type(gpu_count) is not int and gpu_count is not None:
        custom_type_error(int, type(gpu_count))
    if type(storage_size_gb) is not int and storage_size_gb is not None:
        custom_type_error(int, type(storage_size_gb))
    if type(ssd) is not bool and ssd is not None:
        custom_type_error(bool, type(ssd))
    if type(architecture) is not str and architecture is not None:
        custom_type_error(str, type(architecture))
    if gpu_count and gpu_count < 0:
        print("Gpu count too low")
        # TODO: raise some error

    def node_dropdown_callback(change):
        update_selected_node(change["new"])

    def update_selected_node(node_type):
        node_output.clear_output()
        with node_output:
            chi.use_node(node_type, available_nodes[node_type])

    # Get all available nodes and define ret_nodes
    available_nodes, ret_nodes = get_nodes(display=False)[1], {}

    # Assume that if someone queries for # gpus, they want nodes with GPUs
    if gpu_count:
        gpu = True
        # TODO: Implement GPU_COUNT argument logic

    # GPU argument logic
    if gpu is None:  # default
        print("Displaying all available nodes:")
        ret_nodes = available_nodes
    else:
        gpu_nodes, non_gpu_nodes = {}, {}
        for node, data in available_nodes.items():
            try:
                if data['gpu.gpu'] == 'True':
                    gpu_nodes[node] = data
                if data['gpu.gpu'] == 'False':
                    non_gpu_nodes[node] = data
            except KeyError:
                # if gpu key does not exist, assume that it has no gpu
                non_gpu_nodes[node] = data
                continue
        if gpu:
            print("Displaying all nodes with GPUs:")
            ret_nodes = gpu_nodes
        elif not gpu:
            print("Displaying all nodes without GPUs:")
            ret_nodes = non_gpu_nodes

    # TODO: Implement storage_size_gb argument logic
    # TODO: Implement ssd argument logic
    # TODO: Implement architecture argument logic

    # Display message and exit if all nodes unavailable
    if not list(ret_nodes.keys()):
        print("All nodes of the given parameters are currently reserved. "
              "Please try again later.")
        return

    node_output = widgets.Output()
    node_chooser = widgets.Select(options=ret_nodes.keys())

    # update selected note on callback
    node_chooser.observe(node_dropdown_callback, names='value')

    return widgets.VBox([node_chooser, node_output])


def get_sites():
    """ Return list of available sites. """
    api_ret = requests.get("https://api.chameleoncloud.org/sites.json")
    try:
        api_ret.raise_for_status()
    except Exception:
        print("failed to fetch sites")

    sites_ret = api_ret.json().get("items")
    return sites_ret


def get_projects():
    """ Return list of user's projects. """
    os_token = environ.get("OS_ACCESS_TOKEN")
    jwt_info = jwt.decode(os_token, options={"verify_signature": False})
    return jwt_info.get("project_names")


def choose_site():
    """ Return IPyWidget Select object for user to select from
    list of available sites.
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
    site_chooser.observe(site_dropdown_callback, names='value')

    # initialize values before selection is made
    update_selected_site(site_chooser.label)

    return widgets.VBox([site_chooser, site_output])


def choose_project():
    """ Return IPyWidget Select object for user to select from
    list of available projects.
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
    project_chooser.observe(project_dropdown_callback, names='value')

    # initialize values before selection is made
    update_selected_project(project_chooser.value)

    return widgets.VBox([project_chooser, project_output])


def setup():
    """ Display selectable list of available projects and sites. """
    display(widgets.HBox([choose_project(), choose_site()]))
