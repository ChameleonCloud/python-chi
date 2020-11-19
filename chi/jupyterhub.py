import os
import requests

ACCESS_TOKEN_ENDPOINT = 'tokens'

hub_api_url = os.getenv('JUPYTERHUB_API_URL')
hub_token = os.getenv('JUPYTERHUB_API_TOKEN')


def is_jupyterhub_env():
    return hub_api_url is not None


def call_jupyterhub_api(path, method='GET'):
    res = requests.request(
        url=f'{hub_api_url}/{path}',
        method=method,
        headers={'authorization': f'token {hub_token}'})
    res.raise_for_status()

    return res.json()


def refresh_access_token():
    """Refresh a user's access token via the JupyterHub API.
    This requires a custom handler be installed within JupyterHub; that handler
    is currently a part of the jupyterhub-chameleon PyPI package.
    Returns:
        str: the new access token for the user.
    Raises:
        AuthenticationError: if the access token cannot be refreshed.
    """
    res = call_jupyterhub_api(ACCESS_TOKEN_ENDPOINT)
    access_token = res.get('access_token')
    expires_at = res.get('expires_at')

    if not access_token:
        raise ValueError(f'Failed to get access token: {res}')

    return access_token, expires_at
