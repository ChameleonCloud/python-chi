from dataclasses import dataclass
from typing import List

import manilaclient
import swiftclient

from chi.clients import manila
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
