from .clients import neutron

from neutronclient.common.exceptions import NotFound

__all__ = [
    'get_network_id',
    'create_network',
    'delete_network',
    'update_network',
    'list_networks',
    'show_network',
    'show_network_by_name',

    'get_subnet_id',
    'create_subnet',
    'delete_subnet',
    'update_subnet',
    'list_subnets',
    'show_subnet',
    'show_subnet_by_name',

    'get_port_id',
    'create_port',
    'update_port',
    'delete_port',
    'list_ports',
    'show_port',
    'show_port_by_name',

    'get_router_id',
    'create_router',
    'delete_router',
    'update_router',
    'list_routers',
    'show_router',
    'show_router_by_name',

    'add_route_to_router',
    'remove_routes_from_router',
    'remove_all_routes_from_router',
    'remove_route_from_router',
    'add_port_to_router',
    'add_port_to_router_by_name',
    'add_subnet_to_router',
    'add_subnet_to_router_by_name',
    'remove_subnet_from_router',
    'remove_port_from_router',

    'get_free_floating_ip',
    'get_floating_ip',
    'associate_floating_ip',
    'detach_floating_ip',
    'list_floating_ips',

    'nuke_network',
    'chi_wizard_create_network',
    'chi_wizard_delete_network',
]

PUBLIC_NETWORK = 'public'


def _resolve_id(resource, name):
    list_fn = getattr(neutron(), f'list_{resource}', None)
    if not callable(list_fn):
        raise ValueError(f'Invalid resource type "{resource}"')
    resources = [
        x for x in list_fn()[resource]
        if x['name'] == name
    ]
    if not resources:
        raise RuntimeError(f'No {resource} found with name {name}')
    elif len(resources) > 1:
        raise RuntimeError(f'Found multiple {resource} with name {name}')
    return resources[0]['id']


def _resolve_resource(resource, name_or_id):
    get_fn = getattr(neutron(), f'get_{resource}', None)
    if not callable(get_fn):
        raise ValueError(f'Invalid resource type "{resource}"')
    try:
        return get_fn(name_or_id)
    except NotFound:
        resource_id = _resolve_id(f'{resource}s', name_or_id)
        return get_fn(resource_id)


###########
# Networks
###########

def get_network(ref):
    return _resolve_resource('network', ref)


def get_network_id(name):
    return _resolve_id('networks', name)


def create_network(network_name, of_controller_ip=None, of_controller_port=None,
                   vswitch_name=None, provider='physnet1', port_security_enabled=True):
    """Create a network.

    For an OpenFlow network include the IP and port of an OpenFlow controller
    on Chameleon or accessible through the public Internet. Include a virtual
    switch name if you plan to add additional private VLANs to this switch.
    Additional VLANs can be connected using a dedicated port corresponding to
    the VLAN tag and can be conrolled using a valid OpenFlow controller.

    Args:
        network_name (str): the name of the new network.
        of_controller_ip (str): the IP of the optional OpenFlow controller.
            The IP must be accessible on the public Internet.
        of_controller_port (str): the port of the optional OpenFlow controller.
        vswitch_name (str): the name of the virtual switch to use.
        provider (str): the provider network to use when specifying stitchable
            VLANs (i.e. ExoGENI). Default: 'physnet1'
    """
    desc_parts = []
    if of_controller_ip and of_controller_port:
        desc_parts.append(f'OFController={of_controller_ip}:{of_controller_port}')
    if vswitch_name != None:
        desc_parts.append(f'VSwitchName={vswitch_name}')

    network = neutron().create_network(body={
        'network': {
            'name': network_name,
            'description': ','.join(desc_parts),
            'provider:physical_network': provider,
            'provider:network_type': 'vlan',
            'port_security_enabled': port_security_enabled,
        }
    })

    return network['network']


def delete_network(network_id):
    return neutron().delete_network(network_id)


def update_network(network_id):
    raise NotImplementedError()


