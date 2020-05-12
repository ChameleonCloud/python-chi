import chi
import json
import os
from chi.util import get_public_network

def get_network_by_name(name):
    network=None
    for n in chi.neutron().list_networks()['networks']:
        if n['name'] == name:
            if network != None:
                raise RuntimeError('Found multiple networks with name ' + str(name))
            network = n
            
    if network == None:
        raise RuntimeError('Network not found. name: ' + str(name))
        
    return network

def get_router_by_name(name):
    router=None
    for r in chi.neutron().list_routers()['routers']:
        if r['name'] == name:
            if router != None:
                raise RuntimeError('Found multiple routers with name ' + str(name))
            router = r
    
    if router == None:
        raise RuntimeError('Router not found. name: ' + str(name))
    
    return router

def get_subnet_by_name(name):
    subnet=None
    for s in chi.neutron().list_subnets()['subnets']:
        if s['name'] == name:
            if subnet != None:
                raise RuntimeError('Found multiple subnets with name ' + str(name))
            subnet = s
             
    if subnet == None:
        raise RuntimeError('Subnet not found. name: ' + str(name))
                                
    return subnet

def create_network(network_name, of_controller_ip=None, of_controller_port=None, vswitch_name=None, provider="physnet1"):
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
                              }}

    network = chi.neutron().create_network(body=body_sample)
    return network['network']

def add_subnet(subnet_name, network_name, cidr='192.168.1.0/24'):
    network=get_network_by_name(name=network_name)
    network_id=network['id']

    #Add Subnet
    body_create_subnet = {'subnets': [{'cidr': cidr,
                                       'ip_version': 4, 
                                       'network_id': network_id,
                                       'name': subnet_name,
                                      }]
                          }
    subnet = chi.neutron().create_subnet(body=body_create_subnet)
    return subnet

    
def create_router(router_name, network_name):

    public_net=get_network_by_name(name='public')
    public_net_id=public_net['id']
    

    #Create Router
    request = {'router': {'name': router_name,
                          'admin_state_up': True,
                          'external_gateway_info': {"network_id": public_net_id},
                         }}

    network = get_network_by_name(network_name)
    network_id = network['id']

    router = chi.neutron().create_router(request)
    return router

def attach_router_to_subnet(router_name, subnet_name):
    try:
        router = get_router_by_name(name=router_name)
        router_id = router['id']
    except Exception as e:
        import sys
        raise type(e)(str(e) +
                      ', Failed to get router %s. Does it exist?' % router_name).with_traceback(sys.exc_info()[2])                                
                                
    try:
        subnet = get_subnet_by_name(name=subnet_name)
        subnet_id = subnet['id']
    except Exception as e:
        import sys
        raise type(e)(str(e) +
                      ', Failed to get subnet %s. Does it exist?' % subnet_name).with_traceback(sys.exc_info()[2])      
    
    body = {}
    body['subnet_id'] = subnet_id 
    return chi.neutron().add_interface_router(router_id, body)
    

def detach_router_by_id(router_id, subnet_id):
    body = {}
    body['subnet_id'] = subnet_id 
    return chi.neutron().remove_interface_router(router_id,body)


def detach_router_by_name(router_name, subnet_name):
    router=get_router_by_name(name=router_name)
    router_id=router['id']
    #print(router_id)
                          
    subnet = get_subnet_by_name(name=subnet_name)
    subnet_id = subnet['id']

    #body = {}
    #body['subnet_id'] = subnet_id 
    #return neutron.remove_interface_router(router_id,body)
    return detach_router_by_id(router_id, subnet_id)
    


def delete_router_by_id(router_id):
    return chi.neutron().delete_router(router_id)

def delete_router_by_name(router_name):
    router=get_router_by_name(name=router_name)
    router_id=router['id']
    #print(router_id)
    return chi.neutron().delete_router(router_id)

#Delete Subnet
def delete_subnet_by_id(subnet_id):
    chi.neutron().delete_subnet(subnet_id)

def delete_subnet_by_name(subnet_name):

    subnet = get_subnet_by_name(subnet_name)
    subnet_id = subnet['id']
    chi.neutron().delete_subnet(subnet_id)
    

def delete_network_by_name(network_name):
    network = get_network_by_name(network_name)
    network_id = network['id']

    chi.neutron().delete_network(network_id)
    
def nuke_network(network_name):
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

