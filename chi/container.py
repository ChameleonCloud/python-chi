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
import os
import tarfile
import time
from typing import Dict, List, Optional, Tuple

from IPython.display import HTML, display
from packaging.version import Version
from zunclient.exceptions import NotFound

from chi import context, util
from chi import network as chi_network

from .clients import connection, zun
from .context import session
from .exception import ResourceError, ServiceError
from .network import bind_floating_ip, get_free_floating_ip

DEFAULT_IMAGE_DRIVER = "docker"
DEFAULT_NETWORK = "containernet1"
LOG = logging.getLogger(__name__)


class Container:
    """
    Represents a container in the system.

    Args:
        name (str): The name of the container.
        image_ref (str): The reference to the container image.
        exposed_ports (List[str]): A list of ports exposed by the container.
        reservation_id (str, optional): The reservation ID associated with the container. Defaults to None.
        start (bool, optional): Indicates whether to start the container. Defaults to True.
        start_timeout (int, optional): The timeout value for starting the container. Defaults to None.
        runtime (str, optional): The runtime environment for the container. Defaults to None.
        command (List[str], optional): The command to run inside the container.
        workdir (str, optional): The workdir to use in the container.

    Attributes:
        name (str): The name of the container.
        image_ref (str): The reference to the container image.
        exposed_ports (List[str]): A list of ports exposed by the container.
        reservation_id (str): The reservation ID associated with the container.
        start (bool): Indicates whether to start the container.
        start_timeout (int): The timeout value for starting the container.
        runtime (str): The runtime environment for the container.
        id (str): The ID of the container.
        created_at (str): The timestamp when the container was created.
        status (str): The current status of the container.
        environment (Dict[str, str]): A dictionary of environment variables for the container.
        device_profiles (List[str]): A list of device profiles to be configured on the container.
    """

    def __init__(
        self,
        name: str,
        image_ref: str,
        exposed_ports: List[str],
        reservation_id: str = None,
        start: bool = True,
        start_timeout: int = 0,
        runtime: str = None,
        command: List[str] = None,
        workdir: str = None,
        environment: Dict[str, str] = {},
        device_profiles: List[str] = [],
    ):
        self.name = name
        self.image_ref = image_ref
        self.exposed_ports = exposed_ports
        self.reservation_id = reservation_id
        self.start = start
        self.start_timeout = start_timeout
        self.runtime = runtime
        self.id = None
        self.created_at = None
        self._status = None
        self.command = command
        self.workdir = workdir
        self.environment = environment
        self.device_profiles = device_profiles

    @classmethod
    def from_zun_container(cls, zun_container):
        container = cls(
            name=zun_container.name,
            image_ref=zun_container.image,
            exposed_ports=zun_container.ports if zun_container.ports else [],
            start=True,  # Assuming the container is already created
        )
        container.id = zun_container.uuid
        container._status = zun_container.status
        return container

    @property
    def status(self):
        if self.id:
            container = zun().containers.get(self.id)
            self._status = container.status
        return self._status

    def submit(
        self,
        wait_for_active: bool = True,
        wait_timeout: int = 5 * 60,
        show: str = "widget",
        idempotent: bool = False,
    ):
        """
        Submits the container for creation and performs additional actions based on the provided parameters.

        Args:
            wait_for_active (bool, optional): Whether to wait for the container to become active. Defaults to True.
            wait_timeout (int, optional): The maximum time (in seconds) to wait for the container to become active. Defaults to 5 minutes.
            show (str, optional): The type of output to display. Defaults to "widget".
            idempotent (bool, optional): Whether to update the existing container if it already exists. Defaults to False.

        Raises:
            ResourceError: If the container creation fails.

        Returns:
            None
        """
        if idempotent:
            existing = get_container(self.name)
            if existing:
                if wait_for_active:
                    existing.wait(status="Running", timeout=wait_timeout)
                if show:
                    existing.show(type=show, wait_for_active=wait_for_active)
                return existing
        kwargs = {}
        if self.command:
            kwargs["command"] = self.command
        if self.workdir:
            kwargs["workdir"] = self.workdir

        container = create_container(
            name=self.name,
            image=self.image_ref,
            exposed_ports=self.exposed_ports,
            reservation_id=self.reservation_id,
            start=self.start,
            start_timeout=self.start_timeout,
            runtime=self.runtime,
            environment=self.environment,
            device_profiles=self.device_profiles,
            **kwargs,
        )

        if container:
            self.id = zun().containers.get(self.name).uuid
            self._status = zun().containers.get(self.name).status
        else:
            raise ResourceError("could not create container")

        if wait_for_active and self.status != "Running":
            self.wait(status="Running", timeout=wait_timeout)

        if show:
            self.show(type=show, wait_for_active=wait_for_active)

    def delete(self):
        """
        Deletes the container.

        If the container has an ID, it calls the `destroy_container` function to delete the container.
        After deletion, it sets the ID and status of the container to None.

        Args:
            None

        Returns:
            None
        """
        if self.id:
            destroy_container(self.id)
            self.id = None
            self._status = None

    def wait(
        self, status: str = "Running", show: str = "widget", timeout: int = 5 * 60
    ):
        """
        Waits for the container to reach the specified status.

        Args:
            status (str, optional): The status to wait for. Defaults to "Running".
            show (str, optional): The type of container information to display after creation. Defaults to "widget".
            timeout (int, optional): The maximum time to wait in seconds. Defaults to 5 minutes.

        Returns:
            None
        """

        pb = util.TimerProgressBar()
        if show == "widget" and context._is_ipynb():
            pb.display()

        def _callback():
            # self.status is a property that refreshes itself
            # NOTE: zun statuses are title case
            if self.status.upper() == status.upper() or self.status == "Error":
                print(f"Container has moved to status {self.status}")
                return True
            return False

        res = pb.wait(_callback, 2 * 60, timeout)
        if not res:
            raise ServiceError(
                f"Timeout waiting for container to reach {status} status"
            )

    def show(self, type: str = "text", wait_for_active: bool = False):
        """
        Display information about the container.

        Args:
            type (str, optional): The type of display. Can be "text" or "widget". Defaults to "text".
            wait_for_active (bool, optional): Whether to wait for the container to be in the "Running" state before displaying information. Defaults to False.
        """
        if wait_for_active and self.status != "Running":
            self.wait(status="Running")

        zun_container = get_container(self.id)

        if type == "text":
            print(f"Container: {self.name}")
            print(f"ID: {self.id}")
            print(f"Status: {zun_container.status}")
            print(f"Image: {self.image_ref}")
            print(f"Created at: {self.created_at}")
        elif type == "widget":
            self._show_html_table(zun_container)

    def _show_html_table(self, zun_container):
        container_details = {
            "Name": self.name,
            "ID": self.id,
            "Status": zun_container.status,
            "Image": self.image_ref,
            "Created at": str(self.created_at),
            "Exposed Ports": self.exposed_ports if self.exposed_ports else "None",
            "Reservation ID": self.reservation_id if self.reservation_id else "None",
            "Runtime": self.runtime if self.runtime else "Default",
        }

        html_table = """
        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <th style="border: 1px solid black; padding: 8px; text-align: left; background-color: #f2f2f2;">Property</th>
                <th style="border: 1px solid black; padding: 8px; text-align: left; background-color: #f2f2f2;">Value</th>
            </tr>
            {rows}
        </table>
        """

        rows = ""
        for key, value in container_details.items():
            rows += f"""
            <tr>
                <td style="border: 1px solid black; padding: 8px;">{key}</td>
                <td style="border: 1px solid black; padding: 8px;">{value}</td>
            </tr>
            """

        html_table = html_table.format(rows=rows)
        display(HTML(html_table))

    def execute(self, command: str) -> Tuple[str, str]:
        """
        Executes a command inside the container and returns the output and exit code.

        Args:
            command (str): The command to be executed inside the container.

        Returns:
            Tuple[str, str]: A tuple containing the output of the command and the exit code.
        """
        result = execute(self.id, command)
        return result.get("output", ""), str(result.get("exit_code", ""))

    def upload(self, source: str, remote_dest: str) -> None:
        """
        Uploads a file from the local machine to the remote destination in the container.

        Args:
            source (str): The path of the file on the local machine.
            remote_dest (str): The destination path in the container where the file will be uploaded.

        Returns:
            None
        """
        upload(self.id, source, remote_dest)

    def download(self, remote_source: str, dest: str) -> None:
        """
        Downloads a file from a remote source to the specified destination.

        Args:
            remote_source (str): The URL or path of the remote file to download.
            dest (str): The destination path where the file will be saved.

        Returns:
            None
        """
        download(self.id, remote_source, dest)

    def associate_floating_ip(self, fip: str = None):
        """
        Associates a floating IP with the container.

        Args:
            fip (str, optional): The floating IP to associate with the container. Defaults to None.

        Returns:
            The result of the association operation.
        """
        return associate_floating_ip(self.id, fip)

    def detach_floating_ip(self, fip: str) -> None:
        """
        Detaches and deletes a floating IP from the container.

        Args:
            fip (str): The floating IP to detach.
            delete (Optional[bool], optional): Whether to delete the floating IP after disassociation. Defaults to True.

        Returns:
            None
        """
        conn = connection(session=session())
        floating_ip_obj = chi_network.get_floating_ip(fip)
        conn.network.delete(floating_ip_obj["id"])

    def logs(self, stdout: str = True, stderr: str = True) -> str:
        """
        Print all logs outputted by the container.

        Args:
            container_ref (str): The name or ID of the container.
            stdout (bool): Whether to include stdout logs. Default True.
            stderr (bool): Whether to include stderr logs. Default True.

        Returns:
            A string containing all log output. Log lines will be delimited by
                newline characters.
        """
        return get_logs(self.id, stdout=stdout, stderr=stderr)


