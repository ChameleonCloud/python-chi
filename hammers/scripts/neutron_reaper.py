# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import sys
import os
import argparse
import collections
import datetime
from pprint import pprint

from MySQLdb import ProgrammingError

from hammers import MySqlArgs, query
from hammers.slack import Slackbot

RESOURCE_QUERY = {
    'ip': query.owned_ip_single,
    'port': query.owned_ports_single,
}

RESOURCE_DELETE_COMMAND = {
    'ip': 'floatingip-delete',
    'port': 'port-delete',
}

assert set(RESOURCE_QUERY) == set(RESOURCE_DELETE_COMMAND)


def normalize_project_name(s):
    return s.lower().replace('-', '').strip()


def days_past(dt):
    return (datetime.datetime.utcnow() - dt).total_seconds() / (60*60*24)


def reaper(db, type_, idle_days, whitelist, describe=False):
    try:
        future_projects = {
            normalize_project_name(row['project_id'])
            for row
            in query.future_reservations(db)
        }
    except ProgrammingError as e:
        if "Table 'blazar.leases' doesn't exist" in str(e):
            # assume we're on KVM, we can't check this.
            future_projects = set()
        else:
            raise

    too_idle_projects = [
        proj
        for proj
        in query.idle_projects(db)
        if (
            days_past(proj['latest_deletion']) > idle_days
            and normalize_project_name(proj['id']) not in future_projects
            and normalize_project_name(proj['id']) not in whitelist
            and normalize_project_name(proj['name']) not in whitelist
        )
    ]
    too_idle_project_ids = [proj['id'] for proj in too_idle_projects]

    resource_query = RESOURCE_QUERY[type_]
    command = RESOURCE_DELETE_COMMAND[type_]

    n_things_to_remove = 0
    if not describe:
        for proj_id in too_idle_project_ids:
            for resource in resource_query(db, proj_id):
                print('{} {}'.format(command, resource['id']))
                n_things_to_remove += 1
    else:
        projects = collections.defaultdict(dict)
        for proj_id in too_idle_project_ids:
            for resource in resource_query(db, proj_id):
                assert proj_id == resource.pop('project_id')
                projects[proj_id][resource.pop('id')] = resource
                n_things_to_remove += 1
        print('Format: {project_id: {resource_id: {INFO} ...}, ...}\n')
        pprint(dict(projects))
        # print(json.dumps(dict(projects), indent=4))

    return n_things_to_remove


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description='Floating IP reclaimer. Run '
        'by itself as a "dry run," or pipe it to the Neutron client.')
    mysqlargs = MySqlArgs({
        'user': 'root',
        'password': '',
        'host': 'localhost',
        'port': 3306,
    })
    mysqlargs.inject(parser)

    parser.add_argument('-w', '--whitelist', type=str,
        help='File of project/tenant IDs/names to ignore, one per line. '
             'Ignores case and dashes.')
    parser.add_argument('-i', '--info', action='store_true',
        help='Rather than print Neutron commands, print out info about them.')
    parser.add_argument('--slack', type=str,
        help='JSON file with Slack webhook information to send a notification to')
    parser.add_argument('type', choices=list(RESOURCE_QUERY),
        help='Grab floating IPs or ports?')
    parser.add_argument('idle_days', type=float,
        help='Number of days since last active instance in project was '
        'deleted to consider it idle.')

    args = parser.parse_args(argv[1:])
    mysqlargs.extract(args)

    if args.slack:
        slack = Slackbot(args.slack)
    else:
        slack = None

    whitelist = set()
    if args.whitelist:
        with open(args.whitelist) as f:
            whitelist = {normalize_project_name(line) for line in f}

    db = mysqlargs.connect()

    remove_count = reaper(db, args.type, args.idle_days, whitelist, args.info)

    if slack and not args.info:
        thing = '{}{}'.format(
            {'ip': 'floating IP', 'port': 'port'}[args.type],
            ('' if remove_count == 1 else 's'),
        )

        if remove_count > 0:
            message = (
                'Commanded deletion of *{} {}* ({:.0f} day grace-period)'
                .format(remove_count, thing, args.idle_days)
            )
            color = '#000000'
        else:
            message = (
                'No {} to delete ({:.0f} day grace-period)'
                .format(thing, args.idle_days)
            )
            color = '#cccccc'

        slack.post('neutron-reaper', message, color=color)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
