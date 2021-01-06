.. _server-module:

==========
chi.server
==========

The :mod:`chi.server` module exposes both a functional interface and an
object-oriented interface for interacting with server instances.

Functional interface
====================

Any of the following functions can be directly imported and used individually:

.. code-block:: python

  from chi.server import get_server

  s = server.get_server('my-server-name')

.. automodule:: chi.server
   :members:

Object-oriented interface
=========================

The :class:`~chi.server.Server` abstraction has been available historically for
those who wish to use something with more of an OOP flavor.

.. autoclass:: chi.server.Server
   :members:
