import chi
import pytest


def setup_function():
    chi.reset()


def test_get():
    value = "KEYNAME"
    chi.set("key_name", value)
    assert chi.get("key_name") == value


def test_get_invalid_key():
    with pytest.raises(KeyError):
        chi.get("some_invalid_key")


def test_set():
    values = ["KEYNAME", "KEYNAME2"]
    [chi.set("key_name", k) for k in values]
    assert chi.get("key_name") == values[-1]


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
    auth_plugin = session.session.auth
    assert auth_plugin.auth_url == "AUTH_URL"
    assert auth_plugin.auth_methods[0].token == "TOKEN"
    assert auth_plugin.project_name == "PROJECT_NAME"
    assert auth_plugin.project_domain_name == "PROJECT_DOMAIN_NAME"
    assert session.interface == "INTERFACE"
    assert session.region_name == "REGION_NAME"
