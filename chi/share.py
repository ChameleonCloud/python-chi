from .clients import manila

from manilaclient.exceptions import NotFound

__all__ = [
    'create_share',
    'delete_share',
    'extend_share',
    'get_access_rules',
    'get_share',
    'get_share_id',
    'list_shares',
    'shrink_share',
]


def _get_default_share_type_id():
    # we only support one share type - cephfsnfstype
    share_types = manila().share_types.list()
    if not share_types:
        raise ValueError("No share types found")
    elif len(share_types) > 1:
        raise ValueError("Multiple share types found")
    return share_types[0].id


def create_share(size, name=None, description=None, metadata=None,
                 is_public=False, wrapped_call: bool = False, **kwargs):
    """Create a share.

    Args:
        size (int): size in GiB.
        name (str): name of new share.
        description (str): description of a share.
        is_public (bool): whether to set share as public or not.
        wrapped_call (bool): Whether the function was called from within
            its associated ensure wrapper. Set to True to bypass ensure
            wrapper call (not recommended). (Default False).
        all kwargs of ensure_container.

    Returns:
        The created share.
    """
    if not wrapped_call:
        ensure_share(share_name=name, **kwargs)
    share = manila().shares.create(
        share_proto="NFS",
        size=size,
        name=name,
        description=description,
        metadata=metadata,
        share_type=_get_default_share_type_id(),
        is_public=is_public
    )
    return share


def ensure_share(share_name: str, **kwargs):
    """Get a share with name if it exists, create a new one if not.

    Args:
        share_name (str): The name or ID of the share.
        all kwargs of create_share.

    Returns:
        The existing share if found, a new share if not.
    """
    try:
        current_share = get_share(share_name)
    except NotFound:
        print(f"Unable to get share named {share_name}")
        try:
            new_share = create_share(name=share_name, wrapped_call=True,
                                     **kwargs)
        except Exception as ex:
            print(f"Unable to create new share named {share_name}")
            raise ex
        else:
            print(f"Using new share named {share_name}")
            return new_share
    else:
        print(f"Using existing share named {share_name}")
        return current_share


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
    shares = list(manila().shares.list(filters={'name': name}))
    if not shares:
        raise ValueError(f'No shares found matching name "{name}"')
    elif len(shares) > 1:
        raise ValueError(f'Multiple shares found matching name "{name}"')
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
