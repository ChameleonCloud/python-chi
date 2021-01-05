import chi
import json
import os

from chi.reservation_api_examples import *
from chi.networking_api_examples import *

#nova = chi.nova()
#blazar = chi.blazar()
#neutron = chi.neutron()
#glance = chi.glance()

def list_images():
    return chi.glance().images.list()

def get_image_by_name(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    try:
        return list(chi.glance().images.list(filters={'name': name}))[0]
    except:
        images = list(chi.glance().images.list(filters={'name': name}))
        if len(images) < 1:
            raise RuntimeError('no images found matching name or ID "{}"'.format(name))
        elif len(images) > 1:
            raise RuntimeError('multiple images found matching name "{}"'.format(name))
        else:
            return images[0]

def get_image_id(name):
    image=get_image_by_name(name)
    if image:
        return image.id
    else:
        return None
    
def get_image(id):
    return chi.glance().images.get(id)

        
def list_flavors():
    return chi.nova().flavors.list()
        
def get_flavor_by_name(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    flavor = next((f for f in chi.nova().flavors.list() if f.name == name), None)

    if not flavor:
        raise RuntimeError('no flavor found matching name "{}"'.format(name))
    
    return flavor
    
def get_flavor_id(name):
    flavor=get_flavor_by_name(name)
    if flavor:
        return flavor.id
    else:
        return None
    
def get_flavor(id):
    return chi.nova().flavors.get(id)

    
def get_server_by_name(name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    server = None    
    for s in chi.nova().servers.list():
        if s.name == name:
            if server == None:
                server = s
            else:
                print("Found multiple servers with name " + str(name))
                return None
    return server

def get_server_id(name):
    server=get_server_by_name(name)
    if server:
        return server.id
    else:
        return None
    
def get_server(id):
    return chi.nova().servers.get(id)



def list_servers():
    return chi.nova().servers.list()


def create_server_simple(server_name, 
                  reservation_id, 
                  key_name, 
                  network_name='sharednet1', 
                  fixed_ip='',
                  count=1, 
                  image_name='CC-CentOS7', 
                  flavor_name='baremetal'):
    
    # Create network list
    network_id = get_network_id(name=network_name)
    nics=[{"net-id": network_id, "v4-fixed-ip": ''}]
    
    # Get flavor
    flavor = get_flavor_by_name(name=flavor_name).id
    if not flavor:
        raise RuntimeError('no flavor found matching name "{}"'.format(flavor_name))
    
    #Get image
    image_id = get_image_by_name(name=image_name)['id']
        
    return create_server(server_name, 
                  reservation_id=reservation_id, 
                  key_name=key_name, 
                  count=count, 
                  nics=nics,
                  image_id=image_id, 
                  flavor_id=get_flavor_id(flavor_name))
    

def create_server(server_name, 
                  reservation_id, 
                  key_name, 
                  image_id, 
                  nics=[{"net-id": 'sharednet1', 'v4-fixed-ip': ''}],
                  count=1, 
                  flavor_id=None):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    # Get flavor
    if not flavor_id:
        flavor_id=get_flavor_id('baremetal')
        
    server = chi.nova().servers.create(name=server_name,
                       image=image_id,
                       flavor=flavor_id,
                       scheduler_hints={'reservation': reservation_id},
                       key_name=key_name,
                       nics=nics,
                       min_count=count,
                       max_count=count 
                       )
    return server
    
def delete_server_by_name(server_name):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    return get_server_by_name(server_name).delete()
    
def delete_server(server_id):
    ''' 
    TODO: Description needed
    
    Parameters
    ----------
    arg1 : str
        Description of parameter `arg1`.
    '''
    return get_server(id).delete()

