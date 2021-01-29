from .clients import glance

from glanceclient.exc import NotFound

__all__ = [
    'get_image',
    'get_image_id',
    'list_images',
]


def get_image(ref):
    """Get an image by its ID or name.

    Args:
        ref (str): The ID or name of the image.

    Returns:
        The image matching the ID or name.

    Raises:
        NotFound: If the image could not be found.
    """
    try:
        return glance().images.get(ref)
    except NotFound:
        return glance().images.get(get_image_id(ref))


def get_image_id(name):
    """Look up an image's ID from its name.

    Args:
        name (str): The name of the image.

    Returns:
        The ID of the found image.

    Raises:
        ValueError: If the image could not be found, or if multiple images
            matched the name.
    """
    images = list(glance().images.list(filters={'name': name}))
    if not images:
        raise ValueError(f'No images found matching name "{name}"')
    elif len(images) > 1:
        raise ValueError(f'Multiple images found matching name "{name}"')
    return images[0].id


def list_images():
    """List all images under the current project.

    Returns:
        All images associated with the current project.
    """
    return list(glance().images.list())
