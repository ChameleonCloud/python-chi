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

import io
import logging
import tarfile
import time
import typing

from .clients import zun
from .network import bind_floating_ip, get_free_floating_ip, get_network_id

if typing.TYPE_CHECKING:
    from zunclient.v1.containers import Container

DEFAULT_IMAGE_DRIVER = "docker"
DEFAULT_NETWORK = "containernet1"
LOG = logging.getLogger(__name__)

__all__ = [
    "list_containers",
    "get_container",
    "create_container",
    "snapshot_container",
    "destroy_container",
    "get_logs",
    "execute",
    "upload",
    "wait_for_active",
]


def create_container(
    name: "str",
    image: "str" = None,
    exposed_ports: "list[str]" = None,
    reservation_id: "str" = None,
    start: "bool" = True,
    start_timeout: "int" = None,
    platform_version: "int" = 2,
    **kwargs,
) -> "Container":
    """Create a container instance.

    Args:
        name (str): The name to give the container.
        image (str): The Docker image, with or without tag information. If no
            tag is provided, "latest" is assumed.
        device_profiles (list[str]): An optional list of device profiles to
            request be configured on the container when it is created. Edge
            devices may have differing sets of supported device profiles, so
            it is important to understand which profiles are supported by the
            target device for your container.
        environment (dict): A set of environment variables to pass to the
            container.
        exposed_ports (list[str]): A list of ports to expose on the container.
            TCP or UDP can be provided with a slash prefix, e.g., "80/tcp" vs.
            "53/udp". If no protocol is provided, TCP is assumed.
        host (str): The Zun host to launch a container on. If not specified,
            the host is chosen by Zun.
        runtime (str): The container runtime to use. This should only be
            overridden when explicitly launching containers onto a host/platform
            requiring a separate runtime to, e.g., pass-through GPU devices,
            such as the "nvidia" runtime provided by NVIDIA Jetson Nano/TX2.
        start (bool): Whether to automatically start the container after it
            is created. Default True.
        **kwargs: Additional keyword arguments to send to the Zun client's
            container create call.
    """
    hints = kwargs.setdefault("hints", {})
    if reservation_id:
        hints["reservation"] = reservation_id
    if platform_version:
        hints["platform_version"] = platform_version

    # Support simpler syntax for exposed_ports
    if exposed_ports and isinstance(exposed_ports, list):
        exposed_ports = {port_def: {} for port_def in exposed_ports}
    # Only set exposed_ports on the parent invocation if it is non-empty. Otherwise,
    # end-users cannot specify security groups; the client will send an explicit 'null'
    # value for this key, which will fail validation in the API layer, which expects the
    # key to be missing if security groups are specified.
    if exposed_ports:
        kwargs["exposed_ports"] = exposed_ports

    # Note: most documented args are not on the function signature because there is some special
    # handling of it in the Zun client; it is not sent if it is not on kwargs.
    # If it is on kwargs it is expected to be non-None.
    container = zun().containers.create(
        name=name,
        image=image,
        **kwargs,
    )

    # Wait for a while, the image may need to download. 30 minutes is
    # _quite_ a long time, but the user can interrupt or choose a smaller
    # timeout.
    timeout = start_timeout or (60 * 30)
    LOG.info(f"Waiting up to {timeout}s for container creation ...")

    if platform_version == 2:
        container = _wait_for_status(container.uuid, "Running", timeout=timeout)
    else:
        container = _wait_for_status(container.uuid, "Created", timeout=timeout)
        if start:
            LOG.info("Starting container ...")
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
        tag (str): An optional version to tag the container image with. If not
            defined, defaults to "latest".

    Returns:
        The container, if found.
    """
    return zun().containers.get(container_ref)


def snapshot_container(
    container_ref: "str", repository: "str", tag: "str" = "latest"
) -> "str":
    """Create a snapshot of a running container.

    This will store the container's file system in Glance as a new Image.
    You can then specify the Image ID in container create requests.

    Args:
        container_ref (str): The name or ID of the container.
        repository (str): The name to give the snapshot.
        tag (str): An optional version tag to give the snapshot. Defaults to
            "latest".
    """
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


def upload(container_ref: "str", source: "str", dest: "str") -> "dict":
    """Upload a file or directory to a running container.

    Args:
        container_ref (str): The name or ID of the container.
        source (str): The (local) path to the file or directory to upload.
        dest (str): The (container) path to upload the file or directory to.
    """
    fd = io.BytesIO()
    with tarfile.open(fileobj=fd, mode="w") as tar:
        tar.add(source, arcname=".")
    fd.seek(0)
    data = fd.read()
    fd.close()
    return zun().containers.put_archive(container_ref, dest, data)


def download(container_ref: "str", source: "str", dest: "str"):
    """Download a file or directory from a running container.

    Args:
        container_ref (str): The name or ID of the container.
        source (str): The (container) path of the file or directory.
        dest (str): The (local) path to download to.
    """
    res = zun().containers.get_archive(container_ref, source)
    fd = io.BytesIO(res["data"])
    with tarfile.open(fileobj=fd, mode="r") as tar:
        tar.extractall(dest)


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
        if container.status == "Error":
            raise RuntimeError("Container went in to error state")
        elif container.status == status:
            return container
        time.sleep(5)
        if time.perf_counter() - start_time >= timeout:
            raise TimeoutError(
                (
                    f"Waited too long for the container {container_ref} to be "
                    f"{status.lower()}."
                )
            )


def associate_floating_ip(container_ref: "str", floating_ip_address=None) -> "str":
    """Assign a Floating IP address to a container.

    The container's first address will be used for the assignment.

    Args:
        container_ref (str): The name or ID of the container.
        floating_ip_address (str): The Floating IP address, which must already
            be owned by the requesting project. If not defined, a Floating IP
            will be allocated, if there are any available.

    Returns:
        The Floating IP address, if it was bound successfully, else None.
    """
    if not floating_ip_address:
        floating_ip_address = get_free_floating_ip()["floating_ip_address"]

    container = zun().containers.get(container_ref)
    for net_id, addrs in container.addresses.items():
        port = next(iter([a["port"] for a in addrs if a["port"]]), None)
        if port:
            bind_floating_ip(floating_ip_address, port_id=port)
            return floating_ip_address

    return None