def list_networks():
    return neutron().list_networks()


def show_network(network_id):
    return neutron().show_network(network_id)


def show_network_by_name(network_name):
    return show_network(get_network_id(network_name))


##########
# Subnets
##########

def get_subnet(ref):
    return _resolve_resource('subnets', ref)


def get_subnet_id(name):
    return _resolve_id('subnets', name)


def create_subnet(subnet_name, network_id, cidr='192.168.1.0/24',
                  gateway_ip=None):
    subnet = {
        'name': subnet_name,
        'cidr': cidr,
        'ip_version': 4,
        'network_id': network_id,
    }
    if gateway_ip:
        subnet['gateway_ip'] = gateway_ip

    subnet = neutron().create_subnet(body={
        'subnets': [
            {
                'name': subnet_name,
                'cidr': cidr,
                'ip_version': 4,
                'network_id': network_id,
            }
        ]
    })

    return subnet


def delete_subnet(subnet_id):
    return neutron().delete_subnet(subnet_id)


def update_subnet(subnet_id):
    raise NotImplementedError()


def list_subnets():
    return neutron().list_subnets()


def show_subnet(subnet_id):
    return neutron().show_subnet(subnet_id)


def show_subnet_by_name(name):
    return show_subnet(get_subnet_id(name))


########
# Ports
########

def get_port(ref):
    return _resolve_resource('port', ref)


def get_port_id(name):
    return _resolve_id('ports', name)


def create_port(port_name, network_id, subnet_id=None, ip_address=None,
               port_security_enabled=True):
    port = {
        'name': port_name,
        'network_id': network_id,
        'port_security_enabled': port_security_enabled,
    }

    if subnet_id != None:
        fixed_ip = {
            'subnet_id': subnet_id,
        }
        if ip_address != None:
            fixed_ip['ip_address'] = ip_address
        port['fixed_ips'] = [fixed_ip]

    return neutron().create_port(body={'port': port})


def update_port(port_id, subnet_id=None, ip_address=None):
    raise NotImplementedError()


def delete_port(port_id):
    return neutron().delete_port(port_id)


def list_ports():
    return neutron().list_ports()


def show_port(port_id):
    return neutron().show_port(port_id)


def show_port_by_name(port_name):
    return show_port(get_port_id(port_name))


##########
# Routers
##########

def get_router(ref):
    return _resolve_resource('router', ref)


def get_router_id(name):
    return _resolve_id('routers', name)


def create_router(router_name, gw_network_name=None):
    '''
    Create a router with or without a public gateway.

    Args:
        router_name (str): name of the new router.
        gw_network_name (str): name of the external gateway network (i.e.,
            the network that connects to the Internet). Chameleon's gateway
            network is 'public'. Default: None
    '''
    router = {
        'name': router_name,
        'admin_state_up': True,
    }

    if gw_network_name:
        public_net_id = get_network_id(gw_network_name)
        router['external_gateway_info'] = {'network_id': public_net_id}

    router = neutron().create_router(body=router)
    return router


def delete_router(router_id):
    return neutron().delete_router(router_id)


def update_router(router_id):
    raise NotImplementedError()


def list_routers():
    return neutron().list_routers()


def show_router(router_id):
    return neutron().show_router(router_id)


def show_router_by_name(router_name):
    return show_router(get_router_id(router_name))


####################
# Router operations
####################

def add_route_to_router(router_id, cidr, nexthop):
    return neutron().add_extra_routes_to_router(router_id, {
        'router': {
            'routes' : [
                {'destination': cidr, 'nexthop': nexthop}
            ]
        }
    })


def remove_routes_from_router(router_id, routes):
    return neutron().remove_extra_routes_from_router(router_id, {
        'router': {
            'routes': routes
        }
    })


def remove_all_routes_from_router(router_id):
    return remove_routes_from_router(router_id,
        show_router(router_id)['routes'])


