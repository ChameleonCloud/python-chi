# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import os
import argparse
import json
from pprint import pprint

import requests

from hammers.osapi import load_osrc, Auth
from hammers.slack import reporter_factory

OS_ENV_PREFIX = 'OS_'


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description='Remove orphan ports in '
        'Neutron referring to an inactive Ironic instance')

    parser.add_argument('mode', choices=['info', 'delete'],
        help='Just display data on the conflict ports or delete them')
    parser.add_argument('--slack', type=str,
        help='JSON file with Slack webhook information to send a notification to')
    parser.add_argument('--osrc', type=str,
        help='Connection parameter file. Should include password. envars used '
        'if not provided by this file.')

    args = parser.parse_args(argv[1:])

    if args.slack:
        reporter = reporter_factory(args.slack)
    else:
        reporter = None

    os_vars = {k: os.environ[k] for k in os.environ if k.startswith(OS_ENV_PREFIX)}
    if args.osrc:
        os_vars.update(load_osrc(args.osrc))
    missing_os_vars = set(Auth.required_os_vars) - set(os_vars)
    if missing_os_vars:
        print(
            'Missing required OS values in env/rcfile: {}'
            .format(', '.join(missing_os_vars)),
            file=sys.stderr
        )
        return -1

    auth = Auth(os_vars)

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

    if args.mode == 'info':
        # no-op
        if conflict_macs:
            print('CONFLICTS')
        else:
            print('No conflicts currently.')
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

    elif args.mode == 'delete':
        # TODO: enable this
        if reporter:
            if conflict_macs:
                reporter('Possible ironic/neutron MAC conflicts: {}'.format(conflict_macs))
        else:
            raise RuntimeError("we don't actually do anything yet...")

    else:
        assert False, 'unknown command'

if __name__ == '__main__':
    sys.exit(main(sys.argv))
