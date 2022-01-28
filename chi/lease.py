from datetime import timedelta
import json
import numbers
import re
import sys
import time
from typing import TYPE_CHECKING

from blazarclient.exception import BlazarClientException

from .clients import blazar, neutron
from .context import get as get_from_context, session
from .network import get_network_id, PUBLIC_NETWORK, list_floating_ips
from .server import Server, ServerError
from .util import random_base32, utcnow

import logging

if TYPE_CHECKING:
    from typing import Pattern

LOG = logging.getLogger(__name__)


class ErrorParsers:
    NOT_ENOUGH_RESOURCES: "Pattern" = (
        r"not enough (?P<resource_type>([\w\s\-\._]+)) available"
    )


__all__ = [
    "add_node_reservation",
    "add_network_reservation",
    "add_fip_reservation",
    "add_device_reservation",
    "get_node_reservation",
    "get_device_reservation",
    "get_reserved_floating_ips",
    "lease_duration",
    "get_lease",
    "get_lease_id",
    "create_lease",
    "delete_lease",
    "wait_for_active",
]

BLAZAR_TIME_FORMAT = "%Y-%m-%d %H:%M"
NODE_TYPES = {
    "compute_skylake",
    "compute_haswell_ib",
    "compute_cascadelake",
    "compute_cascadelake_r",
    "storage",
    "storage_hierarchy",
    "gpu_p100",
    "gpu_p100_nvlink",
    "gpu_k80",
    "gpu_m40",
    "fpga",
    "lowpower_xeon",
    "atom",
    "arm64",
}
DEFAULT_NODE_TYPE = "compute_skylake"
DEFAULT_LEASE_LENGTH = timedelta(days=1)
DEFAULT_NETWORK_RESOURCE_PROPERTIES = ["==", "$physical_network", "physnet1"]


def lease_create_args(
    neutronclient,
    name=None,
    start="now",
    end=None,
    length=None,
    nodes=1,
    node_resource_properties=None,
    fips=0,
    networks=0,
    network_resource_properties=DEFAULT_NETWORK_RESOURCE_PROPERTIES,
):
    """
    Generates the nested object that needs to be sent to the Blazar client
    to create the lease. Provides useful defaults for Chameleon.

    :param str name: name of lease. If ``None``, generates a random name.
    :param str/datetime start: when to start lease as a
        :py:class:`datetime.datetime` object, or if the string ``'now'``,
        starts in about a minute.
    :param length: length of time as a :py:class:`datetime.timedelta` object or
        number of seconds as a number. Defaults to 1 day.
    :param datetime.datetime end: when to end the lease. Provide only this or
        `length`, not both.
    :param int nodes: number of nodes to reserve.
    :param resource_properties: object that is JSON-encoded and sent as the
        ``resource_properties`` value to Blazar. Commonly used to specify
        node types.
    """
    if start == "now":
        start = utcnow() + timedelta(seconds=70)

    if length is None and end is None:
        length = DEFAULT_LEASE_LENGTH
    elif length is not None and end is not None:
        raise ValueError("provide either 'length' or 'end', not both")

    if end is None:
        if isinstance(length, numbers.Number):
            length = timedelta(seconds=length)
        end = start + length

    reservations = []

    if nodes > 0:
        if node_resource_properties:
            node_resource_properties = json.dumps(node_resource_properties)

        reservations += [
            {
                "resource_type": "physical:host",
                "resource_properties": node_resource_properties or "",
                "hypervisor_properties": "",
                "min": str(nodes),
                "max": str(nodes),
            }
        ]

    if fips > 0:
        reservations += [
            {
                "resource_type": "virtual:floatingip",
                "network_id": get_network_id(PUBLIC_NETWORK),
                "amount": fips,
            }
        ]

    if networks > 0:
        if network_resource_properties:
            network_resource_properties = json.dumps(network_resource_properties)

        reservations += [
            {
                "resource_type": "network",
                "resource_properties": network_resource_properties or "",
                "network_name": f"{name}-net{idx}",
            }
            for idx in range(networks)
        ]

    return {
        "name": name,
        "start": start.strftime(BLAZAR_TIME_FORMAT),
        "end": end.strftime(BLAZAR_TIME_FORMAT),
        "reservations": reservations,
        "events": [],
    }


def lease_create_nodetype(*args, **kwargs):
    """
    Wrapper for :py:func:`lease_create_args` that adds the
    ``resource_properties`` payload to specify node type.

    :param str node_type: Node type to filter by, ``compute_skylake``, et al.
    :raises ValueError: if there is no `node_type` named argument.
    """
    try:
        node_type = kwargs.pop("node_type")
    except KeyError:
        raise ValueError("no node_type specified")
    if node_type not in NODE_TYPES:
        print('warning: unknown node_type ("{}")'.format(node_type), file=sys.stderr)
        # raise ValueError('unknown node_type ("{}")'.format(node_type))
    kwargs["node_resource_properties"] = ["==", "$node_type", node_type]
    return lease_create_args(*args, **kwargs)


class Lease(object):
    """
    Creates and manages a lease, optionally with a context manager (``with``).

    .. code-block:: python

        with Lease(session, node_type='compute_skylake') as lease:
            instance = lease.create_server()
            ...

    When using the context manager, on entering it will wait for the lease
    to launch, then on exiting it will delete the lease, which in-turn
    also deletes the instances launched with it.

    :param keystone_session: session object
    :param bool sequester: If the context manager catches that an instance
        failed to start, it will not delete the lease, but rather extend it
        and rename it with the ID of the instance that failed.
    :param bool _no_clean: Don't delete the lease at the end of a context
        manager
    :param kwargs: Parameters passed through to
        :py:func:`lease_create_nodetype` and in turn
        :py:func:`lease_create_args`
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("session", session())

        self.session = kwargs.pop("session")
        self.blazar = blazar(session=self.session)
        self.neutron = neutron(session=self.session)

        self.lease = None

        self._servers = {}

        self._sequester = kwargs.pop("sequester", False)

        kwargs.setdefault("_preexisting", False)
        self._preexisting = kwargs.pop("_preexisting")

        kwargs.setdefault("_no_clean", False)
        self._noclean = kwargs.pop("_no_clean")

        prefix = kwargs.pop("prefix", "")
        rand = random_base32(6)
        self.prefix = f"{prefix}-{rand}" if prefix else rand

        kwargs.setdefault("name", self.prefix)

        if self._preexisting:
            self.id = kwargs["_id"]
            self.refresh()
        else:
            kwargs.setdefault("node_type", DEFAULT_NODE_TYPE)
            self._lease_kwargs = lease_create_nodetype(self.neutron, **kwargs)
            self.lease = self.blazar.lease.create(**self._lease_kwargs)
            self.id = self.lease["id"]

        self.name = self.lease["name"]
        self.reservations = self.lease["reservations"]

    @classmethod
    def from_existing(cls, id):
        """
        Attach to an existing lease by ID. When using in conjunction with the
        context manager, it will *not* delete the lease at the end.
        """
        return cls(_preexisting=True, _id=id)

    def __repr__(self):
        region = self.session.region_name
        return "<{} '{}' on {} ({})>".format(
            self.__class__.__name__, self.name, region, self.id
        )

    def __enter__(self):
        if self.lease is None:
            # don't support reuse in multiple with's.
            raise RuntimeError("Lease context manager not reentrant")
        self.wait()
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        if exc is not None and self._noclean:
            print("Lease existing uncleanly (noclean = True).")
            return

        if isinstance(exc, ServerError) and self._sequester:
            print("Instance failed to start, sequestering lease")
            self.blazar.lease.update(
                lease_id=self.id,
                name="sequester-error-instance-{}".format(exc.server.id),
                prolong_for="6d",
            )
            return

        # if lease exists, delete instances
        current_lease = self.blazar.lease.get(self.id)
        if current_lease:
            for server in self.servers:
                server.delete()

        if not self._preexisting:
            # don't auto-delete pre-existing leases
            self.delete()

    def refresh(self):
        """Updates the lease data"""
        self.lease = self.blazar.lease.get(self.id)

    @property
    def node_reservation(self):
        return next(
            iter(
                [
                    r["id"]
                    for r in (self.reservations or [])
                    if r["resource_type"] == "physical:host"
                ]
            ),
            None,
        )

    @property
    def status(self):
        """Refreshes and returns the status of the lease."""
        self.refresh()
        # NOTE(priteau): Temporary compatibility with old and new lease status
        if self.lease.get("action") is not None:
            return self.lease["action"], self.lease["status"]
        else:
            return self.lease["status"]

    @property
    def ready(self):
        """Returns True if the lease has started."""
        # NOTE(priteau): Temporary compatibility with old and new lease status
        if self.lease.get("action") is not None:
            return self.status == ("START", "COMPLETE")
        else:
            return self.status == "ACTIVE"

    @property
    def servers(self):
        return self._servers.values()

    @property
    def binding(self):
        return {
            key: {
                "address": value.ip,
                "auth": {
                    "user": "cc",
                    "private_key": get_from_context("keypair_private_key"),
                },
            }
            for key, value in self._servers.items()
        }

    def wait(self):
        """Blocks for up to 150 seconds, waiting for the lease to be ready.
        Raises a RuntimeError if it times out."""
        for _ in range(15):
            time.sleep(10)
            if self.ready:
                break
        else:
            raise RuntimeError("timeout, lease failed to start")

    def delete(self):
        """Deletes the lease"""
        self.blazar.lease.delete(self.id)
        self.lease = None

    def create_server(self, *server_args, **server_kwargs):
        """Generates instances using the resource of the lease. Arguments
        are passed to :py:class:`ccmanage.server.Server` and returns same
        object."""
        server_kwargs.setdefault("lease", self)
        server_name = server_kwargs.pop("name", len(self.servers))
        server_kwargs.setdefault("name", f"{self.prefix}-{server_name}")
        server = Server(*server_args, **server_kwargs)
        self._servers[server_name] = server
        return server


def add_node_reservation(
    reservation_list,
    count=1,
    resource_properties=[],
    node_type=None,
    architecture=None,
):
    """Add a node reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        count (int): The number of nodes of the given type to request.
            (Default 1).
        resource_properties (list): A list of resource property constraints. These take
            the form [<operation>, <search_key>, <search_value>], e.g.::

              ["==", "$node_type", "some-node-type"]: filter the reservation to only
                nodes with a `node_type` matching "some-node-type".
              [">", "$architecture.smt_size", 40]: filter to nodes having more than 40
                (hyperthread) cores.

        node_type (str): The node type to request. If None, the reservation will not
            target any particular node type. If `resource_properties` is defined, the
            node type constraint is added to the existing property constraints.
        architecture (str): The node architecture to request. If `resource_properties`
            is defined, the architecture constraint is added to the existing property
            constraints.
    """
    user_constraints = (resource_properties or []).copy()
    extra_constraints = []
    if node_type:
        extra_constraints.append(["==", "$node_type", node_type])
    if architecture:
        extra_constraints.append(["==", "$architecture.platform_type", architecture])

    if user_constraints:
        if user_constraints[0] == "and":
            # Already a compound constraint
            resource_properties = user_constraints + extra_constraints
        else:
            resource_properties = ["and", user_constraints] + extra_constraints
    else:
        if len(extra_constraints) < 2:
            # Possibly a compount constraint if multiple kwarg helpers used
            resource_properties = extra_constraints[0] if extra_constraints else []
        else:
            resource_properties = ["and"] + extra_constraints

    reservation_list.append(
        {
            "resource_type": "physical:host",
            "resource_properties": json.dumps(resource_properties),
            "hypervisor_properties": "",
            "min": count,
            "max": count,
        }
    )


def get_node_reservation(
    lease_ref, count=None, resource_properties=None, node_type=None, architecture=None
):
    """Retrieve a reservation ID for a node reservation.

    The reservation ID is useful to have when launching bare metal instances.

    Args:
        lease_ref (str): The ID or name of the lease.
        count (int): An optional count of nodes the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        resource_properties (list): An optional set of resource property constraints
            the desired reservation was made under. Use this if you have multiple
            reservations under a lease.
        node_type (str): An optional node type the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        architecture (str): An optional node architecture the desired reservation was
            made for. Use this if you have multiple reservations under a lease.

    Returns:
        The ID of the reservation, if found.

    Raises:
        ValueError: If no reservation was found, or multiple were found.
    """

    def _find_node_reservation(res):
        if res.get("resource_type") != "physical:host":
            return False
        if count is not None and not all(
            int(res.get(key)) == count for key in ["min_count", "max_count"]
        ):
            return False
        rp = res.get("resource_properties")
        if node_type is not None and node_type not in rp:
            return False
        if architecture is not None and architecture not in rp:
            return False
        if resource_properties is not None and json.dumps(rp) != resource_properties:
            return False
        return True

    res = _reservation_matching(lease_ref, _find_node_reservation)
    return res["id"]


def get_device_reservation(lease_ref, count=None, device_model=None, device_name=None):
    """Retrieve a reservation ID for a device reservation.

    The reservation ID is useful to have when requesting containers.

    Args:
        lease_ref (str): The ID or name of the lease.
        count (int): An optional count of devices the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        device_model (str): An optional device model the desired reservation was
            made for. Use this if you have multiple reservations under a lease.
        device_name (str): An optional device name the desired reservation was
            made for. Use this if you have multiple reservations under a lease.

    Returns:
        The ID of the reservation, if found.

    Raises:
        ValueError: If no reservation was found, or multiple were found.
    """

    def _find_device_reservation(res):
        if res.get("resource_type") != "device":
            return False
        # FIXME(jason): Blazar's device plugin uses "min" and "max", but the
        # standard seems to be "min_count" and "max_count"; this should be fixed in
        # Blazar's device plugin.
        if count is not None and not all(
            (key not in res) or int(res.get(key)) == count
            for key in ["min_count", "max_count", "min", "max"]
        ):
            return False
        resource_properties = res.get("resource_properties")
        if device_model is not None and device_model not in resource_properties:
            return False
        if device_name is not None and device_name not in resource_properties:
            return False
        return True

    res = _reservation_matching(lease_ref, _find_device_reservation)
    return res["id"]


def get_reserved_floating_ips(lease_ref) -> "list[str]":
    """Get a list of Floating IP addresses reserved in a lease.

    Args:
        lease_ref (str): The ID or name of the lease.

    Returns:
        A list of all reserved Floating IP addresses, if any were reserved.
    """

    def _find_fip_reservation(res):
        return res.get("resource_type") == "virtual:floatingip"

    res = _reservation_matching(lease_ref, _find_fip_reservation, multiple=True)
    fips = list_floating_ips()
    return [
        fip["floating_ip_address"]
        for fip in fips
        if any(f"reservation:{r['id']}" in fip["tags"] for r in res)
    ]


def _reservation_matching(lease_ref, match_fn, multiple=False):
    lease = get_lease(lease_ref)
    reservations = lease.get("reservations", [])
    if isinstance(reservations, str):
        LOG.info("Blazar returned nested JSON structure, unpacking.")
        try:
            reservations = json.loads(reservations)
        except Exception:
            pass

    matches = [r for r in reservations if match_fn(r)]

    if not matches:
        raise ValueError("No matching reservation found")

    if multiple:
        return matches
    else:
        if len(matches) > 1:
            raise ValueError("Multiple matching reservations found")
        return matches[0]


def add_network_reservation(
    reservation_list,
    network_name,
    of_controller_ip=None,
    of_controller_port=None,
    vswitch_name=None,
    physical_network="physnet1",
):
    """Add a network reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        network_name (str): The name of the network to create when the
            reservation starts.
        of_controller_ip (str): The OpenFlow controller IP, if the network
            should be controlled by an external controller.
        of_controller_port (int): The OpenFlow controller port.
        vswitch_name (str): The name of the virtual switch associated with
            this network. See `the virtual forwarding context documentation
            <https://chameleoncloud.readthedocs.io/en/latest/technical/networks/networks_sdn.html#corsa-dp2000-virtual-forwarding-contexts-network-layout-and-advanced-features>`_
            for more details.
        physical_network (str): The physical provider network to reserve from.
            This only needs to be changed if you are reserving a `stitchable
            network <https://chameleoncloud.readthedocs.io/en/latest/technical/networks/networks_stitching.html>`_.
            (Default "physnet1").
    """
    desc_parts = []
    if of_controller_ip and of_controller_port:
        desc_parts.append(f"OFController={of_controller_ip}:{of_controller_port}")
    if vswitch_name:
        desc_parts.append(f"VSwitchName={vswitch_name}")

    reservation_list.append(
        {
            "resource_type": "network",
            "network_name": network_name,
            "network_description": ",".join(desc_parts),
            "resource_properties": json.dumps(
                ["==", "$physical_network", physical_network]
            ),
            "network_properties": "",
        }
    )


def add_fip_reservation(reservation_list, count=1):
    """Add a floating IP reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
            The list will be extended in-place.
        count (int): The number of floating IPs to reserve.
    """
    reservation_list.append(
        {
            "resource_type": "virtual:floatingip",
            "network_id": get_network_id(PUBLIC_NETWORK),
            "amount": count,
        }
    )


def add_device_reservation(
    reservation_list, count=1, device_model=None, device_name=None
):
    """Add an IoT/edge device reservation to a reservation list.

    Args:
        reservation_list (list[dict]): The list of reservations to add to.
        count (int): The number of devices to request.
        device_model (str): The model of device to reserve. This should match
            a "model" property of the devices registered in Blazar.
        device_name (str): The name of a specific device to reserve. If this
            is provided in conjunction with ``count`` or other constraints,
            an error will be raised, as there is only 1 possible device that
            can match this criteria, because devices have unique names.

    Raises:
        ValueError: If ``device_name`` is provided, but ``count`` is greater
            than 1, or some other constraint is present.
    """
    reservation = {
        "resource_type": "device",
        "min": count,
        "max": count,
    }
    resource_properties = []
    if device_name:
        if count > 1:
            raise ValueError(
                "Cannot reserve multiple devices if device_name is a constraint."
            )
        resource_properties.append(["==", "$name", device_name])
    elif device_model:
        resource_properties.append(["==", "$model", device_model])

    if len(resource_properties) == 1:
        resource_properties = resource_properties[0]
    elif resource_properties:
        resource_properties.insert(0, "and")

    reservation["resource_properties"] = json.dumps(resource_properties)
    reservation_list.append(reservation)


def lease_duration(days=1, hours=0):
    """Compute the start and end dates for a lease given its desired duration.

    When providing both ``days`` and ``hours``, the duration is summed. So,
    the following would be a lease for one and a half days:

    .. code-block:: python

       start_date, end_date = lease_duration(days=1, hours=12)

    Args:
        days (int): The number of days the lease should be for.
        hours (int): The number of hours the lease should be for.
    """
    now = utcnow()
    # Start one minute into future to avoid Blazar thinking lease is in past
    # due to rounding to closest minute.
    start_date = (now + timedelta(minutes=1)).strftime(BLAZAR_TIME_FORMAT)
    end_date = (now + timedelta(days=days, hours=hours)).strftime(BLAZAR_TIME_FORMAT)
    return start_date, end_date


#########
# Leases
#########


def get_lease(ref) -> dict:
    """Get a lease by its ID or name.

    Args:
        ref (str): The ID or name of the lease.

    Returns:
        The lease matching the ID or name.
    """
    try:
        return blazar().lease.get(ref)
    except BlazarClientException as err:
        # Blazar's exception class is a bit odd and stores the actual code
        # in 'kwargs'. The 'code' attribute on the exception is just the default
        # code. Prefer to use .kwargs['code'] if present, fall back to .code
        code = getattr(err, "kwargs", {}).get("code", getattr(err, "code", None))
        if code == 404:
            return blazar().lease.get(get_lease_id(ref))
        else:
            raise


def get_lease_id(lease_name) -> str:
    """Look up a lease's ID from its name.

    Args:
        name (str): The name of the lease.

    Returns:
        The ID of the found lease.

    Raises:
        ValueError: If the lease could not be found, or if multiple leases were
            found with the same name.
    """
    matching = [l for l in blazar().lease.list() if l["name"] == lease_name]
    if not matching:
        raise ValueError(f"No leases found for name {lease_name}")
    elif len(matching) > 1:
        raise ValueError(f"Multiple leases found for name {lease_name}")
    return matching[0]["id"]


def create_lease(lease_name, reservations=[], start_date=None, end_date=None):
    """Create a new lease with some requested reservations.

    Args:
        lease_name (str): The name to give the new lease.
        reservations (list[dict]): The reservations to request with the lease.
        start_date (datetime): The start date of the lease. (Defaults to now.)
        end_date (datetime): The end date of the lease. (Defaults to 1 day from
            the lease start date.)

    Returns:
        The created lease representation.
    """
    if not (start_date or end_date):
        start_date, end_date = lease_duration(days=1)
    elif not end_date:
        end_date = start_date + timedelta(days=1)
    elif not start_date:
        start_date = utcnow()

    if not reservations:
        raise ValueError("No reservations provided.")

    try:
        return blazar().lease.create(
            name=lease_name,
            start=start_date,
            end=end_date,
            reservations=reservations,
            events=[],
        )
    except BlazarClientException as ex:
        msg: "str" = ex.args[0]
        msg = msg.lower()

        match = ErrorParsers.NOT_ENOUGH_RESOURCES.match(msg)
        if match:
            LOG.error(
                f"There were not enough unreserved {match.group('resource_type')} "
                "to satisfy your request."
            )
        else:
            LOG.error(msg)


def delete_lease(ref):
    """Delete the lease.

    Args:
        ref (str): The name or ID of the lease.
    """
    lease = get_lease(ref)
    lease_id = lease["id"]
    blazar().lease.delete(lease_id)
    print(f"Deleted lease with id {lease_id}")


def wait_for_active(ref):
    """Wait for the lease to become active.

    This function will wait for 2.5 minutes, which is a somewhat arbitrary
    amount of time.

    Args:
        ref (str): The name or ID of the lease.

    Returns:
        The lease in ACTIVE state.

    Raises:
        TimeoutError: If the lease fails to become active within the timeout.
    """
    for _ in range(15):
        lease = get_lease(ref)
        status = lease["status"]
        if status == "ACTIVE":
            return lease
        elif status == "ERROR":
            raise RuntimeError("Lease went into ERROR state")
        time.sleep(10)
    raise TimeoutError("Lease failed to start")
