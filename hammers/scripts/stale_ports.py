# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import json

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

    ports = requests.get(
        url=ironic + '/v1/ports/detail',
        headers={'X-Auth-Token': auth.token},
    ).json()['ports']

    active = {n['uuid'] for n in nodes if n['instance_uuid']}
    orphan = [p for p in ports if (p['extra'] and p['node_uuid'] not in active)]

    print(orphan)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
