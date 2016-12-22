# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import os
import argparse
import collections
import json
from pprint import pprint

import requests

from hammers import osapi, osrest
from hammers.slack import Slackbot

OS_ENV_PREFIX = 'OS_'


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description='Strange things, as per '
        'someone\'s definition of "strange".')

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
        os_vars.update(osapi.load_osrc(args.osrc))
    missing_os_vars = set(osapi.Auth.required_os_vars) - set(os_vars)
    if missing_os_vars:
        print(
            'Missing required OS values in env/rcfile: {}'
            .format(', '.join(missing_os_vars)),
            file=sys.stderr
        )
        return -1

    auth = osapi.Auth(os_vars)

    nodes = osrest.ironic_nodes(auth, details=True)
    # hypervisors = osrest.nova_hypervisors(auth, details=True)

    errored_nodes = [
        n
        for n
        in nodes.values()
        if n['provision_state'] == 'error' and not n['maintenance']
    ]

    if slack:
        'to do'
    else:
        if errored_nodes:
            print('Ironic nodes in "error" provision state, not in maintenance:')
        for n in errored_nodes:
            print('* {}, last error: {}'.format(n['uuid'], n.get('last_error')))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
