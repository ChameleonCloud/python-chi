from manilaclient.exceptions import NotFound

from .clients import manila
from .exception import CHIValueError, ResourceError


def _get_default_share_type_id():
    # we only support one share type - cephfsnfstype
    share_types = manila().share_types.list()
    if not share_types:
        raise CHIValueError("No share types found")
    elif len(share_types) > 1:
        raise ResourceError("Multiple share types found")
    return share_types[0].id


def create_share(size, name=None, description=None, metadata=None, is_public=False):
    """Create a share.

    Args:
        size (int): size in GiB.
        name (str): name of new share.
        description (str): description of a share.
        is_public (bool): whether to set share as public or not.

    Returns:
        The created share.
    """
    share = manila().shares.create(
        share_proto="NFS",
        size=size,
        name=name,
        description=description,
        metadata=metadata,
        share_type=_get_default_share_type_id(),
        is_public=is_public,
    )
    return share


def delete_share(share):
    """Delete a share.

    Args:
        share: either share object or text with its ID.
    """
    manila().shares.delete(share)


def extend_share(share, new_size):
    """Extend the size of the specific share.

    Args:
        share: either share object or text with its ID.
        new_size: desired size to extend share to.
    """
    manila().shares.extend(share, new_size)


def get_access_rules(share):
    """Get access list to a share.

    Args:
        share: either share object or text with its ID.

    Returns:
        A list of access rules.
    """
    return manila().shares.access_list(share)


def get_share(ref):
    """Get a share by its ID or name.

    Args:
        ref (str): The ID or name of the share.

    Returns:
        The share matching the ID or name.

    Raises:
        NotFound: If the share could not be found.
    """
    try:
        return manila().shares.get(ref)
    except NotFound:
        return manila().shares.get(get_share_id(ref))


def get_share_id(name):
    """Look up a share's ID from its name.

    Args:
        name (str): The name of the share.

    Returns:
        The ID of the found share.

    Raises:
        ValueError: If the share could not be found, or if multiple shares
            matched the name.
    """
    shares = list(manila().shares.list(search_opts={"name": name}))
    if not shares:
        raise CHIValueError(f'No shares found matching name "{name}"')
    elif len(shares) > 1:
        raise ResourceError(f'Multiple shares found matching name "{name}"')
    return shares[0].id


def list_shares():
    """List all shares under the current project.

    Returns:
        All shares associated with the current project.
    """
    return list(manila().shares.list())


def shrink_share(share, new_size):
    """Shrink the size of the specific share.

    Args:
        share: either share object or text with its ID.
        new_size: desired size to shrink share to.
    """
    manila().shares.shrink(share, new_size)
