===================
Python-chi Examples
===================

.. _examples:

Cleanup Non-leased Resources
============================

While baremetal nodes on Chameleon require leases, other resources like networks, and KVM instances
are persistent, and require manual cleanup. For large projects (e.g. for educational courses), it
may be useful to have some automatic process to clean up resources after a certain time. Below is
a suggested method for managing this. First, when creating the resource, or to prolong the resource,
you can set a "delete_at" tag. This is simply an date string in the future, which can be checked.

.. code-block:: python

  # Set a Server metadata item, which will be read leader
  my_server.set_metadata_item("delete_at", util.date_string_in_future(days=3))

  # Similarly, use "tag" for network or floating ip
  network.set_floating_ip_tag(MY_FIP_ADDRESS, f"delete_at={util.date_string_in_future(days=3)}")
  network.set_network_tag(MY_NETWORK_ID, f"delete_at={util.date_string_in_future(days=3)}")

Then, set up the following script to run periodically using something like cron. You'll need
to set authentication variables (e.g. source an openrc file), and set the site/project. This script
iterates over the resources in your project, and deletes them if the "delete_at" tag is in the past.

.. code-block:: python

  from chi import util, server, network

  # Find servers with "delete_at" metadata
  for s in server.list_servers():
    if util.should_delete(my_servers.get_metadata().get("delete_at", "")):
      s.delete()

  # Networks, FIP tags set via tags as a string
  for net in network.list_networks():
    try:
      delete_tag = next(s for s in net["tags"] if s.startswith("delete_at="))
      if util.should_delete(delete_tag.split("=")[1]):
        network.nuke_network(net_id)
    except StopIteration:
      pass

  for fip in network.list_floating_ips():
    try:
      delete_tag = next(s for s in fip["tags"] if s.startswith("delete_at="))
      if util.should_delete(delete_tag.split("=")[1]):
        network.deallocate_floating_ip(fip["floating_ip_address"])
    except StopIteration:
      pass