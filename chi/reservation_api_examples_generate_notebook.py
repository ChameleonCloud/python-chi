# Do not import things here. Each example below should be a stand-alone function that included all imports.



def create_network_notebook():
    ''' 
       This is the description of this example of  in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    import json
    import chi
    from chi.networking_api_examples import create_network

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'

    network = create_network(network_name="pruthNet", 
                             of_controller_ip=None, 
                             of_controller_port=None, 
                             vswitch_name="pruthVSwitch", 
                             provider="physnet1")
    
    
        

    #Print the lease info
    print(json.dumps(network, indent=2))

def create_router_notebook():
    ''' 
       This is the description of this example of  in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    import json
    import chi
    from chi.networking_api_examples import create_router

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'

    router = create_router(router_name="pruth_router",gw_network_name='public')

    #Print the lease info
    print(json.dumps(router, indent=2))

def reserve_node_notebook():
    ''' 
       This is the description of this example of reserve_node_notebook in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    
    import json
    import os
    import chi

    from chi.reservation_api_examples import reserve_node
    from chi.reservation_api_examples import get_lease_by_name

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'

    #Create the lease
    reserve_node("myNewLeaseName", node_type="compute_haswell")

    #Get the lease by name
    lease = get_lease_by_name("myNewLeaseName")

    #Print the lease info
    print(json.dumps(lease, indent=2))

    
def reserve_network_notebook():
    ''' 
       This is the description of this example of reserve_network_notebook in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    import json
    import os
    import chi

    from chi.reservation_api_examples import reserve_network
    from chi.reservation_api_examples import get_lease_by_name

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'


    #Get a network by name
    lease = reserve_network("myLeaseName", network_name=network_name)

    #Get the lease by name
    lease = get_lease_by_name("myLeaseName")

    #Print the lease info
    print(json.dumps(lease, indent=2))

def reserve_floating_ip_notebook():
    ''' 
       This is the description of this example of reserve_floating_ip_notebook in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    import json
    import os
    import chi

    from chi.reservation_api_examples import reserve_floating_ip
    from chi.reservation_api_examples import get_lease_by_name

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'

    #Get a network by name
    lease = reserve_floating_ip("myNewLeaseName")

    #Get the lease by name
    lease = get_lease_by_name("myNewLeaseName")

    #Print the lease info
    print(json.dumps(lease, indent=2))

def delete_lease_notebook():
    ''' 
       This is the description of this example of delete_lease_notebook in the notebook from the docstring in reservation_notebook_examples.py.
    '''
    import json
    import os
    import chi

    from chi.reservation_api_examples import delete_lease_by_name

    #Config with your project and site
    chi.set('project_name', 'CH-816532') # Replace with your project name
    chi.set('region_name', 'CHI@UC')     # Optional, defaults to 'CHI@UC'


    # Tip: Name resources with your username for easier identification
    username = os.getenv("USER")
    lease_name = username+'Lease'

    #Delete the lease
    lease = delete_lease_by_name(lease_name)