def create_container(
    name: "str",
    image: "str" = None,
    exposed_ports: "list[str]" = None,
    reservation_id: "str" = None,
    start: "bool" = True,
    start_timeout: "int" = None,
    platform_version: "int" = 2,
    **kwargs,
):
    """
    .. deprecated:: 1.0

    Create a container instance.

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
    # handling of it in the Zu      n client; it is not sent if it is not on kwargs.
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


def list_containers() -> List[Container]:
    """
    Retrieve a list of containers.

    Returns:
        A list of Container objects representing the containers.
    """
    if Version(context.version) >= Version("1.0"):
        zun_containers = zun().containers.list()
        return [Container.from_zun_container(c) for c in zun_containers]
    return zun().containers.list()


def get_container(name: str) -> Optional[Container]:
    """
    Retrieve a container by name.

    Args:
        name (str): The name of the container to retrieve.

    Returns:
        Optional[Container]: The retrieved container object, or None if the container does not exist.
    """
    if Version(context.version) >= Version("1.0"):
        try:
            zun_container = zun().containers.get(name)
        except NotFound:
            return None
        return Container.from_zun_container(zun_container)
    return zun().containers.get(name)


def snapshot_container(
    container_ref: "str", repository: "str", tag: "str" = "latest"
) -> "str":
    """
    .. deprecated:: 1.0

    Create a snapshot of a running container.

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
    """
    .. deprecated:: 1.0

    Delete the container.

    This will automatically stop the container if it is currently running.

    Args:
        container_ref (str): The name or ID of the container.
    """
    return zun().containers.delete(container_ref, stop=True)


