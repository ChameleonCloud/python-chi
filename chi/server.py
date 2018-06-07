import os
import time
import urllib.parse

from glanceclient.client import Client as GlanceClient
from glanceclient.exc import NotFound
from neutronclient.v2_0.client import Client as NeutronClient
from novaclient.client import Client as NovaClient

from .util import random_base32


DEFAULT_IMAGE = 'CC-CentOS7'


class ServerError(RuntimeError):
    def __init__(self, msg, server):
        super().__init__(msg)
        self.server = server


def instance_create_args(reservation, name=None, image=DEFAULT_IMAGE, key=None, net_ids=None, **extra):
    if name is None:
        name = 'instance-{}'.format(random_base32(6))

    server_args = {
        'name': name,
        'flavor': 'baremetal',
        'image': image,
        # 'reservation_id': lease['reservations'][0]['id'],
        'scheduler_hints': {
            'reservation': reservation,
        },
        'key_name': key,
    }

    if net_ids is None:
        # automatically binds "the one" unless there's more than one
        server_args['nics'] = None
    else:
        # Not sure what fields are actually required and what they're called.
        # novaclient (and Nova HTTP API) docs seem vague. the command at
        # https://github.com/ChameleonCloud/horizon/blob/stable/liberty/openstack_dashboard/dashboards/project/instances/workflows/create_instance.py#L943
        # appears to POST a JSON akin to
        # {"server": {..., "networks": [{"uuid": "e8c33574-5423-436c-a45b-5bab78071b8a"}] ...}, "os:scheduler_hints": ...},
        server_args['nics'] = [{"net-id": netid, "v4-fixed-ip": ""} for netid in net_ids]

    server_args.update(extra)
    return server_args


def get_public_network(neutronclient):
    nets = neutronclient.list_networks()['networks']
    for net in nets:
        if net['router:external'] != True:
            continue
        pubnet_id = net['id']
        break
    else:
        raise RuntimeError("couldn't find public net")
    return pubnet_id


def get_networkid_byname(neutronclient, name):
    nets = neutronclient.list_networks()['networks']
    for net in nets:
        if net['name'] == name:
            return net['id']
    raise RuntimeError("couldn't find net with name '{}'".format(name))


def create_floatingip(neutronclient):
    pubnet_id = get_public_network(neutronclient)
    body = {'floatingip': {'floating_network_id': pubnet_id}}
    floatingip = neutronclient.create_floatingip(body)['floatingip']
    return floatingip


def get_create_floatingip(neutronclient):
    '''Gets or creates a free floating IP to use'''
    created = False
    ips = neutronclient.list_floatingips()['floatingips']
    unbound = (ip for ip in ips if ip['port_id'] is None)
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
        images = list(glanceclient.images.list(filters={'name': idname}))
        if len(images) < 1:
            raise RuntimeError('no images found matching name or ID "{}"'.format(idname))
        elif len(images) > 1:
            raise RuntimeError('multiple images found matching name "{}"'.format(idname))
        else:
            return images[0]


class Server(object):
    """
    Launches an instance on a lease.
    """
    def __init__(self, lease, key='default', image=DEFAULT_IMAGE, **extra):
        self.lease = lease
        self.session = self.lease.session
        self.neutron = NeutronClient(session=self.session, region_name=os.environ.get('OS_REGION_NAME'))
        self.nova = NovaClient('2', session=self.session, region_name=os.environ.get('OS_REGION_NAME'))
        self.glance = GlanceClient('2', session=self.session, region_name=os.environ.get('OS_REGION_NAME'))
        self.ip = None
        self._fip = None

        self.image = resolve_image_idname(self.glance, image)

        net_ids = extra.pop('net_ids', None)
        net_name = extra.pop('net_name', None)
        if net_ids is None and net_name is not None:
            net_ids = [get_networkid_byname(self.neutron, net_name)]

        self.server_kwargs = instance_create_args(
            self.lease.reservation, key=key, image=self.image, net_ids=net_ids,
            **extra
        )
        self.server = self.nova.servers.create(**self.server_kwargs)
        self.id = self.server.id
        self.name = self.server.name
        # print('created instance {}'.format(self.server.id))

    def __repr__(self):
        netloc = urllib.parse.urlsplit(self.session.auth.auth_url).netloc
        if netloc.endswith(':5000'):
            # drop if default port
            netloc = netloc[:-5]
        return '<{} \'{}\' on {} ({})>'.format(self.__class__.__name__, self.name, netloc, self.id)

    def refresh(self):
        now = time.monotonic()
        try:
            lr = self._last_refresh
        except AttributeError:
            pass # expected failure on first pass
        else:
            # limit refreshes to once/sec.
            if now - lr < 1:
                return

        self.server.get()
        self._last_refresh = now

    @property
    def status(self):
        self.refresh()
        return self.server.status

    @property
    def ready(self):
        return self.status == 'ACTIVE'

    @property
    def error(self):
        return self.status == 'ERROR'

    def wait(self):
        # check a couple for fast failures
        for _ in range(3):
            time.sleep(10)
            if self.error:
                raise ServerError(self.server.fault, self.server)
        time.sleep(5 * 60)
        for _ in range(100):
            time.sleep(10)
            if self.ready:
                break
            if self.error:
                raise ServerError(self.server.fault, self.server)
        else:
            raise RuntimeError('timeout, server failed to start')
        # print('server active')

    def associate_floating_ip(self):
        created, self._fip = get_create_floatingip(self.neutron)
        self.ip = self._fip['floating_ip_address']
        try:
            self.server.add_floating_ip(self.ip)
        except AttributeError:
            # using method from https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/api/neutron.py#L518
            ports = self.neutron.list_ports(**{'device_id': self.id}).get('ports')
            fip_target = {
                'port_id': ports[0]['id'],
                'ip_addr': ports[0]['fixed_ips'][0]['ip_address']
            }
            # https://github.com/ChameleonCloud/horizon/blob/f5cf987633271518970b24de4439e8c1f343cad9/openstack_dashboard/dashboards/project/instances/tables.py#L671
            target_id = fip_target['port_id']
            self.neutron.update_floatingip(self._fip['id'], body={
                'floatingip': {
                    'port_id': target_id,
                    # 'fixed_ip_address': ip_address,
                }
            })
        return self.ip

    def delete(self):
        self.server.delete()
        # wait for deletion complete
        for _ in range(30):
            time.sleep(60)
            try:
                self.server.get()
            except Exception as e:
                if "HTTP 404" in str(e):
                    return
        else:
            raise RuntimeError('timeout, server failed to terminate')    

    def rebuild(self, idname):
        self.image = resolve_image_idname(self.glance, idname)
        self.server.rebuild(self.image)
