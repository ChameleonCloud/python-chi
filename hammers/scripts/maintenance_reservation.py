# coding: utf-8
from __future__ import absolute_import, print_function

import sys
import os
import argparse
import datetime
import traceback

from dateutil import tz
import mysql.connector

from climateclient import client as climate_client
from ironicclient import client as ironic_client
from keystoneclient.auth.identity import v2
from keystoneclient import session
from keystoneclient.v2_0 import client


def main():
    # Command line argument(s)
    parser = argparse.ArgumentParser()

    v2.Password.register_argparse_arguments(parser)
    session.Session.register_cli_options(parser)

    # add Region argument to parser
    parser.add_argument(
        '--os-region-name',
        metavar='<region-name>', default=os.environ.get('OS_REGION_NAME'),
        help='Specify the region to use. Defaults to env[OS_REGION_NAME].',
    )
    parser.add_argument('--os_region_name', help=argparse.SUPPRESS)
    parser.add_argument(
        'nodes', metavar='node', nargs='+',
        help='node(s) to put in maintenance mode',
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help='Perform a trial run without making reservations.',
    )
    parser.add_argument('--db-user', help='(Blazar) DB User', required=True)
    parser.add_argument('--db-pass', help='DB Password', default='')

    args = parser.parse_args()

    # Open Keystone Authenticated Session
    auth = v2.Password.load_from_argparse_arguments(args)
    sess = session.Session(auth=auth)
    keystone = client.Client(session=sess)

    token = sess.get_token()

    # Discover BareMetal Internal Endpoint
    try:
        ironic_url = sess.get_endpoint(service_type='baremetal', interface='internal')
    except Exception:
        traceback.print_exc(file=sys.stdout)
    ironic = ironic_client.get_client(1, os_auth_token=token, ironic_url=ironic_url)

    # Discover Reservation Internal Endpoint
    try:
        blazar_url = sess.get_endpoint(service_type='reservation', interface='internal')
    except Exception:
        traceback.print_exc(file=sys.stdout)
    blazar = climate_client.Client(climate_url=blazar_url,  auth_token=token)

    db_kwargs = {
        'database': 'blazar',
        'user': args.db_user,
        #'password': args.db_pass,
    }
    if args.db_pass:
        db_kwargs['password'] = args.db_pass
    blazardb = mysql.connector.connect(**db_kwargs)
    cursor = blazardb.cursor(buffered=False)
    query = """
        SELECT     leases.end_date
        FROM       leases
        INNER JOIN reservations
        ON         reservations.lease_id = leases.id
        INNER JOIN computehost_allocations
        ON         reservations.id = computehost_allocations.reservation_id
        INNER JOIN computehosts
        ON         computehosts.id = computehost_allocations.compute_host_id
        WHERE      computehosts.hypervisor_hostname = %(node_uuid)s
               AND leases.deleted != leases.id
               AND end_date > NOW()
        ORDER BY   end_date DESC
        LIMIT      1;
    """

    time_format = "%Y-%m-%d %H:%M"
    time_format_z = time_format + ' %Z'
    utc_zone = tz.tzutc()

    # Main Loop
    for node in args.nodes:
        node_uuid = ironic.node.get(node).uuid.encode('ascii', 'replace')
        node_name = ironic.node.get(node).name.encode('ascii', 'replace')

        cursor.execute(query, {'node_uuid': node_uuid})
        last_end_time = cursor.fetchone()
        if last_end_time:
            last_end_time = last_end_time[0].replace(tzinfo=utc_zone)
        else:
            last_end_time = datetime.datetime.utcnow()

        next_start_time = last_end_time + datetime.timedelta(seconds=60)
        next_end_time = last_end_time + datetime.timedelta(days=4)

        lease_name = "maintenance_{}".format(node_name)
        resource_properties = '["=", "$uid", "{}"]'.format(node_uuid)
        phys_res = {
            'min': "1",
            'max': "1",
            'hypervisor_properties': "",
            'resource_properties': resource_properties,
            'resource_type': 'physical:host',
        }
        next_start_str = next_start_time.strftime(time_format)
        next_end_str = next_end_time.strftime(time_format)

        print(("Creating maintenance reservation for node %(node)s, "
               "starting %(start)s and ending %(end)s") % {
            'node': node_name,
            'start': next_start_time.strftime(time_format_z),
            'end': next_end_time.strftime(time_format_z)
        })
        if not args.dry_run:
            blazar.lease.create(
                name=lease_name,
                start=next_start_str,
                end=next_end_str,
                reservations=[phys_res],
                events=[],
            )
        blazardb.close()


if __name__ == "__main__":
    sys.exit(main())
