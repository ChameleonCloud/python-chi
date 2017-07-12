import requests


FREEPOOL_AGGREGATE_ID = 1
RESET_STATES = ['error', 'active']


def nova_hypervisors(auth, details=False):
    path = '/os-hypervisors/detail' if details else '/os-hypervisors'
    response = requests.get(
        url=auth.endpoint('compute') + path,
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    data = response.json()
    return {h['id']: h for h in data['hypervisors']}


def nova_instance(auth, id):
    response = requests.get(
        url=auth.endpoint('compute') + '/servers/{}'.format(id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    server = response.json()['server']
    return server


def nova_instances(auth, **params):
    default_params = {'all_tenants': 1}
    default_params.update(params)

    response = requests.get(
        url=auth.endpoint('compute') + '/servers',
        params=default_params,
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    servers = response.json()['servers']
    servers = {s['id']: s for s in servers}
    return servers


def nova_instances_details(auth, **params):
    default_params = {'all_tenants': 1}
    default_params.update(params)

    response = requests.get(
        url=auth.endpoint('compute') + '/servers/detail',
        params=default_params,
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    servers = response.json()['servers']
    servers = {s['id']: s for s in servers}
    return servers


def nova_reset_state(auth, id, state='error'):
    if state not in RESET_STATES:
        raise ValueError('cannot reset state to \'{}\', not one of {}'.format(state, RESET_STATES))


def nova_aggregates(auth):
    response = requests.get(
        url=auth.endpoint('compute') + '/os-aggregates',
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    aggregates = response.json()['aggregates']
    aggregates = {int(a['id']): a for a in aggregates}
    return aggregates


def nova_aggregate_details(auth, agg_id):
    response = requests.get(
        url=auth.endpoint('compute') + '/os-aggregates/{}'.format(agg_id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    return response.json()['aggregate']


def nova_aggregate_delete(auth, agg_id):
    if int(agg_id) == FREEPOOL_AGGREGATE_ID:
        raise RuntimeError('nope. (this is the freepool aggregate...bad idea.)')

    response = requests.delete(
        url=auth.endpoint('compute') + '/os-aggregates/{}'.format(agg_id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    return response


def _addremove_host(auth, mode, agg_id, host_id):
    if mode not in ['add_host', 'remove_host']:
        raise ValueError('invalid mode')

    response = requests.post(
        url=auth.endpoint('compute') + '/os-aggregates/{}/action'.format(agg_id),
        headers={'X-Auth-Token': auth.token},
        json={
            mode: {
                'host': host_id
            }
        }
    )
    response.raise_for_status()
    return response.json()['aggregate']


def nova_aggregate_add_host(auth, agg_id, host_id):
    return _addremove_host(auth, 'add_host', agg_id, host_id)


def nova_aggregate_remove_host(auth, agg_id, host_id, verify=True):
    if verify:
        agg = nova_aggregate_details(auth, agg_id)
        if host_id not in agg['hosts']:
            raise RuntimeError("host '{}' is not in aggregate '{}'".format(host_id, agg_id))
    return _addremove_host(auth, 'remove_host', agg_id, host_id)


def nova_aggregate_move_host(auth, host_id, from_agg_id, to_agg_id):
    nova_aggregate_remove_host(auth, from_agg_id, host_id)
    return nova_aggregate_add_host(auth, to_agg_id, host_id)


def nova_availabilityzones(auth):
    response = requests.get(
        url=auth.endpoint('compute') + '/os-availability-zone/detail',
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    zones = response.json()[u'availabilityZoneInfo']
    return zones
