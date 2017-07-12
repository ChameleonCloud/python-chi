import requests


def blazar_leases(auth):
    response = requests.get(
        url=auth.endpoint('reservation') + '/leases',
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    leases = response.json()['leases']
    leases = {l['id']: l for l in leases}
    return leases


def blazar_lease(auth, lease_id):
    response = requests.get(
        url=auth.endpoint('reservation') + '/leases/{}'.format(lease_id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    return response.json()['lease']


def blazar_lease_delete(auth, lease_id):
    response = requests.delete(
        url=auth.endpoint('reservation') + '/leases/{}'.format(lease_id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    return response
