class CHIValueError(ValueError):
    """Raised when argument is not valid. These errors might be fixed by
    checking hardware catalog or documentation. Examples where this might
    be seen are:
    * Site name is not valid
    * Node type is not valid
    * Resource does not exist
    """

    def __init__(self, message):
        super().__init__(message)


class ResourceError(Exception):
    """Raised when a request has valid arguments, but the resources are
    being used incorrectly, or can not be used as requested. This type
    of error might depend on the time the request is run, due to the
    shared nature of the testbed."""

    def __init__(self, message):
        super().__init__(message)


class ServiceError(Exception):
    """Raised when an error occurs with some Chameleon resource.
    For example, if your node is having hardware issues, and so
    fails to provision, this will be raised."""

    def __init__(self, message):
        super().__init__(message)
