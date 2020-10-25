import os

from oslo_config import cfg
import pytest

import chi

def setup_function():
    chi.reset()


def test_get():
    value = "KEYNAME"
    chi.set("key_name", value)
    assert chi.get("key_name") == value


def test_get_invalid_key():
    with pytest.raises(cfg.NoSuchOptError):
        chi.get("some_invalid_key")


def test_set():
    values = ["KEYNAME", "KEYNAME2"]
    [chi.set("key_name", k) for k in values]
    assert chi.get("key_name") == values[-1]


def test_set_invalid_key():
    with pytest.raises(cfg.NoSuchOptError):
        chi.set("some_invalid_key", "foo")


def test_reset():
    value = "KEYNAME"
    chi.set("key_name", value)
    chi.reset()
    assert chi.get("key_name") == None


def test_session():
    chi.set("auth_url", "AUTH_URL")
    chi.set("token", "TOKEN")
    chi.set("project_name", "PROJECT_NAME")
    chi.set("project_domain_name", "PROJECT_DOMAIN_NAME")
    chi.set("interface", "INTERFACE")
    chi.set("region_name", "REGION_NAME")
    session = chi.session()
    assert session
    assert session.interface == "INTERFACE"
    assert session.region_name == "REGION_NAME"
    auth_plugin = session.session.auth
    assert auth_plugin
    assert auth_plugin.auth_url == "AUTH_URL"
    assert auth_plugin.auth_methods[0].token == "TOKEN"
    assert auth_plugin.project_name == "PROJECT_NAME"
    assert auth_plugin.project_domain_name == "PROJECT_DOMAIN_NAME"


def test_switch_auth_plugin():
    chi.set("auth_type", "v3oidcaccesstoken")
    chi.set("auth_url", "AUTH_URL")
    chi.set("protocol", "PROTOCOL")
    chi.set("access_token", "ACCESS_TOKEN")
    chi.set("identity_provider", "IDENTITY_PROVIDER")
    session = chi.session()
    assert session
    assert session.session.auth.access_token == "ACCESS_TOKEN"
    chi.set("auth_type", "v3token")
    chi.set("token", "TOKEN")
    session = chi.session()
    assert session
    assert session.session.auth.auth_methods[0].token == "TOKEN"


def test_set_auth_params_in_any_order():
    """It should be possible to set auth_type after setting other parameters.

    Any parameters set before setting auth_type should be preserved and used,
    even if the currently selected auth_type does not use those parameters.
    """
    chi.set("auth_url", "AUTH_URL")
    chi.set("application_credential_id", "APPLICATION_CREDENTIAL_ID")
    chi.set("application_credential_secret", "APPLICATION_CREDENTIAL_SECRET")
    chi.set("auth_type", "v3applicationcredential")
    session = chi.session()
    assert session

def test_default_from_env():
    os.environ['OS_AUTH_TYPE'] = 'v3password'
    os.environ['OS_USERNAME'] = 'USERNAME'
    os.environ['OS_PASSWORD'] = 'PASSWORD'
    os.environ['OS_PROJECT_ID'] = 'PROJECT_ID'
    chi.reset()
    assert chi.get('auth_type') == 'v3password'
    assert chi.get('username') == 'USERNAME'
    assert chi.get('password') == 'PASSWORD'
    assert chi.get('project_id') == 'PROJECT_ID'