def get_logs(container_ref: "str", stdout=True, stderr=True):
    """
    .. deprecated:: 1.0

    Print all logs outputted by the container.

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
    """
    .. deprecated:: 1.0

    Execute a one-off process inside a running container.

    Args:
        container_ref (str): The name or ID of the container.
        command (str): The command to run.

    Returns:
        A summary of the output of the command, with "output" and "exit_code".
    """
    return zun().containers.execute(container_ref, command=command, run=True)


def upload(container_ref: "str", source: "str", dest: "str") -> "dict":
    """
    .. deprecated:: 1.0

    Upload a file or directory to a running container.

    This method requires your running container to include
    the GNU tar utility.

    Args:
        container_ref (str): The name or ID of the container.
        source (str): The (local) path to the file or directory to upload.
        dest (str): The (container) path to upload the file or directory to.
    """
    fd = io.BytesIO()
    with tarfile.open(fileobj=fd, mode="w") as tar:
        tar.add(source, arcname=os.path.basename(source))
    fd.seek(0)
    data = fd.read()
    fd.close()
    return zun().containers.put_archive(container_ref, dest, data)


def download(container_ref: "str", source: "str", dest: "str"):
    """
    .. deprecated:: 1.0

    Download a file or directory from a running container.

    This method requires your running container to include
    both the POSIX sh and GNU tar utilities.

    Args:
        container_ref (str): The name or ID of the container.
        source (str): The (container) path of the file or directory.
        dest (str): The (local) path to download to.
    """
    res = zun().containers.get_archive(container_ref, source)
    fd = io.BytesIO(res["data"])
    with tarfile.open(fileobj=fd, mode="r") as tar:
        tar.extraction_filter = lambda member, path: member
        tar.extractall(dest)


def wait_for_active(container_ref: "str", timeout: int = (60 * 2)) -> "Container":
    """
    .. deprecated:: 1.0

    Wait for a container to transition to the running state.

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
    print(
        f"Waiting for container {container_ref} status to turn to Running. This can take a while depending on the image"
    )
    start_time = time.perf_counter()

    while True:
        container = zun().containers.get(container_ref)
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
    """
    .. deprecated:: 1.0

    Assign a Floating IP address to a container.

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
