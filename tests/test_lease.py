from datetime import datetime

import pytest

@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


def example_reserve_node():
    """Reserve a bare metal node.

    Multiple nodes can be reserved at once by changing the `count` variable.
    This example makes a reservation for the "compute_haswell" node type.
    [See here](https://chameleoncloud.readthedocs.io/en/latest/technical/reservations.html#chameleon-node-types)
    for a complete list of node types available currently.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [add_node_reservation](../modules/lease.html#chi.lease.add_node_reservation)
    * [lease_duration](../modules/lease.html#chi.lease.lease_duration)
    * [create_lease](../modules/lease.html#chi.lease.create_lease)

    </div>

    """
    from chi.lease import lease_duration, add_node_reservation, create_lease

    lease_name = "myLease"
    node_type = "compute_haswell"
    start_date, end_date = lease_duration(days=1)

    # Build list of reservations (in this case there is only one reservation)
    reservations = []
    add_node_reservation(reservations, count=1, node_type=node_type)
    # Create the lease
    lease = create_lease(lease_name, reservations, start_date=start_date,
                         end_date=end_date)


def test_example_reserve_node(mocker, now):
    mocker.patch('chi.lease.utcnow', return_value=now)
    blazar = mocker.patch('chi.lease.blazar')()

    example_reserve_node()

    blazar.lease.create.assert_called_once_with(
        name='myLease',
        start='2021-01-01 00:01',
        end='2021-01-02 00:00',
        events=[],
        reservations=[{
            'resource_type': 'physical:host',
            'hypervisor_properties': '', 'max': 1, 'min': 1,
            'resource_properties': '["==", "$node_type", "compute_haswell"]',
        }]
    )


def example_reserve_network():
    """Reserve a VLAN segment.

    This example illustrates how to reserve an isolated VLAN in order to
    ensure your network experiment is not subject to cross-traffic from other
    experimenters.

    This is also how you reserve
    [stitchable VLANs](https://chameleoncloud.readthedocs.io/en/latest/technical/networks/networks_stitching.html)
    provided through ExoGENI. For these VLANs, you must set `physical_network`
    to "exogeni".

    <div class="alert alert-info">

    **Functions used in this example:**

    * [add_network_reservation](../modules/lease.html#chi.lease.add_network_reservation)
    * [lease_duration](../modules/lease.html#chi.lease.lease_duration)
    * [create_lease](../modules/lease.html#chi.lease.create_lease)

    </div>

    """
    from chi.lease import lease_duration, add_network_reservation, create_lease

    lease_name = "myLease"
    network_name = f"{lease_name}Network"
    of_controller_ip = None
    of_controller_port = None
    vswitch_name = None
    physical_network = "physnet1"
    start_date, end_date = lease_duration(days=1)

    # Build list of reservations (in this case there is only one reservation)
    reservations = []
    add_network_reservation(reservations,
                            network_name=network_name,
                            of_controller_ip=of_controller_ip,
                            of_controller_port=of_controller_port,
                            vswitch_name=vswitch_name,
                            physical_network=physical_network)

    # Create the lease
    lease = create_lease(lease_name, reservations, start_date=start_date,
                         end_date=end_date)


def test_example_reserve_network(mocker, now):
    mocker.patch('chi.lease.utcnow', return_value=now)
    blazar = mocker.patch('chi.lease.blazar')()

    example_reserve_network()

    blazar.lease.create.assert_called_once_with(
        name='myLease',
        start='2021-01-01 00:01',
        end='2021-01-02 00:00',
        events=[],
        reservations=[{
            'resource_type': 'network',
            'network_name': 'myLeaseNetwork',
            'network_description': '',
            'network_properties': '',
            'resource_properties': '["==", "$physical_network", "physnet1"]',
        }]
    )


def example_reserve_floating_ip():
    """Reserve a floating IP.

    While it's possible to allocate a floating IP ad hoc from Chameleon most
    of the time, there are a limited amount of IPs and they are sometimes
    exhausted. You can reserve a floating IP to ensure you have access to one
    to attach to your experimental nodes to allow, e.g., external SSH
    connectivity.

    [See here](https://www.chameleoncloud.org/blog/2019/02/27/save-planet-use-fewer-ips/)
    for some tips on how to make the most out of a single floating IP, which
    can help you avoid excessive charges.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [add_fip_reservation](../modules/lease.html#chi.lease.add_fip_reservation)
    * [lease_duration](../modules/lease.html#chi.lease.lease_duration)
    * [create_lease](../modules/lease.html#chi.lease.create_lease)

    </div>

    """
    from chi.lease import lease_duration, add_fip_reservation, create_lease

    lease_name = "myLease"
    start_date, end_date = lease_duration(days=1)

    # Build list of reservations (in this case there is only one reservation)
    reservation_list = []
    add_fip_reservation(reservation_list, count=1)

    # Create the lease
    lease = create_lease(lease_name, reservation_list, start_date=start_date,
                         end_date=end_date)


def test_example_reserve_floating_ip(mocker, now):
    mocker.patch('chi.lease.utcnow', return_value=now)
    blazar = mocker.patch('chi.lease.blazar')()
    mocker.patch('chi.lease.get_network_id', return_value='public-net-id')

    example_reserve_floating_ip()

    blazar.lease.create.assert_called_once_with(
        name='myLease',
        start='2021-01-01 00:01',
        end='2021-01-02 00:00',
        events=[],
        reservations=[{
            'resource_type': 'virtual:floatingip',
            'amount': 1,
            'network_id': 'public-net-id',
        }]
    )


def example_reserve_multiple_resources():
    """Reserve multiple types of resources in a single lease.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [add_node_reservation](../modules/lease.html#chi.lease.add_node_reservation)
    * [add_network_reservation](../modules/lease.html#chi.lease.add_network_reservation)
    * [add_fip_reservation](../modules/lease.html#chi.lease.add_fip_reservation)
    * [lease_duration](../modules/lease.html#chi.lease.lease_duration)
    * [create_lease](../modules/lease.html#chi.lease.create_lease)

    </div>

    """
    from chi.lease import (
        lease_duration, add_node_reservation, add_network_reservation,
        add_fip_reservation, create_lease)

    lease_name = "myLease"
    start_date, end_date = lease_duration(days=1)

    # Build list of reservations
    reservations = []
    add_node_reservation(reservations, count=1, node_type="compute_haswell")
    add_network_reservation(reservations, network_name=f"{lease_name}Network")
    add_fip_reservation(reservations, count=1)

    # Create the lease
    lease = create_lease(lease_name, reservations, start_date=start_date,
                         end_date=end_date)


def test_example_reserve_multiple_resources(mocker, now):
    mocker.patch('chi.lease.utcnow', return_value=now)
    blazar = mocker.patch('chi.lease.blazar')()
    mocker.patch('chi.lease.get_network_id', return_value='public-net-id')

    example_reserve_multiple_resources()

    blazar.lease.create.assert_called_once_with(
        name='myLease',
        start='2021-01-01 00:01',
        end='2021-01-02 00:00',
        events=[],
        reservations=[{
            'resource_type': 'physical:host',
            'hypervisor_properties': '', 'max': 1, 'min': 1,
            'resource_properties': '["==", "$node_type", "compute_haswell"]',
        }, {
            'resource_type': 'network',
            'network_name': 'myLeaseNetwork',
            'network_description': '',
            'network_properties': '',
            'resource_properties': '["==", "$physical_network", "physnet1"]',
        }, {
            'resource_type': 'virtual:floatingip',
            'amount': 1,
            'network_id': 'public-net-id',
        }]
    )
