# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import os
import argparse
import json
from pprint import pprint

import requests

from hammers import osrest
from hammers.osapi import load_osrc, Auth
from hammers.slack import Slackbot

OS_ENV_PREFIX = 'OS_'
SUBCOMMAND = 'conflict-macs'


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
    parser.add_argument('-v', '--verbose', action='store_true')

    args = parser.parse_args(argv[1:])

    if args.slack:
        slack = Slackbot(args.slack)
    else:
        slack = None

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

    nodes = osrest.ironic_nodes(auth)
    ports = osrest.ironic_ports(auth)
    neut_ports = osrest.neutron_ports(auth)

    # mac --> uuid mappings
    node_mac_map = {port['address']: port['node_uuid'] for port in ports.values()}
    port_mac_map = {port['address']: pid for pid, port in ports.items()}
    neut_mac_map = {port['mac_address']: pid for pid, port in neut_ports.items()}

    neut_macs = set(neut_mac_map)

    inactive_nodes = {
        nid: node
        for nid, node
        in nodes.items()
        if node['instance_uuid'] is None
    }
    inactive_ports = {
        pid: port
        for pid, port
        in ports.items()
        if port['node_uuid'] in inactive_nodes
    }
    inactive_macs = {port['address'] for port in inactive_ports.values()}

    conflict_macs = neut_macs & inactive_macs

    if args.mode == 'info':
        # no-op
        if conflict_macs:
            print('CONFLICTS')
        else:
            print('No conflicts currently.')
        for mac in conflict_macs:
            node = nodes[node_mac_map[mac]]
            neut_port = neut_ports[neut_mac_map[mac]]

            print('-----')
            print('MAC Address:          {}'.format(mac))
            print('Ironic Node ID:       {}'.format(node['uuid']))
            print('Ironic Node Instance: {}'.format(node['instance_uuid']))
            print('Neutron Port ID:      {}'.format(neut_port['id']))
            print('Neutron Port Details:')
            pprint(neut_port)

    elif args.mode == 'delete':
        if slack:
            if conflict_macs:
                message = 'Attempting to remove Ironic/Neutron MAC conflicts\n{}'.format(
                    '\n'.join(
                        ' • Neutron Port `{}` → `{}` ← Ironic Node `{}` (Port `{}`)'
                        .format(neut_mac_map[m], m, node_mac_map[m], port_mac_map[m])
                        for m in conflict_macs
                    )
                )
                color = 'xkcd:darkish red'
            elif args.verbose:
                message = 'No visible Ironic/Neutron MAC conflicts'
                color = 'xkcd:light grey'
            else:
                message = None

            if message:
                slack.post(SUBCOMMAND, message, color=color)

        try:
            for mac in conflict_macs:
                osrest.neutron_port_delete(auth, neut_ports[neut_mac_map[mac]])
        except Exception as e:
            if slack:
                error = '{} raised while trying to delete ports, check logs'.format(type(e))
                slack.post(SUBCOMMAND, error, color='xkcd:red')
            raise
        else:
            if conflict_macs and slack:
                ok_message = 'Deleted {} neutron port(s)'.format(len(conflict_macs))
                slack.post(SUBCOMMAND, ok_message, color='xkcd:chartreuse')


    else:
        assert False, 'unknown command'

if __name__ == '__main__':
    sys.exit(main(sys.argv))
