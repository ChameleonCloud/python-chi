# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import requests


def ironic_node(auth, node):
    if isinstance(node, dict):
        node = node['uuid']

    response = requests.get(
        url=auth.endpoint('baremetal') + '/v1/nodes/{}'.format(node),
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    return data


def ironic_nodes(auth):
    response = requests.get(
        url=auth.endpoint('baremetal') + '/v1/nodes',
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    return {n['uuid']: n for n in data['nodes']}


def ironic_ports(auth):
    response = requests.get(
        url=auth.endpoint('baremetal') + '/v1/ports/detail',
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    return {n['uuid']: n for n in data['ports']}


def neutron_ports(auth):
    response = requests.get(
        url=auth.endpoint('network') + '/v2.0/ports',
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    return {n['id']: n for n in data['ports']}


def nova_instance(auth, id):
    response = requests.get(
        auth.endpoint('compute') + '/servers/{}'.format(id),
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    server = response.json()['server']
    return server


def nova_instances(auth, **params):
    default_params = {'all_tenants': 1}
    default_params.update(params)

    response = requests.get(
        auth.endpoint('compute') + '/servers',
        params=default_params,
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    servers = response.json()['servers']
    servers = {s['id']: s for s in servers}
    return servers


def nova_instances_details(auth, **params):
    default_params = {'all_tenants': 1}
    default_params.update(params)

    response = requests.get(
        auth.endpoint('compute') + '/servers/detail',
        params=default_params,
        headers={'X-Auth-Token': auth.token},
    )
    data = response.json()
    if response.status_code != requests.codes.OK:
        raise RuntimeError(data)

    servers = response.json()['servers']
    servers = {s['id']: s for s in servers}
    return servers
