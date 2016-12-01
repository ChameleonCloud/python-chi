# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import argparse
import json
from pprint import pprint

import requests

from hammers.osapi import load_osrc, Auth


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description='Remove orphan ports in '
        'Neutron referring to an inactive Ironic instance')

    parser.add_argument('-i', '--info', action='store_true',
        help='Rather than do anything, print info about what we\'d do.')
    parser.add_argument('rcfile', type=str,
        help='Connection parameter file. Should include password.')

    args = parser.parse_args(argv[1:])

    rc = load_osrc(args.rcfile)
    auth = Auth(rc)
    ironic = auth.endpoint('baremetal')

    nodes = requests.get(
        url=ironic + '/v1/nodes',
        headers={'X-Auth-Token': auth.token},
    ).json()['nodes']
    nodes = {n['uuid']: n for n in nodes}

    ports = requests.get(
        url=ironic + '/v1/ports/detail',
        headers={'X-Auth-Token': auth.token},
    ).json()['ports']
    ports = {p['uuid']: p for p in ports}

    neut_ports = requests.get(
        url=auth.endpoint('network') + '/v2.0/ports',
        headers={'X-Auth-Token': auth.token},
    ).json()['ports']
    neut_ports = {p['id']: p for p in neut_ports}

    active_nodes = {
        nid: node
        for nid, node
        in nodes.items()
        if node['instance_uuid']
    }
    orphan_ports = {
        pid: port
        for pid, port
        in ports.items()
        if (port['extra']
            and port['node_uuid'] not in active_nodes)
    }

    neut_mac_map = {port['mac_address']: pid for pid, port in neut_ports.items()}
    node_mac_map = {port['address']: port['node_uuid'] for port in ports.values()}

    neut_macs = set(neut_mac_map)
    orphan_macs = {ports[pid]['address'] for pid in orphan_ports}

    conflict_macs = orphan_macs & neut_macs

    if args.info:
        # no-op
        print('CONFLICTS')
        for mac in conflict_macs:
            node = nodes[node_mac_map[mac]]
            neut_port = neut_ports[neut_mac_map[mac]]

            # node_detail = requests.get(
            #     url=ironic + '/v1/nodes/{}'.format(node['uuid']),
            #     headers={'X-Auth-Token': auth.token},
            # ).json()

            print('-----')
            print('MAC Address:          {}'.format(mac))
            print('Ironic Node ID:       {}'.format(node['uuid']))
            print('Ironic Node Instance: {}'.format(node['instance_uuid']))
            print('Neutron Port ID:      {}'.format(neut_port['id']))
            print('Neutron Port Details:')
            pprint(neut_port)
    else:
        raise RuntimeError("we don't actually do anything yet...")

if __name__ == '__main__':
    sys.exit(main(sys.argv))
