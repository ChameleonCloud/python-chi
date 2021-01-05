from . import glance

from glanceclient.exc import NotFound

__all__ = [
    'get_image',
    'get_image_id',
    'list_images',
    'show_image',
]


def get_image(ref):
    try:
        return show_image(ref)
    except NotFound:
        return show_image(get_image_id(ref))


def get_image_id(name):
    images = glance().images.list(filters={'name': name})
    if not images:
        raise ValueError(f'No images found matching name "{name}"')
    elif len(images) > 1:
        raise ValueError(f'Multiple images found matching name "{name}"')
    return images[0]['id']


def list_images():
    return glance().images.list()


def show_image(image_id):
    return glance().images.get(image_id)


def show_image_by_name(name):
    image_id = get_image_id(name)
    return show_image(image_id)
