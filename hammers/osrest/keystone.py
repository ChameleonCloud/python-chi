import requests


def keystone_project(auth, id):
    response = requests.get(
        url=auth.endpoint('identityv3') + '/projects/{}'.format(id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    project = response.json()['project']
    return project


def keystone_projects(auth, **params):
    """
    Example params: 'name', 'enabled', or stuff from
    https://developer.openstack.org/api-ref/identity/v3/?expanded=list-projects-detail#list-projects
    """
    response = requests.get(
        url=auth.endpoint('identityv3') + '/projects'.format(id),
        headers={'X-Auth-Token': auth.token},
        params=params,
    )
    response.raise_for_status()
    projects = response.json()['projects']
    projects = {p['id']: p for p in projects}
    return projects


def keystone_project_lookup(auth, name_or_id):
    try:
        return keystone_project(auth, name_or_id)
    except requests.HTTPError:
        pass # failed lookup assuming it was an id, must be a name?

    projects = keystone_projects(auth, name=name_or_id)
    if len(projects) < 1:
        raise RuntimeError('no projects found')
    elif len(projects) > 1:
        raise RuntimeError('multiple projects matched provided name')

    id, project = projects.popitem()
    return project


def keystone_user(auth, id):
    response = requests.get(
        url=auth.endpoint('identityv3') + '/users/{}'.format(id),
        headers={'X-Auth-Token': auth.token},
    )
    response.raise_for_status()
    user = response.json()['user']
    return user


def keystone_users(auth, enabled=None, name=None):
    params = {}
    if name is not None:
        params['name'] = name
    if enabled is not None:
        params['enabled'] = enabled

    response = requests.get(
        url=auth.endpoint('identityv3') + '/users',
        headers={'X-Auth-Token': auth.token},
        params=params,
    )
    response.raise_for_status()
    users = response.json()['users']
    users = {u['id']: u for u in users}
    return users


def keystone_user_lookup(auth, name_or_id):
    try:
        return keystone_user(auth, name_or_id)
    except requests.HTTPError:
        pass # failed lookup assuming it was an id, must be a name?

    users = keystone_users(auth, name=name_or_id)
    if len(users) < 1:
        raise RuntimeError('no users found')
    elif len(users) > 1:
        raise RuntimeError('multiple users matched provided name')

    id, user = users.popitem()
    return user
