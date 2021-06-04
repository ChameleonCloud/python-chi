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

import time
import typing

from .clients import zun
from .network import get_network_id

if typing.TYPE_CHECKING:
    from zunclient.v1.containers import Container

DEFAULT_NETWORK = "containernet1"

__all__ = [
    "list_containers",
    "get_container",
    "create_container",
    "snapshot_container",
    "destroy_container",
    "get_logs",
    "execute",
    "wait_for_active",
]


def create_container(
    name: "str",
    image: "str" = None,
    environment: "dict" = None,
    exposed_ports: "list[str]" = [],
    nets: "list[dict]" = None,
    network_id: "str" = None,
    network_name: "str" = DEFAULT_NETWORK,
    start: "bool" = True,
    **kwargs,
) -> "Container":
    """Create a container instance.

    Args:
        name (str): The name to give the container.
        image (str): The Docker image, with or without tag information. If no
            tag is provided, "latest" is assumed.
        environment (dict): A set of environment variables to pass to the
            container.
        exposed_ports (list[str]): A list of ports to expose on the container.
            TCP or UDP can be provided with a slash prefix, e.g., "80/tcp" vs.
            "53/udp". If no protocol is provided, TCP is assumed.
        nets (list[dict]): A set of network configurations. This is an advanced
            invocation; typically ``network_id`` or ``network_name`` should be
            enough, and is much simpler. Refer to the `Zun documentation
            <https://docs.openstack.org/api-ref/application-container/?expanded=create-new-container-detail#create-new-container>`_
            for information about this parameter.
        network_id (str): The ID of a network to launch the container on.
        network_name (str): The name of a network to launch the container on.
            This has no effect if ``network_id`` is already provided. Default
            "containernet1".
        start (bool): Whether to automatically start the container after it
            is created. Default True.
    """

    if not nets:
        if not network_id:
            network_id = get_network_id(network_name)
        nets = [{"network": network_id}]

    container = zun().containers.create(
        name=name,
        image=image,
        image_driver="docker",
        nets=nets,
        exposed_ports={port_def: {} for port_def in (exposed_ports or [])},
        environment=environment,
        **kwargs,
    )

    if start:
        container = _wait_for_status(container.uuid, "Created")
        zun().containers.start(container.uuid)

    return container


def list_containers() -> "list[Container]":
    """List all containers owned by this project.

    Returns:
        A list of containers.
    """
    return zun().containers.list()


def get_container(container_ref: "str") -> "Container":
    """Get a container's information.

    Args:
        container_ref (str): The name or ID of the container.

    Returns:
        The container, if found.
    """
    return zun().containers.get(container_ref)


def snapshot_container(
    container_ref: "str", repository: "str", tag: "str" = None
) -> "str":
    return zun().containers.commit(container_ref, repository, tag=tag)["uuid"]


def destroy_container(container_ref: "str"):
    """Delete the container.

    This will automatically stop the container if it is currently running.

    Args:
        container_ref (str): The name or ID of the container.
    """
    return zun().containers.delete(container_ref, stop=True)


def get_logs(container_ref: "str", stdout=True, stderr=True):
    """Print all logs outputted by the container.

    Args:
        container_ref (str): The name or ID of the container.
        stdout (bool): Whether to include stdout logs. Default True.
        stderr (bool): Whether to include stderr logs. Default True.

    Returns:
        A string containing all log output. Log lines will be delimited by
            newline characters.
    """
    return zun().containers.logs(container_ref, stdout=stdout, stderr=stderr)


def execute(container_ref: "str", command: "str") -> "dict":
    """Execute a one-off process inside a running container.

    Args:
        container_ref (str): The name or ID of the container.
        command (str): The command to run.

    Returns:
        A summary of the output of the command, with "output" and "exit_code".
    """
    return zun().containers.execute(container_ref, command=command, run=True)


def wait_for_active(container_ref: "str", timeout: int = (60 * 2)) -> "Container":
    """Wait for a container to transition to the running state.

    Args:
        container_ref (str): The name or ID of the container.
        timeout (int): How long to wait before issuing a TimeoutError.

    Raises:
        TimeoutError: if the timeout was reached before the container started.

    Returns:
        The container representation.
    """
    return _wait_for_status(container_ref, "Running", timeout=timeout)


def _wait_for_status(
    container_ref: "str", status: "str", timeout: int = (60 * 2)
) -> "Container":
    start_time = time.perf_counter()

    while True:
        container = get_container(container_ref)
        if container.status == status:
            return container
        time.sleep(5)
        if time.perf_counter() - start_time >= timeout:
            raise TimeoutError(
                (
                    f"Waited too long for the container {container_ref} to be "
                    f"{status.lower()}."
                )
            )
