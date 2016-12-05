=======================
Bag o' Hammers
=======================

    *Percussive maintenance.*

Collection of various tools to keep things ship-shape. Not particularly bright tools, but good for a first-pass.

1. Neutron resource reaper

  ``neutron-reaper {ip, port} <grace-days> [--info]``

  Reclaims idle floating IPs and cleans up stale ports. Pipe into ``neutron`` to act upon what it finds.

2. Conflicting Ironic/Neutron MACs

  ``conflict-macs {info, delete}``

Common options:

* ``--slack <json-options>`` - if provided, used to post notifications to Slack
* ``--osrc <rc-file>`` - alternate way to feed in the OS authentication vars

-----

Puppet with a bag of hammers::

  package { 'bag-o-hammers':
      provider => pip,
      name     => hammers,
      ensure   => 0.1.3,
  }
