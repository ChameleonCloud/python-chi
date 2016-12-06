# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import os
import argparse
import json
from pprint import pprint

import requests

from hammers.osapi import load_osrc, Auth
from hammers.osrest import ironic_nodes, nova_instances
from hammers.slack import Slackbot

OS_ENV_PREFIX = 'OS_'


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description='Kick Ironic nodes that '
        'refer to a deleted/nonexistant Nova instance')

    parser.add_argument('mode', choices=['info', 'delete'],
        help='Just display data on the bound nodes or delete them')
    parser.add_argument('--slack', type=str,
        help='JSON file with Slack webhook information to send a notification to')
    parser.add_argument('--osrc', type=str,
        help='Connection parameter file. Should include password. envars used '
        'if not provided by this file.')

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

    nodes = ironic_nodes(auth)
    instances = nova_instances(auth)

    node_instance_map = {
        n['instance_uuid']: n
        for n
        in nodes.values()
        if n['instance_uuid'] is not None
    }

    node_instance_ids = set(node_instance_map)
    instance_ids = set(instances)

    unbound_instances = node_instance_ids - instance_ids

    if args.mode == 'info':
        # no-op
        if unbound_instances:
            print('ZOMBIE INSTANCES ON NODES')
        else:
            print('No zombies currently.')
        for inst_id in unbound_instances:
            node = node_instance_map[inst_id]
            try:
                instance = instances[inst_id]
            except KeyError:
                pass
            else:
                raise AssertionError('contradiction, this should be impossible')

            print('-----')
            print('Ironic Node\n'
                  '  ID:       {}'.format(node['uuid']))
            print('  Instance: {}'.format(node['instance_uuid']))
            print('  State:    {}'.format(node['provision_state']))

    elif args.mode == 'delete':
        # TODO: enable this
        # for inst_id in unbound_instances:
        #     ironic_node_set_state(auth, node_instance_map[inst_id], 'deleted')

        if slack:
            if unbound_instances:
                message = 'Possible Ironic nodes with nonexistant instances:\n{}'.format(
                    '\n'.join(
                        ' • node `{}` → instance `{}`'.format(
                            node_instance_map[i]['uuid'],
                            node_instance_map[i]['instance_uuid'])
                        for i in unbound_instances
                    )
                )
                color = '#cc0000'
            else:
                message = 'No Ironic nodes visibly clinging to dead instances'
                color = '#cccccc'

            slack.post('undead-instances', message, color=color)

        else: # TODO: remove
            raise RuntimeError("we don't actually do anything yet...")

    else:
        assert False, 'unknown command'

if __name__ == '__main__':
    sys.exit(main(sys.argv))
