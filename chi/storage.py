from dataclasses import dataclass
from typing import List

import manilaclient
import swiftclient

from chi import storage
from chi.clients import cinder, manila
from chi.context import session
from chi.exception import CHIValueError, ResourceError


def _get_default_share_type_id():
    # we only support one share type - cephfsnfstype
    share_types = manila().share_types.list()
    if not share_types:
        raise CHIValueError("No share types found")
    elif len(share_types) > 1:
        raise ResourceError("Multiple share types found")
    return share_types[0].id


class Share:
    """Represents a manilla share

    Args:
        name (str): name of new share.
        size (int): size in GiB.
        description (str): description of a share.
        metadata (str): metadata for the share.
        is_public (bool): whether to set share as public or not.

    Fields:
        id (str): id of the share
        export_locations: list of mount paths
    """

    def __init__(
        self,
        name: str,
        size: int,
        description: str = None,
        metadata: str = None,
        is_public: bool = False,
    ):
        self.name = name
        self.size = size
        self.description = description
        self.metadata = metadata
        self.is_public = is_public

    def _from_manilla_share(cls, share):
        s = cls(
            share.name, share.size, share.description, share.metadata, share.is_public
        )
        s.id = share.id
        s.export_locations = share.export_locations
        pass

    def submit(
        self,
        idempotent: bool = False,
    ):
        """
        Create the share.

        Args:
            idempotent (bool, optional): Whether to create the share only if it doesn't already exist.
        """
        # TODO
        if idempotent:
            pass
        share = manila().shares.create(
            share_proto="NFS",
            size=self.size,
            name=self.name,
            description=self.description,
            metadata=self.metadata,
            share_type=_get_default_share_type_id(),
            is_public=self.is_public,
        )
        self.id = share.id
        self.export_locations = share.export_locations
        return share

    def delete(self):
        """Delete the share."""

        manila().shares.delete(self.id)

    def extend(self, new_size: int):
        """Extend the size of the specific share.

        Args:
            new_size: desired size to extend share to.
        """
        manila().shares.extend(self.id, new_size)

    def shrink(self, new_size: int):
        """Shrink the size of the specific share.

        Args:
            new_size: desired size to extend share to.
        """

        manila().shares.shrink(self.id, new_size)


def list_shares() -> List[Share]:
    """Get a list of all available flavors.

    Returns:
        A list of all flavors.
    """
    return [Share._from_manilla_share(s) for s in manila().shares.list()]


def get_share(ref) -> Share:
    """Get a share by its ID or name.

    Args:
        ref (str): The ID or name of the share.

    Returns:
        The share matching the ID or name.

    Raises:
        NotFound: If the share could not be found.
    """

    try:
        share = manila().shares.get(ref)
    except manilaclient.exceptions.NotFound:
        shares = list(manila().shares.list(search_opts={"name": ref}))
        if not shares:
            raise CHIValueError(f'No shares found matching name "{ref}"')
        elif len(shares) > 1:
            raise ResourceError(f'Multiple shares found matching name "{ref}"')
        share = shares[0]
    return Share._from_manilla_share(share)


@dataclass
class Object:
    container: str
    name: str
    size: int

    def download(self, file_dest: str):
        conn = swiftclient.Connection(session=session())
        obj_tuple = conn.get_object(self.container, self.name)
        object_content = obj_tuple[1]
        with open(file_dest, "wb") as f:
            f.write(object_content)


class ObjectBucket:
    """Class representing an object store bucket

    Args:
        name (str): name of the bucket
    """

    def __init__(self, name: str):
        self.name = name

    def submit(self, idempotent: bool = False):
        conn = swiftclient.Connection(session=session())
        # TODO idempotent
        conn.put_container(self.name)

    def list_objects(self) -> List[Object]:
        conn = swiftclient.Connection(session=session())
        container_info, res_objects = conn.get_container(self.name)
        objects = []
        for obj in res_objects:
            objects.append(
                Object(container=self.name, name=obj["name"], size=obj["bytes"])
            )
        return objects

    def upload(self, file_src: str):
        self.swift = swiftclient.service.SwiftService()
        self.upload_object = swiftclient.service.SwiftUploadObject(
            file_src, object_name=self.name
        )

    def download(self, object_name: str, file_dest: str):
        Object(container=self.name, name=object_name).download(file_dest)


def list_buckets() -> List[ObjectBucket]:
    swift_conn = swiftclient.client.Connection(session=session())
    resp_headers, containers = swift_conn.get_account()

    buckets = []
    for container in containers:
        buckets.append(ObjectBucket(container["name"]))
    return buckets


class Volume:
    """Represents an OpenStack Cinder volume

    Args:
        name (str): name of the new volume.
        size (int): size in GiB.
        description (str): description of the volume.
        metadata (str): metadata for the volume.
        volume_type (str): type of the volume.

    Fields:
        id (str): id of the volume
        status (str): status of the volume
    """

    def __init__(
        self,
        name: str,
        size: int,
        description: str = None,
        metadata: str = None,
        volume_type: str = "ceph-ssd",
    ):
        self.name = name
        self.size = size
        self.description = description
        self.metadata = metadata
        self.volume_type = volume_type

    @classmethod
    def _from_cinder_volume(cls, volume):
        v = cls(
            volume.name,
            volume.size,
            volume.description,
            volume.metadata,
            volume.volume_type,
        )
        v.id = volume.id
        v.status = volume.status
        return v

    def submit(self, idempotent: bool = False):
        """Create the volume."""
        volume = None
        if idempotent:
            for v in storage.list_volumes():
                if v.name == self.name:
                    volume = v
                    break
        if not volume:
            volume = cinder().volumes.create(
                size=self.size,
                name=self.name,
                description=self.description,
                metadata=self.metadata,
                volume_type=self.volume_type,
            )
        self.id = volume.id
        self.status = volume.status
        return volume

    def delete(self):
        """Delete the volume."""
        cinder().volumes.delete(self.id)

    def get(self):
        """Retrieve the volume details."""
        volume = cinder().volumes.get(self.id)
        return self._from_cinder_volume(volume)


def list_volumes() -> List[Volume]:
    """Get a list of all available volumes.

    Returns:
        A list of all volumes.
    """
    return [Volume._from_cinder_volume(v) for v in cinder().volumes.list()]


def get_volume(ref) -> Volume:
    """Get a volume by its ID or name.

    Args:
        ref (str): The ID or name of the volume.

    Returns:
        The volume matching the ID or name.

    Raises:
        CHIValueError: If no volumes are found matching the name.
        ResourceError: If multiple volumes are found matching the name.
    """
    try:
        volume = cinder().volumes.get(ref)
    except cinder.exceptions.NotFound:
        volumes = list(cinder().volumes.list(search_opts={"name": ref}))
        if not volumes:
            raise CHIValueError(f'No volumes found matching name "{ref}"')
        elif len(volumes) > 1:
            raise ResourceError(f'Multiple volumes found matching name "{ref}"')
        volume = volumes[0]
    return Volume._from_cinder_volume(volume)
