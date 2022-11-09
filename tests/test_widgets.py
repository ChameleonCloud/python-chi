from json import dumps

import pytest
import requests
from requests import HTTPError

import chi
from chi import widgets


@pytest.fixture()
def sites_request():
    return str(dumps(
        {"items": [{"email_contact": "example@domain.org",
                    "latitude": 0,
                    "longitude": 0,
                    "location": "None",
                    "name": "CHI@Test1",
                    "uid": "test1"},
                   {"email_contact": "example@domain.org",
                    "latitude": 0,
                    "longitude": 0,
                    "location": "None",
                    "name": "CHI@Test2",
                    "uid": "test2"}]}
    ))


@pytest.fixture()
def site():
    return 'CHI@Test1'


@pytest.fixture()
def node():
    return 'test_node_type_1'


def test_get_site(site):
    chi.set('region_name', site)
    assert widgets.get_site() == site


def test_get_node(node):
    chi.set("node_type", node)
    assert widgets.get_node() == node


def test_get_discovery(requests_mock,
                       sites_request):
    sites_url = 'https://api.chameleoncloud.org/sites/'
    requests_mock.get(sites_url, text="", status_code=404)
    with pytest.raises(HTTPError):
        bad_req = requests.get(sites_url)
        bad_req.raise_for_status()

    requests_mock.get(sites_url, text=sites_request)
    assert requests.get(sites_url).text == sites_request

    # TODO: handle bad request from widgets.get_discovery(site)
    # TODO: check valid case of widgets.get_discovery(site)
    # TODO: handle bad request to /clusters/chameleon/notes
    # TODO: check valid case of widgets.get_discovery()
