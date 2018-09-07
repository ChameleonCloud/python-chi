from keystoneauth1 import adapter, session
from keystoneauth1.identity import v3
from os import getenv

class Session(session.Session):
    '''
    Creates a Keystone session object for use in OpenStack clients.
    Defaults to using environment variables discovered.
    '''
    def __init__(project_name):
        auth_url = getenv('OS_URL')
        token = getenv('OS_TOKEN')

        # Exchange unscoped token for project-scoped token
        auth = v3.Token(auth_url=auth_url, token=token,
                        project_name=project_name,
                        project_domain_name='default')

        super(session.Session, self).__init__(auth=auth)

    def with_region(region_name):
        return adapter.Adapter(session=self, region_name=region_name)
