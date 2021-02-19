from .clients import neutron

from neutronclient.common.exceptions import NotFound

import json

__all__ = [
    'get_network',
    'get_network_id',
    'create_network',
    'delete_network',
    'update_network',
    'list_networks',

    'get_subnet',
    'get_subnet_id',
    'create_subnet',
    'delete_subnet',
    'update_subnet',
    'list_subnets',

    'get_port',
    'get_port_id',
    'create_port',
    'update_port',
    'delete_port',
    'list_ports',

    'get_router',
    'get_router_id',
    'create_router',
    'delete_router',
    'update_router',
    'list_routers',

    'add_route_to_router',
    'add_routes_to_router',
    'remove_route_from_router',
    'remove_routes_from_router',
    'remove_all_routes_from_router',
    'add_port_to_router',
    'add_port_to_router_by_name',
    'add_subnet_to_router',
    'add_subnet_to_router_by_name',
    'remove_subnet_from_router',
    'remove_port_from_router',

    'get_free_floating_ip',
    'get_floating_ip',
    'list_floating_ips',

    'nuke_network',
]

PUBLIC_NETWORK = 'public'


def _resolve_id(resource, name) -> str:
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


def _resolve_resource(resource, name_or_id) -> dict:
    get_fn = getattr(neutron(), f'show_{resource}', None)
    if not callable(get_fn):
        raise ValueError(f'Invalid resource type "{resource}"')
    try:
        res = get_fn(name_or_id)
    except NotFound:
        resource_id = _resolve_id(f'{resource}s', name_or_id)
        res = get_fn(resource_id)
    # Unwrap nested structure
    return res.get(resource)


###########
# Networks
###########

def get_network(ref) -> dict:
    """Get a network by its name or ID.

    Args:
        ref (str): The name or ID of the network.

    Returns:
        The network representation.

    Raises:
        RuntimeError: If the network could not be found, or multiple networks
            were returned for the search term.
    """
    return _resolve_resource('network', ref)


def get_network_id(name) -> str:
    """Look up a network's ID from its name.

    Args:
        name (str): The network name.

    Returns:
        The network's ID, if found.

    Raises:
        RuntimeError: If the network could not be found, or multiple networks
            were returned for the search term.
    """
    return _resolve_id('networks', name)


