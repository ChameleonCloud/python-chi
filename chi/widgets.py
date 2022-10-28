from os import environ

import ipywidgets as widgets
import jwt
import requests
from IPython.core.display import display

import chi


def get_nodes(display=True):
    """ Compute a tuple of available/unavailable nodes and their data
    and display availability for all nodes.

    Returns:
        ( ["all node_types"], { "avail_node": "data" }, { "unavail_node":
        "data" }
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

    # Assume all unavail, then remove from set if avail
    for uid, data in hosts.items():
        node_type = data['node_type']
        unavailable_nodes[node_type] = data
        free = data['reservable']

        # Initialize dict schema: { "node_type" : (# avail, # unavail) }
        all_nodes.setdefault(node_type, (0, 0))
        all_nodes[node_type] = (all_nodes[node_type][0] + free,
                                all_nodes[node_type][1] + (not free))

        # update available/unavailable nodes accordingly
        if all_nodes[node_type][0]:
            unavailable_nodes.pop(node_type)
            available_nodes[node_type] = data

    # Display availability for all nodes if requested (default)
    if display:
        print(f'Available nodes: {list(available_nodes.keys())}\n'
              f'Unavailable nodes: {list(unavailable_nodes.keys())}')

    return list(all_nodes.keys()), available_nodes, unavailable_nodes


def choose_node_type():
    """ Return IPyWidget Select object for user to select from
    list of available nodes.

    Display helpful information (TBD) when user selects a node.
    """
    def node_dropdown_callback(change):
        update_selected_node(change["new"])

    def update_selected_node(node_type):
        node_output.clear_output()
        with node_output:
            chi.use_node(node_type, available_nodes[node_type])

    # The code below is USED in production only; NOT USED in dev
    # all_nodes, available_nodes = \
    #     get_nodes(display=False)[0], get_nodes(display=False)[1],

    # The code below is NOT USED in production; USED in dev only
    # Mock node_types and their data
    avail_node_1_data = lambda: None
    avail_node_1_data.gpu = "some_gpu_name"
    avail_node_2_data = lambda: None
    avail_node_2_data.gpu = "some_gpu_name_2"
    available_nodes = {"avail_node_1": avail_node_1_data,
                       "avail_node_2": avail_node_2_data}

    # Display message and exit if all nodes unavailable
    if not list(available_nodes.keys()):
        print("All nodes are currently reserved. Please try again later.")
        return

    node_output = widgets.Output()
    node_chooser = widgets.Select(options=available_nodes.keys())

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
