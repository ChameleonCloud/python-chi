==========================
Chameleon Cloud Python API
==========================

``python-chi`` is a Python library that can help you interact with the
`Chameleon testbed <https://www.chameleoncloud.org>`_ to improve your
workflows with automation. It additionally pairs well with environments like
Jupyter Notebooks.

Installation
============

.. figure:: https://img.shields.io/pypi/v/python-chi
   :target: https://pypi.org/project/python-chi/

.. code-block:: shell

   pip install python-chi

Authentication
==============

Environment variables are the primary authentication method. Please refer to
the `documentation on OpenRC scripts
<https://chameleoncloud.readthedocs.io/en/latest/technical/cli.html#the-openstack-rc-script>`_
to learn more about how to download and source your authentication credentials
for the CLI; the same instructions apply for using the Python interface.

Basic usage
===========

The following example shows how to make a reservation for a bare metal server.
For more details about the modules available refer to their respective pages.

.. code-block:: python

  import chi

  # Select your project
  chi.set('project_name', 'CH-XXXXXX')
  # Select your site
  chi.use_site('CHI@UC')

  # Make a reservation ...
  reservations = []
  # ... for one node of type "compute_skylake"
  chi.lease.add_node_reservation(
      reservations, node_type='compute_skylake', count=1)
  # ... and one Floating IP
  chi.lease.add_fip_reservation(count=1)
  # ... for one day.
  start_date, end_date = chi.lease.lease_duration(days=1)
  chi.lease.create_lease(
      lease_name, reservations, start_date=start_date, end_date=end_date)

.. toctree::
   :caption: Modules
   :maxdepth: 1

   modules/context
   modules/lease
   modules/server
   modules/network
   modules/image
   modules/container

.. toctree::
   :caption: Examples
   :glob:

   notebooks/*


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
