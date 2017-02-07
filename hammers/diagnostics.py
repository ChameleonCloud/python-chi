from __future__ import absolute_import, print_function, unicode_literals

import operator

from . import osrest


def find_lease(leases, name_or_id):
    """name_or_id can be the lease name, or lease/reservation id."""
    # search lease IDs
    try:
        return next(l for lid, l in leases.items() if lid == name_or_id)
    except StopIteration:
        pass

    # search reservation IDs
    try:
        return next(l for lid, l in leases.items() if l['reservations'][0]['id'] == name_or_id)
    except StopIteration:
        pass

    # search names
        candidates = [l for lid, l in leases.items() if l['name'] == name_or_id]
        if len(candidates) > 1:
            print('warning: multiple leases match based on name: selecting one with latest end-date', file=sys.stderr)
        elif len(candidates) < 1:
            raise RuntimeError('no leases found with name or ID "{}"'.format(name_or_id))

        return max(candidates, key=operator.itemgetter('end_date'))


def lease_aggregate(auth, lease):
    return osrest.nova_aggregate_details(auth, lease['reservations'][0]['resource_id'])


def nodes_in_lease(auth, lease):
    return lease_aggregate(auth, lease)['hosts']


def node_filter(auth, nodes):
    if len(nodes) < 1:
        return []
    elif len(nodes) <= 1:
        return osrest.ironic_node(auth, nodes[0])

    all_nodes = osrest.ironic_nodes(auth, details=True)
    lease_nodes = {nid: n for nid, n in all_nodes.items() if nid in nodes}
    assert len(lease_nodes) == len(nodes)
    return lease_nodes
