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

3. Undead Instances

  ``undead-instances {info, delete}``

  Nova instances that have been put to rest but still cling to Ironic nodes, preventing the next generation from being...ensouled? Checks for the inconsistency and fixed it.

4. IPMI Retry

  ``ipmi-retry {info, reset}``

  Resets Ironic nodes in error state with a known, common error. Records those resets on the node metadata (``extra`` field) and refuses after a magic number of attempts.

Common options:

* ``--slack <json-options>`` - if provided, used to post notifications to Slack
* ``--osrc <rc-file>`` - alternate way to feed in the OS authentication vars
