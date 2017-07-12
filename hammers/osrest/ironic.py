import requests


def ironic_node(auth, node):
    if isinstance(node, dict):
        node = node['uuid']

    response = requests.get(
        url=auth.endpoint('baremetal') + '/v1/nodes/{}'.format(node),
        headers={
            'X-Auth-Token': auth.token,
            'X-OpenStack-Ironic-API-Version': '1.9',
        },
    )
    response.raise_for_status()
    data = response.json()
    return data


def ironic_node_set_state(auth, node, state):
    if isinstance(node, dict):
        node = node['uuid']

    response = requests.put(
        url=auth.endpoint('baremetal') + '/v1/nodes/{}/states/provision'.format(node),
        json={'target': state},
        headers={
            'X-Auth-Token': auth.token,
            'X-OpenStack-Ironic-API-Version': '1.9',
        },
    )
    response.raise_for_status()
    return response


# def ironic_node_update(auth, node, *, add=None, remove=None, replace=None):
# <python 2 compat>
def ironic_node_update(auth, node, **kwargs):
    add = kwargs.get('add')
    remove = kwargs.get('remove')
    replace = kwargs.get('replace')
# </python 2 compat>
    patch = []
    if replace is not None:
        for key, value in replace.items():
            patch.append({'op': 'replace', 'path': key, 'value': value})

    if isinstance(node, dict):
        node = node['uuid']

    response = requests.patch(
        url=auth.endpoint('baremetal') + '/v1/nodes/{}'.format(node),
        headers={
            'X-Auth-Token': auth.token,
            'X-OpenStack-Ironic-API-Version': '1.9',
        },
        json=patch,
    )
    response.raise_for_status()
    data = response.json()
    return data


def ironic_nodes(auth, details=False):
    path = '/v1/nodes' if not details else '/v1/nodes/detail'
    response = requests.get(
        url=auth.endpoint('baremetal') + path,
        headers={
            'X-Auth-Token': auth.token,
            'X-OpenStack-Ironic-API-Version': '1.9',
        },
    )
    response.raise_for_status()
    data = response.json()

    return {n['uuid']: n for n in data['nodes']}


def ironic_ports(auth):
    response = requests.get(
        url=auth.endpoint('baremetal') + '/v1/ports/detail',
        headers={
            'X-Auth-Token': auth.token,
            'X-OpenStack-Ironic-API-Version': '1.9',
        },
    )
    response.raise_for_status()
    data = response.json()

    return {n['uuid']: n for n in data['ports']}
