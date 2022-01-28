# Copyright 2021 University of Chicago
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from collections import namedtuple
from datetime import datetime
import pytest

from chi.container import DEFAULT_IMAGE_DRIVER, DEFAULT_NETWORK


@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


def example_create_container():
    """Launch a container.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [create_container](../modules/container.html#chi.container.create_container)
    * [get_device_reservation](../modules/lease.html#chi.lease.get_device_reservation)

    </div>

    """
    from chi.lease import get_device_reservation
    from chi.container import create_container

    # We assume a lease has already been created, for example with
    # ``chi.lease.create_lease```
    lease_name = "my_lease"
    container_name = "my_container"
    reservation_id = get_device_reservation(lease_name)
    container = create_container(
        container_name,
        image="centos:8",
        reservation_id=reservation_id,
    )


def test_example_create_container(mocker):
    zun = mocker.patch("chi.container.zun")()

    def get_network_id(network_name):
        assert network_name == DEFAULT_NETWORK
        return "network-id"

    mocker.patch("chi.container.get_network_id", side_effect=get_network_id)
    mocker.patch("chi.lease.get_device_reservation", return_value="reservation-id")
    Container = namedtuple("Container", ["uuid", "name", "status"])
    mocker.patch(
        # Fake that the container is already created
        "chi.container.get_container",
        return_value=Container("fake-uuid", "my-container", "Created"),
    )

    example_create_container()

    zun.containers.create.assert_called_once_with(
        name="my_container",
        image="centos:8",
        image_driver=DEFAULT_IMAGE_DRIVER,
        hints={"reservation": "reservation-id"},
        nets=[{"network": "network-id"}],
        environment=None,
        exposed_ports=None,
        runtime=None,
        device_profiles=None,
    )
