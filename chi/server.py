import os
from datetime import datetime
from time import sleep

from glanceclient.client import Client as GlanceClient
from glanceclient.exc import NotFound
from neutronclient.v2_0.client import Client as NeutronClient
from novaclient.client import Client as NovaClient

from . import context
from .keypair import Keypair
from .util import get_public_network, random_base32


DEFAULT_IMAGE = "CC-CentOS7"


class ServerError(RuntimeError):
    def __init__(self, msg, server):
        super().__init__(msg)
        self.server = server


def instance_create_args(
    reservation,
    name=None,
    image=DEFAULT_IMAGE,
    flavor=None,
    key=None,
    net_ids=None,
    **kwargs
):
    if name is None:
        name = "instance-{}".format(random_base32(6))

    server_args = {
        "name": name,
        "flavor": flavor,
        "image": image,
        "scheduler_hints": {"reservation": reservation,},
        "key_name": key,
    }

    if net_ids is None:
        # automatically binds "the one" unless there's more than one
        server_args["nics"] = None
    else:
        # Not sure what fields are actually required and what they're called.
        # novaclient (and Nova HTTP API) docs seem vague. the command at
        # https://github.com/ChameleonCloud/horizon/blob/stable/liberty/openstack_dashboard/dashboards/project/instances/workflows/create_instance.py#L943
        # appears to POST a JSON akin to
        # {"server": {..., "networks": [{"uuid": "e8c33574-5423-436c-a45b-5bab78071b8a"}] ...}, "os:scheduler_hints": ...},
        server_args["nics"] = [
            {"net-id": netid, "v4-fixed-ip": ""} for netid in net_ids
        ]

    server_args.update(kwargs)
    return server_args


def get_networkid_byname(neutronclient, name):
    nets = neutronclient.list_networks()["networks"]
    for net in nets:
        if net["name"] == name:
            return net["id"]
    raise RuntimeError("couldn't find net with name '{}'".format(name))


def create_floatingip(neutronclient):
    pubnet_id = get_public_network(neutronclient)
    body = {"floatingip": {"floating_network_id": pubnet_id}}
    floatingip = neutronclient.create_floatingip(body)["floatingip"]
    return floatingip


def get_create_floatingip(neutronclient):
    """Gets or creates a free floating IP to use"""
    created = False
    ips = neutronclient.list_floatingips()["floatingips"]
    unbound = (ip for ip in ips if ip["port_id"] is None)
    try:
        fip = next(unbound)
    except StopIteration:
        fip = create_floatingip(neutronclient)
        created = True
    return created, fip


def resolve_image_idname(glanceclient, idname):
    try:
        return glanceclient.images.get(image_id=idname)
    except NotFound:
        images = list(glanceclient.images.list(filters={"name": idname}))
        if len(images) < 1:
            raise RuntimeError(
                'no images found matching name or ID "{}"'.format(idname)
            )
        elif len(images) > 1:
            raise RuntimeError(
                'multiple images found matching name "{}"'.format(idname)
            )
        else:
            return images[0]


def resolve_flavor(novaclient, flavor_name):
    flavor = next((f for f in novaclient.flavors.list() if f.name == flavor_name), None)

    if not flavor:
        raise RuntimeError('no flavor found matching name "{}"'.format(flavor_name))

    return flavor


class Server(object):
    """
    Launches an instance on a lease.
    """

    def __init__(self, id=None, lease=None, key=None, image=DEFAULT_IMAGE, **kwargs):
        kwargs.setdefault("session", context.session())

        self.session = kwargs.pop("session")

        self.neutron = NeutronClient(session=self.session)
        self.nova = NovaClient("2", session=self.session)
        self.glance = GlanceClient("2", session=self.session)
        self.image = resolve_image_idname(self.glance, image)
        self.flavor = resolve_flavor(self.nova, "baremetal")

        self.ip = None
        self._fip = None
        self._fip_created = False
        self._preexisting = False

        kwargs.setdefault("_no_clean", False)
        self._noclean = kwargs.pop("_no_clean")

        net_ids = kwargs.pop("net_ids", None)
        net_name = kwargs.pop("net_name", "sharednet1")
        if net_ids is None and net_name is not None:
            net_ids = [get_networkid_byname(self.neutron, net_name)]

        if id is not None:
            self._preexisting = True
            self.server = self.nova.servers.get(id)
        elif lease is not None:
            if key is None:
                key = Keypair().key_name
            server_kwargs = instance_create_args(
                lease.node_reservation,
                image=self.image,
                flavor=self.flavor,
                key=key,
                net_ids=net_ids,
                **kwargs
            )
            self.server = self.nova.servers.create(**server_kwargs)
        else:
            raise ValueError("Missing required argument: 'id' or 'lease' required.")

        self.id = self.server.id
        self.name = self.server.name

    def __repr__(self):
        return "<{} '{}' ({})>".format(self.__class__.__name__, self.name, self.id)

    def __enter__(self):
        self.wait()
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        if exc is not None and self._noclean:
            print("Instance existing uncleanly (noclean = True).")
            return

        self.disassociate_floating_ip()
        if not self._preexisting:
            self.delete()

    def refresh(self):
        now = datetime.now()
        try:
            lr = self._last_refresh
        except AttributeError:
            pass  # expected failure on first pass
        else:
            # limit refreshes to once/sec.
            if (now - lr).total_seconds() < 1:
                return

        self.server.get()
        self._last_refresh = now

    @property
    def status(self):
        self.refresh()
        return self.server.status

    @property
    def ready(self):
        return self.status == "ACTIVE"

    @property
    def error(self):
        return self.status == "ERROR"

    def wait(self):
        # check a couple for fast failures
        for _ in range(3):
            sleep(10)
            if self.ready:
                return
            if self.error:
                raise ServerError(self.server.fault, self.server)
        sleep(5 * 60)
        for _ in range(100):
            sleep(10)
            if self.ready:
                return
            if self.error:
                raise ServerError(self.server.fault, self.server)
        else:
            raise RuntimeError("timeout, server failed to start")
        # print('server active')

    def associate_floating_ip(self):
        if self.ip is not None:
            return self.ip

        created, self._fip = get_create_floatingip(self.neutron)
        self._fip_created = created
        self.ip = self._fip["floating_ip_address"]
        try:
            self.server.add_floating_ip(self.ip)
        except AttributeError:
            # using method from https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/api/neutron.py#L518
            ports = self.neutron.list_ports(**{"device_id": self.id}).get("ports")
            fip_target = {
                "port_id": ports[0]["id"],
                "ip_addr": ports[0]["fixed_ips"][0]["ip_address"],
            }
            # https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/dashboards/project/instances/tables.py#L671
            target_id = fip_target["port_id"]
            self.neutron.update_floatingip(
                self._fip["id"],
                body={
                    "floatingip": {
                        "port_id": target_id,
                        # 'fixed_ip_address': ip_address,
                    }
                },
            )
        return self.ip

    def disassociate_floating_ip(self):
        if self.ip is None:
            return

        self.server.remove_floating_ip(self.ip)
        if self._fip_created:
            self.neutron.delete_floatingip(self._fip["id"])

        self.ip = None
        self._fip = None
        self._fip_created = False

    def delete(self):
        self.server.delete()
        # wait for deletion complete
        for _ in range(30):
            sleep(60)
            try:
                self.server.get()
            except Exception as e:
                if "HTTP 404" in str(e):
                    return
        else:
            raise RuntimeError("timeout, server failed to terminate")

    def rebuild(self, idname):
        self.image = resolve_image_idname(self.glance, idname)
        self.server.rebuild(self.image)
