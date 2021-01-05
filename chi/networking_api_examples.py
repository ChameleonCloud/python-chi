import chi
import json
import os
from chi.util import get_public_network

def get_network_id(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    network=None
    for n in chi.neutron().list_networks()['networks']:
        if n['name'] == name:
            if network != None:
                raise RuntimeError('Found multiple networks with name ' + str(name))
            network = n
            
    if network == None:
        raise RuntimeError('Network not found. name: ' + str(name))
        
    return network['id']

def get_router_id(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    router=None
    for r in chi.neutron().list_routers()['routers']:
        if r['name'] == name:
            if router != None:
                raise RuntimeError('Found multiple routers with name ' + str(name))
            router = r
    
    if router == None:
        raise RuntimeError('Router not found. name: ' + str(name))
    
    return router['id']

def get_subnet_id(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    subnet=None
    for s in chi.neutron().list_subnets()['subnets']:
        if s['name'] == name:
            if subnet != None:
                raise RuntimeError('Found multiple subnets with name ' + str(name))
            subnet = s
             
    if subnet == None:
        raise RuntimeError('Subnet not found. name: ' + str(name))
                                
    return subnet['id']

def get_port_id(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    port=None
    for p in chi.neutron().list_ports()['ports']:
        if p['name'] == name:
            if port != None:
                raise RuntimeError('Found multiple ports with name ' + str(name))
            port = p
             
    if port == None:
        raise RuntimeError('Port not found. name: ' + str(name))
                                
    return port['id']


def create_network(network_name, of_controller_ip=None, of_controller_port=None, vswitch_name=None, provider="physnet1",port_security_enabled='true'):
    ''' 
    Create a network. For an OpenFlow network include the IP and port of an OpenFlow controller on Chameleon or accessible through the public Internet. Include a virtual switch name if you plan to add additional private VLANs to this switch. Additional VLANs can be connected using a dedicated port corisponding the the VLAN tag and can be conrolled using a valid OpenFlow controller.  
    
    Parameters
    ----------
    network_name : str
        The name of the new network.
    of_controller_ip : str
        The IP of the optional OpenFlow controller. The IP must be accessible on the public Internet.
    of_controller_port : str
        The port of the optional OpenFlow controller.
    vswitch_name : str
        The name of the virtual switch to use.
    provider : str
        The povider network to use when specifying stitchable VLANs (i.e. exogen). Default: 'physnet1'
    '''
    description=''
    if of_controller_ip != None and of_controller_port != None:
        description = description + 'OFController=' + of_controller_ip + ':' + of_controller_port 
        
    if vswitch_name != None and of_controller_ip != None and of_controller_port != None:
        description = description + ','
    
    if vswitch_name != None:
        description = description + 'VSwitchName=' + vswitch_name
    
    body_sample = {'network': {'name': network_name,
                               "provider:physical_network": provider,
                               "provider:network_type": "vlan",
                               "description": description,
                               "port_security_enabled": port_security_enabled
                              }}

    network = chi.neutron().create_network(body=body_sample)
    return network['network']

def delete_network(network_id):
    return chi.neutron().delete_network(network_id) 
    pass

def update_network(network_id):
    pass

def list_networks():
    return chi.neutron().list_networks() 
    

def show_network(network_id):
    return chi.neutron().show_network(network_id) 

def show_network_by_name(network_name):
    return show_network(get_network_id(network_name=network_name)) 


def create_port(port_name, network_id, subnet_id=None, ip_address=None, port_security_enabled='true'):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    network = show_network(network_id=network_id)
    
    #print(json.dumps(network, indent=2))
    #print('network_id' + network_id + '\n')
    #print(json.dumps(subnet, indent=2))
    #print('subnet_id ' + subnet_id + '\n')

    body_port={}
    
    port={}
    port['name']=port_name
    port['network_id']=network_id
    port['port_security_enabled']=port_security_enabled
    
    if subnet_id != None:
        fixed_ip={}
        fixed_ip['subnet_id']=subnet_id
        if ip_address != None:
            fixed_ip['ip_address']=ip_address
        port['fixed_ips']=[ fixed_ip ]

    body_port['port']=port 
    
    #body_port = {'port': {    'name': port_name,
    #                          'network_id': network_id,
    #                          'fixed_ips': [{
    #                                            'ip_address': ip_address,
    #                                            'subnet_id': subnet_id
    #                                       }]
    #
    #                     }
    #            }
    
    port = chi.neutron().create_port(body=body_port)
    return port
    
def update_port(port_id, subnet_id=None, ip_address=None):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    #port=get_port_by_name(name=port_name)
    #port_id=port['id']
    #print(json.dumps(port, indent=2))
    #print('port_id ' + port_id + '\n')
    
    #subnet=get_subnet_by_name(name=subnet_name)
    #subnet_id=subnet['id']   
    
    #print(json.dumps(subnet, indent=2))
    #print('subnet_id ' + subnet_id + '\n')
    
    #body_port={}
    
    #port={}
    #port['name']='newName'
        
    #if subnet_name != None:
    #    subnet=get_subnet_by_name(name=subnet_name)
    #    subnet_id=subnet['id']   
    #    
    #    fixed_ip={}
    #    fixed_ip['subnet_id']=subnet_id
    #    if ip_address != None:
    #        fixed_ip['ip_address']=ip_address
    #    port['fixed_ips']=[ fixed_ip ]

    body_port={ 'port': port }  


    #Update port    
    #body_port = {'port': {    'name': port_name,
    #                                   "fixed_ips": [
    #                                         {
    #                                            #"ip_address": "192.168.111.4",
    #                                            "subnet_id": subnet_id
    #                                         }
    #                                    ]
    #                      }
    #            }
    port = chi.neutron().update_port(port=port_id,body=body_port)
    return port['id']

def delete_port(port_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    port = chi.neutron().delete_port(port=port_id)

def list_ports():
    return chi.neutron().list_ports() 

def show_port(port_id):
    return chi.neutron().show_port(port_id) 

def show_port_by_name(port_name):
    return show_port(get_port_id(port_name=port_name)) 
    
    
    
def create_subnet(subnet_name, network_id, cidr='192.168.1.0/24', gateway_ip=None):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    #network=get_network_by_name(name=network_name)
    #network_id=network['id']

    subnet={}
    subnet['cidr']=cidr
    subnet['ip_version']=4
    subnet['network_id']=network_id
    subnet['name']=subnet_name
    if gateway_ip:
        subnet['gateway_ip']=gateway_ip
    
    #Add Subnet
    body_create_subnet = {'subnets': [ subnet ] }
    subnet = chi.neutron().create_subnet(body=body_create_subnet)
    return subnet

def delete_subnet(subnet_id):
    return chi.neutron().delete_subnet(subnet_id) 

def update_subnet(subnet_id):
    pass

def list_subnets():
    return chi.neutron().list_subnets() 

def show_subnet(subnet_id):
    return chi.neutron().show_subnet(subnet_id) 

def show_subnet_by_name(subnet_name):
    return show_subnet(get_subnet_id(subnet_name=subnet_name)) 

    
def create_router(router_name, gw_network_name=None):
    ''' 
    Create a router with or without a public gateway. 
    
    Parameters
    ----------
    router_name : str
        Name of the new router.
    gw_network_name: str
        Name of the external gateway network (i.e. the network that connects to the Internet). 
        Chameleon gateway network is 'public'. Default: None
    '''
    request = {}
    if gw_network_name:
        public_net_id= get_network_id(name=gw_network_name)
        
        #Create Router
        request = {'router': {'name': router_name,
                              'admin_state_up': True,
                              'external_gateway_info': {"network_id": public_net_id},
                             }}
    else:
        #Create Router without gateway
        request = {'router': {'name': router_name,
                              'admin_state_up': True,
                             }}
        
    router = chi.neutron().create_router(request)
    return router

def delete_router(router_id):
    return chi.neutron().delete_router(router_id) 
    pass

def update_router(router_id):
    pass

def list_routers():
    return chi.neutron().list_routers() 


def show_router(router_id):
    return chi.neutron().show_router(router_id) 

def show_router_by_name(router_name):
    return show_router(get_router_id(router_name=router_name)) 

def add_route_to_router(router_id, cidr, nexthop):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    
    body = { "router" : {
                        "routes" : [ { "destination" : cidr, "nexthop" : nexthop } ]
                        }
           }
    
    return chi.neutron().add_extra_routes_to_router(router_id, body)



def remove_routes_from_router(router_id, routes):
    body = { "router" : {
                       "routes" : routes
                        }
           }
    
    return chi.neutron().remove_extra_routes_from_router(router_id, body)

def remove_all_routes_from_router(router_id):
    return remove_routes_from_router(router_id, show_router(router_id)['routes'])

def remove_route_from_router(router_id, cidr, nexthop):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    
    body = { "router" : {
                        "routes" : [ { "destination" : cidr, "nexthop" : nexthop } ]
                        }
           }
    
    return chi.neutron().remove_extra_routes_from_router(router_id, body)


def add_port_to_router(router_id, port_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    body = { 'port_id' : port_id }
    return chi.neutron().add_interface_router(router_id, body)
    
def add_port_to_router_by_name(router_name, subnet_name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    router_id = get_router_id(name=router_name)
    port_id = get_port_id(name=port_name)
    
    return add_port_to_router(router_id, subnet_id)


def add_subnet_to_router(router_id, subnet_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    body = { 'subnet_id' : subnet_id }
    return chi.neutron().add_interface_router(router_id, body)
    
def add_subnet_to_router_by_name(router_name, subnet_name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    router_id = get_router_id(name=router_name)
    subnet_id = get_subnet_id(name=subnet_name)
    
    return add_subnet_to_router(router_id, subnet_id)
        
    
def remove_subnet_from_router(router_id, subnet_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    body = { 'subnet_id' : subnet_id }
    return chi.neutron().remove_interface_router(router_id,body)


def remove_port_from_router(router_id, port_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    body = { 'port_id' : port_id }
    return chi.neutron().remove_interface_router(router_id,body)


#get from specifc reservation 
#def get_floating_ip(reservation_id=None)

def get_free_floating_ip():
    ''' 
    TODO: Description needed Gets or creates a free floating IP to use
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
   
    ips = chi.neutron().list_floatingips()['floatingips']
    #print (ips)
    unbound = (ip for ip in ips if ip['port_id'] is None)
    try:
        fip = next(unbound)
        return fip
    except StopIteration:
        print("No free floating IP found")


def associate_floating_ip(server_name, floating_ip_str=None):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    server = get_server_by_name(server_name)
    
    if floating_ip_str == None:
        fip = get_free_floating_ip()
    else:
        fip = get_specific_floating_ip(floating_ip_str)
  
    if fip == None:
        return
    ip = fip['floating_ip_address']
    
    # using method from https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/api/neutron.py#L518
    ports = chi.neutron().list_ports(**{'device_id': server.id}).get('ports')
    fip_target = {
        'port_id': ports[0]['id'],
        'ip_addr': ports[0]['fixed_ips'][0]['ip_address']
    }
    # https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/dashboards/project/instances/tables.py#L671
    target_id = fip_target['port_id']
    chi.neutron().update_floatingip(fip['id'], body={
             'floatingip': {
                 'port_id': target_id,
                 # 'fixed_ip_address': ip_address,
              }
          }
    )
    return ip

def get_specific_floating_ip(ip_str):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    ips = chi.neutron().list_floatingips()['floatingips']
    
    for fip in ips:
        if fip['floating_ip_address'] == ip_str:
            return fip
    print("Floating ip not found " + ip_str)
    
    return None

def detach_floating_ip(server_name, floating_ip_str):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    server = get_server_by_name(server_name)
    fip = get_specific_floating_ip(ip_str)
    
    chi.neutron().update_floatingip(floating_ip['id'],
                {'floatingip': {'port_id': None}})
    
def nuke_network(network_name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    network = get_network_by_name(network_name)
    network_id = network['id']
    print('next network')
    print(json.dumps(network, indent=2))
    
    #Detach the router from all of its networks
    router_device_id=None
    for port in chi.neutron().list_ports()['ports']:
        if port['device_owner'] == "network:router_interface" and port['network_id'] == network_id:
            router_device_id = port['device_id']
            print('next port: router_device_id' + router_device_id)
            print(json.dumps(port, indent=2))
            break
        port=None
    if port != None:
        for router in chi.neutron().list_routers()['routers']:
            if router['id'] == router_device_id:
                print('next router')
                print(json.dumps(router, indent=2))
                for fixed_ip in port['fixed_ips']:
                    print('Detaching router ' + router_device_id + ' from subnet ' + fixed_ip['subnet_id'])
                    detach_router_by_id(router_device_id, fixed_ip['subnet_id'])

    #Delete the router
    if router_device_id:
        print('Deleting router ' + router_device_id)
        delete_router_by_id(router_device_id)

    
    #Delete the subnet
    for subnet in chi.neutron().list_subnets()['subnets']:
        if subnet['network_id'] == network_id:
            print('next subnet')
            print(json.dumps(subnet, indent=2))
            subnet_id=subnet['id']
            print('Deleting subnet ' + subnet_id)
            delete_subnet_by_id(subnet_id)

    #Delete the network
    print('Deleting network ' + network_name)
    delete_network_by_name(network_name)
    

def chi_wizard_create_network(name, of_controller_ip=None,of_controller_port = None): 
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    name_prefix=name
    network_name = name_prefix+'Net'
    vswitch_name = name_prefix+'VSwitch'
    router_name = name_prefix+'Router'
    subnet_name = name_prefix+'Subnet'
    provider = 'physnet1'
    
    network = create_network(network_name, of_controller_ip,of_controller_port , vswitch_name, provider)
    subnet = add_subnet(subnet_name, network_name)
    router = create_router(router_name, network_name)
    result = attach_router_to_subnet(router_name=router_name, subnet_name=subnet_name)

    return network

def chi_wizard_delete_network(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    name_prefix=name
    network_name = name_prefix+'Net'
    vswitch_name = name_prefix+'VSwitch'
    router_name = name_prefix+'Router'
    subnet_name = name_prefix+'Subnet'
    
    try:
        result = detach_router_by_name(router_name=router_name, subnet_name=subnet_name)
    except Exception as e:
        print("detach_router_by_name error:" + str(e))
        pass
    try:
        result = delete_router_by_name(router_name)
    except Exception as e:
        print("delete_router_by_name error: " + str(e))
        pass
    try:
        result = delete_subnet_by_name(subnet_name)
    except Exception as e:
        print("delete_subnet_by_name error: " + str(e))
        pass
    try:
        result = delete_network_by_name(network_name)
    except Exception as e:
        print("delete_network_by_name error: " + str(e))
        pass

