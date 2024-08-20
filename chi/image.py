from .clients import glance
from .exception import CHIValueError, ResourceError

from glanceclient.exc import NotFound

__all__ = [
    'get_image',
    'get_image_id',
    'list_images',
]

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .clients import glance
from .exception import CHIValueError, ResourceError
from glanceclient.exc import NotFound

__all__ = [
    'get_image',
    'get_image_id',
    'list_images',
]

@dataclass
class Image:
    uuid: str
    created_at: datetime
    is_chameleon_supported: bool
    name: str

    @staticmethod
    def from_glance_image(glance_image) -> 'Image':
        """Convert a glance image object to an Image object.

        Args:
            glance_image: The glance image object.

        Returns:
            Image: The Image object.
        """
        if 'build-repo' in glance_image:
            return Image(
            uuid=glance_image.id,
            created_at=glance_image.created_at,
            is_chameleon_supported=(glance_image['build-repo'] == 'https://github.com/ChameleonCloud/cc-images'),
            name=glance_image.name
            )
        else:
            return Image(
            uuid=glance_image.id,
            created_at=glance_image.created_at,
            is_chameleon_supported=False,
            name=glance_image.name
            )

def list_images(is_chameleon_supported: Optional[bool] = False) -> List[Image]:
    """List all images available at the current site, filtered by support status.

    Args:
        is_chameleon_supported (bool, optional): Filter images by Chameleon support. Defaults to True.

    Returns:
        List[Image]: A list of Image objects.
    """
    if is_chameleon_supported:
        glance_images = glance().images.list(filters={'build-repo': 'https://github.com/ChameleonCloud/cc-images'})
    else:
        glance_images = glance().images.list()
    return [Image.from_glance_image(image) for image in glance_images]

def get_image(name: str) -> Image:
    """Get an image by its name.

    Args:
        name (str): The name of the image.

    Returns:
        Image: The Image object matching the name.

    Raises:
        CHIValueError: If no image is found with the given name.
        ResourceError: If multiple images are found with the same name.
    """
    glance_images = list(glance().images.list(filters={'name': name}))
    if not glance_images:
        raise CHIValueError(f'No images found matching name "{name}"')
    elif len(glance_images) > 1:
        raise ResourceError(f'Multiple images found matching name "{name}"')

    return Image.from_glance_image(glance_images[0])


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
        raise CHIValueError(f'No images found matching name "{name}"')
    elif len(images) > 1:
        raise ResourceError(f'Multiple images found matching name "{name}"')
    return images[0].id
