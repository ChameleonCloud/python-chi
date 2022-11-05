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
    """ Use discovery data to get the UIDs associated with each node_type
    for a given site.
    """
    discovery = get_discovery(site)
    return [(key, discovery[key]['uid']) for key in discovery.keys()]


def get_site():
    """ Get user's currently selected site. """
    return get("region_name")


def get_discovery(site_name: str = None):
    """ Get Chameleon resource registry node data for all sites or a single
    specific site. Returns the name of the site(s), each node in that site(s),
    and the data associated with that node. The data associated with each node
    should be indexed into by node name. Note that CHI@Edge is an exception.

    Returns:
        if site_name:
            { 'site_name' : { 'node_name': { discovery data } } }

        if not site_name:
            { 'node_name': { discovery data } }
    """
    if site_name == 'CHI@Edge':
        return None
    r = requests.get('https://api.chameleoncloud.org/sites/')
    r_json = json.loads(r.text)
    name_uid = {r_json['items'][i]['name']: r_json['items'][i]['uid']
                for i in range(len(r_json['items']))}

    if site_name:
        if site_name not in name_uid:
            raise KeyError(f'{site_name} is an invalid site name')
        r = requests.get('https://api.chameleoncloud.org/sites/' +
                         name_uid[site_name] + '/clusters/chameleon/nodes')
        data = json.loads(r.text)['items']
        return {data[i]['node_name']: data[i] for i in range(len(data))}

    discovery_data = {}
    for count, name_uid in enumerate(name_uid.items(), 0):
        name, uid = name_uid
        if uid == "edge":
            continue
        r = requests.get('https://api.chameleoncloud.org/sites/' + uid +
                         '/clusters/chameleon/nodes')
        data = json.loads(r.text)['items'][count]
        discovery_data[name] = {data['node_name']: data}
    return discovery_data


def get_nodes(display=True):
    """ Construct tuples of node availability for all nodes. By default,
    display availability for all nodes; otherwise, return the data itself.

    Returns:
        if display=True:
            pandas df with cols('Type', 'In Use', 'Free')
        if display=False:
            ( { "avail_node": "disco data" }, { "unavail_node": disco data" } )
    """
    all_nodes, unavail_nodes, avail_nodes = {}, {}, {}
    discovery = get_discovery(get_site())
    client = chi.blazar()
    hosts = {host["hypervisor_hostname"]: host for host in client.host.list()}

    for uid, blazar_data in hosts.items():
        node_name = blazar_data['node_name']
        node_type = discovery[node_name]['node_type']
        free = blazar_data['reservable']

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
        d = {'Type': list(all_nodes.keys()),
             'In Use': num_avail,
             'Free': num_unavail}
        return pd.DataFrame(data=d)

    return avail_nodes, unavail_nodes


def choose_node(gpu: bool = None, gpu_count: int = None,
                ssd: bool = None, storage_size_gb: int = None,
                architecture: str = None):
    """ Return IPyWidget Select object for user to select from
    list of available nodes of the given parameters.

    Parameters: (all optional, default None)
    """
    def node_dropdown_callback(change):
        update_selected_node(change["new"])

    def update_selected_node(node_type):
        node_output.clear_output()
        with node_output:
            chi.use_node(node_type, avail_nodes[node_type])

    avail_nodes = get_nodes(display=False)[0]

    def find_gpu(nodes, count: int = None):
        """ Find all nodes with GPUs, and restrict the set to nodes with
        a certain number of GPUs if specified.
        """
        # find all with GPUs
        if count:
            print("Implement me")
            # out of those with GPUs, find with GPU == count GPUs

        return nodes  # TODO: Change me

    # GPU_COUNT logic
    if gpu_count is None:
        pass
    elif gpu_count > 0:
        print("gpu_count is > 0")
        avail_nodes = find_gpu(avail_nodes, gpu_count)
    elif gpu_count == 0:
        print("gpu_count is 0 ")
        if gpu is True:
            raise TypeError("Can't have gpu=True, gpu_count=0")
    else:
        raise TypeError(f"Invalid parameter gpu_count={gpu_count}")

    # GPU logic
    if gpu is None:
        pass
    elif gpu is True and gpu_count is None:
        print("gpu is true and gpu_count is none")
        avail_nodes = find_gpu(avail_nodes)
    elif gpu is False:
        print("gpu is false")
        avail_nodes = find_gpu(avail_nodes, 0)
    else:
        raise TypeError(f"Invalid parameter gpu={gpu}")

    # TODO: implement STORAGE_SIZE_GB
    # TODO: implement SSD
    # TODO: implement architecture

    if not list(avail_nodes.keys()):
        print("All nodes of the given parameters are currently reserved. "
              "Please try again later.")
        return

    node_output = widgets.Output()
    node_chooser = widgets.Select(options=avail_nodes.keys())

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