def remove_route_from_router(router_id, cidr, nexthop):
    return neutron().remove_extra_routes_from_router(router_id, {
        'router': {
            'routes': [
                {'destination': cidr, 'nexthop': nexthop}
            ]
        }
    })


def add_port_to_router(router_id, port_id):
    return neutron().add_interface_router(router_id, {'port_id': port_id})


def add_port_to_router_by_name(router_name, port_name):
    router_id = get_router_id(router_name)
    port_id = get_port_id(port_name)
    return add_port_to_router(router_id, port_id)


def add_subnet_to_router(router_id, subnet_id):
    return neutron().add_interface_router(router_id, {
        'subnet_id': subnet_id
    })


def add_subnet_to_router_by_name(router_name, subnet_name):
    router_id = get_router_id(router_name)
    subnet_id = get_subnet_id(subnet_name)
    return add_subnet_to_router(router_id, subnet_id)


def remove_subnet_from_router(router_id, subnet_id):
    return neutron().remove_interface_router(router_id, {
        'subnet_id': subnet_id
    })


def remove_port_from_router(router_id, port_id):
    return neutron().remove_interface_router(router_id, {
        'port_id': port_id
    })


###############
# Floating IPs
###############

def get_free_floating_ip():
    ips = neutron().list_floatingips()['floatingips']
    unbound_fip = next(iter([ip for ip in ips if ip['port_id'] is None]), None)
    if not unbound_fip:
        raise ValueError('No free floating IP found')
    return unbound_fip


def get_or_create_floating_ip():
    try:
        fip = get_free_floating_ip()
        created = False
    except Exception:
        network_id = get_network_id(PUBLIC_NETWORK)
        fip = neutron().create_floatingip({
            'floatingip': {
                'floating_network_id': network_id
            }
        })['floatingip']
        created = True
        print(f'Allocated new floating IP {fip["floating_ip_address"]}')
    return fip, created


def get_floating_ip(ip_address):
    fip = next(iter([
        fip for fip in list_floating_ips()
        if fip['floating_ip_address'] == ip_str
    ]), None)
    if not fip:
        raise ValueError(f'No floating IP with address {ip_address} found')
    return fip


def list_floating_ips():
    return neutron().list_floatingips()['floatingips']


###################
# Wizard functions
###################

def nuke_network(network_name):
    network_id = get_network_id(network_name)

    # Detach network's subnets from router
    port = next(iter([
        p for p in list_ports()
        if (p['device_owner'] == 'network:router_interface' and
            p['network_id'] == network_id)
    ]), None)
    router_id = port['device_id'] if port else None
    if router_id:
        for fixed_ip in port['fixed_ips']:
            subnet_id = fixed_ip['subnet_id']
            remove_subnet_from_router(router_id, fixed_ip['subnet_id'])
            print(f'Detached subnet {subnet_id}')
        delete_router(router_id)
        print(f'Deleted router {router_id}')

    # TODO: also detach any running instances (?)

    # Delete all subnets
    for subnet in list_subnets():
        if subnet['network_id'] == network_id:
            subnet_id = subnet['id']
            delete_subnet(subnet_id)
            print(f'Deleted subnet {subnet_id}')

    delete_network(network_id)
    print(f'Deleted network {network_id}')


def chi_wizard_create_network(name, of_controller_ip=None,
                              of_controller_port=None):
    name_prefix = name
    network_name = name_prefix + 'Net'
    vswitch_name = name_prefix + 'VSwitch'
    router_name = name_prefix + 'Router'
    subnet_name = name_prefix + 'Subnet'
    provider = 'physnet1'

    network = create_network(network_name, of_controller_ip=of_controller_ip,
                             of_controller_port=of_controller_port,
                             vswitch_name=vswitch_name, provider=provider)
    subnet = create_subnet(subnet_name, network['id'])
    router = create_router(router_name, network_name)
    add_subnet_to_router(router['id'], subnet['id'])

    return network


def chi_wizard_delete_network(name):
    return nuke_network(name + 'Net')