def create_network(network_name, of_controller_ip=None, of_controller_port=None,
                   vswitch_name=None, provider='physnet1',
                   port_security_enabled=True) -> dict:
    """Create a network.

    For an OpenFlow network include the IP and port of an OpenFlow controller
    on Chameleon or accessible through the public Internet. Include a virtual
    switch name if you plan to add additional private VLANs to this switch.
    Additional VLANs can be connected using a dedicated port corresponding to
    the VLAN tag and can be conrolled using a valid OpenFlow controller.

    Args:
        network_name (str): The new network name.
        of_controller_ip (str): the IP of the optional OpenFlow controller.
            The IP must be accessible on the public Internet.
        of_controller_port (str): the port of the optional OpenFlow controller.
        vswitch_name (str): The virtual switch to use name.
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
    """Delete the network.

    .. note::
       This does not perform a full teardown of the network, including removing
       subnets and ports. It will only succeed if the network does not have
       any attached entities. See :func:`nuke_network` for a more complete
       teardown function.

    Args:
        network_id (str): The network ID.
    """
    return neutron().delete_network(network_id)


def update_network(network_id):
    raise NotImplementedError()


def list_networks() -> 'list[dict]':
    """List all networks associated with the current project.

    Returns:
        A list of all the found networks.
    """
    return neutron().list_networks()["networks"]


##########
# Subnets
##########

def get_subnet(ref) -> dict:
    """Get a subnet by its name or ID.

    Args:
        ref (str): The name or ID of the subnet.

    Returns:
        The subnet representation.

    Raises:
        RuntimeError: If the subnet could not be found, or multiple subnets
            were returned for the search term.
    """
    return _resolve_resource('subnet', ref)


def get_subnet_id(name) -> str:
    """Look up a subnet's ID from its name.

    Args:
        name (str): The subnet name.

    Returns:
        The subnet's ID, if found.

    Raises:
        RuntimeError: If the subnet could not be found, or multiple subnets
            were returned for the search term.
    """
    return _resolve_id('subnets', name)


def create_subnet(subnet_name, network_id, cidr='192.168.1.0/24',
                  gateway_ip=None) -> dict:
    """Create a subnet on a network.

    Args:
        subnet_name (str): The name to give the new subnet.
        network_id (str): The network to associate the subnet with ID.
        cidr (str): The subnet's IPv4 CIDR range. (Default 192.168.1.0/24)
        gateway_ip (str): The subnet's gateway address. If not defined,
            the first address in the subnet will be automatically chosen as
            the gateway.

    Returns:
        The new subnet representation.
    """
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

    return subnet['subnets'][0]


def delete_subnet(subnet_id):
    """Delete the subnet.

    Args:
        subnet_id (str): The subnet ID.
    """
    return neutron().delete_subnet(subnet_id)


def update_subnet(subnet_id):
    raise NotImplementedError()


def list_subnets() -> 'list[dict]':
    """List all subnets associated with the current project.

    Returns:
        A list of all the found subnets.
    """
    return neutron().list_subnets()["subnets"]


########
# Ports
########

def get_port(ref) -> dict:
    """Get a port by its name or ID.

    Args:
        ref (str): The name or ID of the port.

    Returns:
        The port representation.

    Raises:
        RuntimeError: If the port could not be found, or multiple ports
            were returned for the search term.
    """
    return _resolve_resource('port', ref)


def get_port_id(name) -> str:
    """Look up a port's ID from its name.

    Args:
        name (str): The port name.

    Returns:
        The port's ID, if found.

    Raises:
        RuntimeError: If the port could not be found, or multiple ports
            were returned for the search term.
    """
    return _resolve_id('ports', name)


def create_port(port_name, network_id, subnet_id=None, ip_address=None,
               port_security_enabled=True) -> dict:
    """Create a new port on a network.

    Args:
        port_name (str): The name to give the new port.
        network_id (str): The ID of the network that the port will be
            connected to.
        subnet_id (str): The ID of the subnet that the port will be allocated
            on. The port will be automatically assigned an IP address on this
            subnet, unless the ``ip_address`` parameter is provided.
        ip_address (str): The IP address to assign the port, if a specific
            IP address is desired. By default an IP address is automatically
            picked from the target subnet.
        port_security_enabled (bool): Whether to enable `port security
            <https://wiki.openstack.org/wiki/Neutron/ML2PortSecurityExtensionDriver>`_.
            In general this should be kept on. (Default True).

    Returns:
        The created port representation.
    """
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
    """Delete the port.

    Args:
        port_id (str): The port ID.
    """
    return neutron().delete_port(port_id)


def list_ports() -> 'list[dict]':
    """List all ports associated with the current project.

    Returns:
        A list of all the found ports.
    """
    return neutron().list_ports()["ports"]


##########
# Routers
##########

def get_router(ref) -> dict:
    """Get a router by its name or ID.

    Args:
        ref (str): The name or ID of the router.

    Returns:
        The router representation.

    Raises:
        RuntimeError: If the router could not be found, or multiple routers
            were returned for the search term.
    """
    return _resolve_resource('router', ref)


def get_router_id(name) -> str:
    """Look up a router's ID from its name.

    Args:
        name (str): The router name.

    Returns:
        The router's ID, if found.

    Raises:
        RuntimeError: If the router could not be found, or multiple routers
            were returned for the search term.
    """
    return _resolve_id('routers', name)


def create_router(router_name, gw_network_name=None) -> dict:
    """Create a router, with or without a public gateway.

    Args:
        router_name (str): The new router name.
        gw_network_name (str): The name of the public gateway requested to
            provide subnets connected this router NAT to the Internet.
    Returns:
        The created router representation.
    """
    router = {"name": router_name, "admin_state_up": True}

    if gw_network_name:
        router["external_gateway_info"] = {"network_id": get_network_id(gw_network_name)}

    response = neutron().create_router(body={"router": router})
    return response["router"]


def delete_router(router_id):
    """Delete the router.

    Args:
        router_id (str): The router ID.
    """
    return neutron().delete_router(router_id)


def update_router(router_id):
    raise NotImplementedError()


def list_routers() -> 'list[dict]':
    """List all routers associated with the current project.

    Returns:
        A list of all the found routers.
    """
    return neutron().list_routers()["routers"]


####################
# Router operations
####################

def add_route_to_router(router_id, cidr, nexthop):
    """Add a new route to a router.

    Args:
        router_id (str): The router ID.
        cidr (str): The destination subnet CIDR for the route.
        nexthop (str): The nexthop address for the route.
    """
    return add_routes_to_router(router_id, [
        {'destination': cidr, 'nexthop': nexthop}
    ])


def add_routes_to_router(router_id, routes):
    """Add a set of routes to a router.

    Args:
        router_id (str): The router ID.
        routes (list[dict]): A list of routes to add. The list is expected
            to consist of items with a 'destination' and 'nexthop' key, e.g.:

            .. code-block:: python

                [
                   {'destination': '10.0.0.0/24', 'nexthop': '10.0.0.1'},
                   {'destination': '10.0.1.0/24', 'nexthop': '10.0.1.1'}
                ]

    """
    return neutron().add_extra_routes_to_router(router_id, {
        'router': {'routes': routes}
    })


def remove_route_from_router(router_id, cidr, nexthop):
    """Remove a single route from the router.

    Args:
        router_id (str): The router ID.
        cidr (str): The destination subnet CIDR for the route.
        nexthop (str): The nexthop address for the route.
    """
    return remove_routes_from_router(router_id, [
        {'destination': cidr, 'nexthop': nexthop}
    ])


def remove_routes_from_router(router_id, routes):
    """Remove a set of routes from a router.

    Args:
        router_id (str): The router ID.
        routes (list[dict]): A list of routes to remove. The list is expected
            to consist of items with a 'destination' and 'nexthop' key, e.g.:

            .. code-block:: python

                [
                   {'destination': '10.0.0.0/24', 'nexthop': '10.0.0.1'},
                   {'destination': '10.0.1.0/24', 'nexthop': '10.0.1.1'}
                ]

    """
    return neutron().remove_extra_routes_from_router(router_id, {
        'router': {
            'routes': routes
        }
    })


def remove_all_routes_from_router(router_id):
    """Remove all routes from the router.

    Args:
        router_id (str): The router ID.
    """
    return remove_routes_from_router(router_id,
        get_router(router_id)['routes'])


def add_port_to_router(router_id, port_id):
    """Add a port to a router.

    Args:
        router_id (str): The router ID.
        port_id (str): The port ID.
    """
    return neutron().add_interface_router(router_id, {'port_id': port_id})


def add_port_to_router_by_name(router_name, port_name):
    """Add a port to a router, referencing the router and port by name.

    Args:
        router_name (str): The router name.
        port_name (str): The port name.
    """
    router_id = get_router_id(router_name)
    port_id = get_port_id(port_name)
    return add_port_to_router(router_id, port_id)


def remove_port_from_router(router_id, port_id):
    """Remove a port from the router.

    Args:
        router_id (str): The router ID.
        port_id (str): The port ID.
    """
    return neutron().remove_interface_router(router_id, {'port_id': port_id})


def add_subnet_to_router(router_id, subnet_id):
    """Add a subnet to a router.

    Args:
        router_id (str): The router ID.
        subnet_id (str): The subnet ID.
    """
    return neutron().add_interface_router(router_id, {'subnet_id': subnet_id})


def add_subnet_to_router_by_name(router_name, subnet_name):
    """Add a subnet to a router, referencing the router and subnet by name.

    Args:
        router_name (str): The router name.
        subnet_name (str): The subnet name.
    """
    router_id = get_router_id(router_name)
    subnet_id = get_subnet_id(subnet_name)
    return add_subnet_to_router(router_id, subnet_id)


def remove_subnet_from_router(router_id, subnet_id):
    """Remove a subnet from the router.

    Args:
        router_id (str): The router ID.
        subnet_id (str): The subnet ID.
    """
    return neutron().remove_interface_router(router_id, {
        'subnet_id': subnet_id
    })


###############
# Floating IPs
###############

def get_free_floating_ip() -> dict:
    """Get the first unallocated floating IP available to your project.

    Returns:
        The free floating IP representation.
    """
    ips = neutron().list_floatingips()['floatingips']
    unbound = (ip for ip in ips if ip['port_id'] is None)
    try:
        fip = next(unbound)
        return fip
    except StopIteration:
        raise Exception("No free floating IP found")


def get_or_create_floating_ip() -> 'tuple[dict,bool]':
    """Get the first unallocated floating IP or allocate one to the project.

    Returns:
        A tuple of the floating IP representation, and a boolean indicating
            whether the IP was dynamically allocated to the project.

    Raises:
        Conflict: If there are no free floating IPs and there are no more
            available to allocate.
    """
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


def get_floating_ip(ip_address) -> dict:
    """Get the floating IP representation for an IP address.

    Args:
        ip_address (str): The IP address of the floating IP.

    Returns:
        The floating IP representation.
    """
    ips = neutron().list_floatingips()['floatingips']

    for fip in ips:
        if fip['floating_ip_address'] == ip_address:
            return fip
    raise Exception(f"Floating IP {ip_address} not found")


def list_floating_ips() -> 'list[dict]':
    """List all floating ips associated with the current project.

    Returns:
        A list of all the found floating ips.
    """
    return neutron().list_floatingips()["floatingips"]


def nuke_network(network_name):
    """Completely tear down the network.

    Cleanly tearing down an OpenStack network representation involves a few
    separate steps:

    1. Detach the network's subnets from the router.
    2. Delete the router.
    3. Delete the subnet(s).
    4. Delete the network.

    This function performs all of those steps for you.

    .. note::

       This function will not work well for very advance networks, perhaps
       those connected to multiple routers. You should perform your own cleanup
       if your network's subnets are attached to multiple routers.

    Args:
        network_name (str): The network name.
    """
    network = get_network(network_name)
    network_id = network["id"]

    #Detach the router from all of its networks
    router_ports = [
        port for port in neutron().list_ports()["ports"]
        if port["device_owner"] == "network:router_interface" and port["network_id"] == network_id
    ]

    for port in router_ports:
        for fixed_ip in port["fixed_ips"]:
            router_id = port["device_id"]
            remove_subnet_from_router(router_id, fixed_ip["subnet_id"])

    #Delete the router
    for port in router_ports:
        delete_router(port["device_id"])

    #Delete the subnet
    for subnet in neutron().list_subnets()['subnets']:
        if subnet['network_id'] == network_id:
            subnet_id=subnet['id']
            delete_subnet(subnet_id)

    #Delete the network
    delete_network(network_id)


###################
# Wizard functions
###################

class wizard(object):
    """A collection of "wizard" functions.

    These utility functions are very opinionated but can reduce boilerplate.
    """

    @staticmethod
    def create_network(name_prefix, of_controller_ip=None,
                       of_controller_port=None, gateway=False):
        """Create a network and subnet, and connect the subnet to a new router.

        Args:
            name_prefix (str): The common name prefix for all created entities.
            of_controller_ip (str): The OpenFlow controller IP, if using.
            of_controller_port (int): The OpenFlow controller port, if using.
            gateway (bool): Whether to add a WAN gateway to the router. Routers
                with a WAN gateway are able to NAT to the Internet.

        Returns:
            The created network representation.
        """
        network_name = f'{name_prefix}Net'
        vswitch_name = f'{name_prefix}VSwitch'
        router_name = f'{name_prefix}Router'
        subnet_name = f'{name_prefix}Subnet'
        network = create_network(
            network_name,
            of_controller_ip=of_controller_ip,
            of_controller_port=of_controller_port,
            vswitch_name=vswitch_name,
            provider='physnet1'
        )
        subnet = create_subnet(subnet_name, network['id'])
        router = create_router(router_name, gateway=gateway)
        add_subnet_to_router(router['id'], subnet['id'])

        return network

    @staticmethod
    def delete_network(name_prefix):
        """Delete a network created via :func:``wizard.create_network``.

        Args:
            name_prefix (str): The common name prefix for all created entities.
        """
        return nuke_network(f'{name_prefix}Net')
