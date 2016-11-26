# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals
import functools

QUERIES = {}
def query(q):
    global QUERIES
    QUERIES[q.__name__] = {'f': q}
    return q


@query
def idle_projects(db):
    '''
    Returns rows enumerating all projects that are currently idle (number
    of running instances = 0). Also provides since when the project has been
    idle (when the latest running instance was deleted)
    '''
    sql = '''
    SELECT project.id
         , project.name
        #  , Count(ip.tenant_id)
         , (SELECT deleted_at
            FROM   nova.instances AS instance
            WHERE  instance.project_id = project.id
            ORDER  BY deleted_at DESC
            LIMIT  1)
                AS latest_deletion
    FROM   neutron.floatingips AS ip
       ,   keystone.project AS project
    WHERE  ip.tenant_id = project.id
           AND ip.status = "down"
           AND (SELECT Count(*)
                FROM   nova.instances
                    AS instance
                WHERE  instance.project_id = project.id
                       AND deleted_at IS NULL
                       AND vm_state != "deleted"
                       AND vm_state != "error") = 0
    GROUP  BY tenant_id
    ORDER  BY Count(tenant_id) DESC;
    '''
    return db.query(sql, limit=None)


@query
def owned_ips(db, project_ids):
    '''
    Return all IPs associated with *project_ids*

    Maria 5.5 in production doesn't seem to like this, but works fine with
    a local MySQL 5.7. Is it Maria? 5.5? Too many? See owned_ip_single for one
    that works, but need to call multiple times.
    '''
    sql = '''
    SELECT id
         , status
         , tenant_id AS project_id
    FROM   neutron.floatingips
    WHERE  tenant_id IN %s;
    '''
    return db.query(sql, args=[project_ids], limit=None)


@query
def owned_ip_single(db, project_id):
    '''
    Return all IPs associated with *project_id*
    '''
    sql = '''
    SELECT id
         , status
         , tenant_id AS project_id
    FROM   neutron.floatingips
    WHERE  tenant_id = %s;
    '''
    return db.query(sql, args=[project_id], limit=None)


@query
def projects_with_unowned_ports(db):
    sql = '''
    SELECT tenant_id AS project_id
         , count(tenant_id) AS count_blank_owner
    FROM   neutron.ports
    WHERE  device_owner = ''
    GROUP  BY tenant_id;
    '''
    return db.query(sql, limit=None)


@query
def owned_ports_single(db, project_id):
    sql = '''
    SELECT id
         , status
         , tenant_id AS project_id
    FROM   neutron.ports
    WHERE  tenant_id = %s;
    '''
    return db.query(sql, args=[project_id], limit=None)


@query
def future_reservations(db):
    '''
    Get project IDs with lease end dates in the future that haven't
    been deleted. This will also grab *active* leases, but that's erring
    on the safe side.
    '''
    sql = '''
    SELECT DISTINCT project_id
    FROM   blazar.leases
    WHERE  end_date > Now()
           AND deleted_at is NULL;
    '''
    return db.query(sql, limit=None)


def main(argv):
    import sys
    import argparse
    import ast

    from .mysqlargs import MySqlArgs

    parser = argparse.ArgumentParser(description='Run queries!')
    mysqlargs = MySqlArgs({
        'user': 'root',
        'password': '',
        'host': 'localhost',
        'port': 3306,
    })
    mysqlargs.inject(parser)

    parser.add_argument('query', type=str, choices=QUERIES,
        help='Query to run.',
    )
    parser.add_argument('qargs', type=str, nargs='*',
        help='Arguments for the query (if needed)'
    )

    args = parser.parse_args(argv[1:])
    mysqlargs.extract(args)

    db = mysqlargs.connect()

    # qargs = [ast.literal_eval(a) for a in args.qargs]

    try:
        for row in QUERIES[args.query]['f'](db, *args.qargs):
            print(row)
    except TypeError as e:
        if '{}() takes'.format(args.query) in str(e):
            print('Invalid number of arguments provided to query: {}'.format(str(e)), file=sys.stderr)
            return -1
        else:
            raise


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
