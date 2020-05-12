import chi
import json
import os
from chi.util import get_public_network

nova = chi.nova()
blazar = chi.blazar()
neutron = chi.neutron()

from datetime import datetime, timedelta
from dateutil import tz

BLAZAR_TIME_FORMAT = "%Y-%m-%d %H:%M"

def add_node_reservation(reservation_list, count=1, node_type="compute_haswell"):
    reservation_list.append({
        "resource_type": "physical:host",
        "resource_properties": json.dumps(["==", "$node_type", node_type]),
        "hypervisor_properties": "",
        "min": count,
        "max": count
    })

def add_network_reservation(reservation_list, 
                            network_name,
                            network_description="", 
                            of_controller_ip=None, 
                            of_controller_port=None, 
                            vswitch_name=None, 
                            physical_network="physnet1"):

    if of_controller_ip != None and of_controller_port != None:
        description = description + 'OFController=' + of_controller_ip + ':' + of_controller_port 
        
    if vswitch_name != None and of_controller_ip != None and of_controller_port != None:
        description = description + ','
    
    if vswitch_name != None:
        description = description + 'VSwitchName=' + vswitch_name

    reservation_list.append({
        "resource_type": "network",
        "network_name": network_name,
        "network_description": network_description,
        "resource_properties": json.dumps(["==", "$physical_network", physical_network]),
        "network_properties": ""
    })
    
def add_fip_reservation(reservation_list, count=1):
    #Get public network id (needed to reserve networks)
    public_network_id = get_public_network(chi.neutron())

    reservation_list.append({
        "resource_type": "virtual:floatingip",
        "network_id": public_network_id,
        "amount": count
    })    
    
    
def reserve_node(lease_name,node_type="compute_haswell",count=1):
    # Set start/end date for lease
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (datetime.now(tz=tz.tzutc()) + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date   = (datetime.now(tz=tz.tzutc()) + timedelta(days=1)).strftime(BLAZAR_TIME_FORMAT)
    
    # Build list of reservations (in this case there is only one reservation)
    reservation_list = []
    add_node_reservation(reservation_list, count=count, node_type=node_type)

    # Create the lease
    lease = chi.blazar().lease.create(name=lease_name, 
                                start=start_date,
                                end=end_date,
                                reservations=reservation_list, events=[])

def reserve_network(lease_name,
                    network_name,
                    of_controller_ip=None, 
                    of_controller_port=None, 
                    vswitch_name=None, 
                    physical_network="physnet1"):
    # Set start/end date for lease
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (datetime.now(tz=tz.tzutc()) + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date   = (datetime.now(tz=tz.tzutc()) + timedelta(days=1)).strftime(BLAZAR_TIME_FORMAT)
    
    # Build list of reservations (in this case there is only one reservation)
    reservation_list = []
    add_network_reservation(reservation_list, 
                            network_name=network_name,
                            of_controller_ip=of_controller_ip, 
                            of_controller_port=of_controller_port, 
                            vswitch_name=vswitch_name, 
                            physical_network=physical_network)
    
    # Create the lease
    lease = chi.blazar().lease.create(name=lease_name, 
                                start=start_date,
                                end=end_date,
                                reservations=reservation_list, events=[])
        
    
def reserve_floating_ip(lease_name,count=1):
    # Set start/end date for lease
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (datetime.now(tz=tz.tzutc()) + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date   = (datetime.now(tz=tz.tzutc()) + timedelta(days=1)).strftime(BLAZAR_TIME_FORMAT)
    
    # Build list of reservations (in this case there is only one reservation)
    reservation_list = []
    add_fip_reservation(reservation_list, count=count)
    
    # Create the lease
    lease = chi.blazar().lease.create(name=lease_name, 
                                start=start_date,
                                end=end_date,
                                reservations=reservation_list, events=[])
    
def reserve_multiple_resources(lease_name):
    # Set start/end date for lease
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (datetime.now(tz=tz.tzutc()) + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date   = (datetime.now(tz=tz.tzutc()) + timedelta(days=1)).strftime(BLAZAR_TIME_FORMAT)
    
    # Build list of reservations (in this case there is only one reservation)
    reservation_list = []
    add_node_reservation(reservation_list, count=1, node_type="compute_haswell")
    add_network_reservation(reservation_list, network_name=lease_name+"Network")
    add_fip_reservation(reservation_list, count=1)
    
    # Create the lease
    lease = chi.blazar().lease.create(name=lease_name, 
                                start=start_date,
                                end=end_date,
                                reservations=reservation_list, events=[])
    
def get_lease_by_name(lease_name):
    leases = list(filter(lambda lease: lease['name'] == lease_name, chi.blazar().lease.list()))
    if len(leases) == 1:
        lease = leases[0]    
        return lease
    else:
        raise RuntimeError("Error: Found " + str(len(leases)) + " leases with name " + str(lease_name) + ". Expected 1")

        
def delete_lease_by_id(lease_id):
    chi.blazar().lease.delete(lease_id)
        
def delete_lease_by_name(lease_name):
    lease = list(filter(lambda lease: lease['name'] == lease_name, chi.blazar().lease.list()))
    if len(lease) == 1:
        lease_id = lease[0]['id']
        chi.blazar().lease.delete(lease_id)

        print("Deleted lease " + str(lease_name) + " with id " + str(lease_id))
    else:
        print("Error: Found " + str(len(lease)) + " leases with name " + str(lease_name) + ". Expected 1")

def get_floating_ip_by_reservation_id(reservation_id):
    chi.blazar().lease.list()
    