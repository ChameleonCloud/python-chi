from json import dumps, loads

import pytest
import requests
from requests import HTTPError

import chi
from chi import widgets


@pytest.fixture()
def site_names():
    return ['CHI@Test1', 'CHI@Test2']


@pytest.fixture()
def node_types():
    return ['test_node_type_1', 'test_node_type_1']


@pytest.fixture()
def node_names():
    return ['test_node_1', 'test_node_2']


@pytest.fixture()
def node_uids():
    return ['test_uid_1', 'test_uid_2']


@pytest.fixture()
def sites_request(site_names, node_uids):
    return str(dumps(
        {"items": [{"email_contact": "example@domain.org",
                    "latitude": 0,
                    "longitude": 0,
                    "location": None,
                    "name": site_names[0],
                    "uid": node_uids[0]},
                   {"email_contact": "example@domain.org",
                    "latitude": 0,
                    "longitude": 0,
                    "location": None,
                    "name": site_names[1],
                    "uid": node_uids[1]}]}
    ))


@pytest.fixture()
def discovery_request_one(node_names, node_types, node_uids):
    return str(dumps(
        {"items": [{"architecture": {"platform_type": "x86_64"},
                    "node_name": node_names[0],
                    "node_type": node_types[0],
                    "gpu": {"gpu": True, "gpu_count": 1},
                    "storage_devices": [
                        {"media_type": "SSD", "humanized_size": "250 GB"}],
                    "type": "node",
                    "uid": node_uids[0]}]}
    ))


@pytest.fixture()
def discovery_request_two(node_names, node_types, node_uids):
    return str(dumps(
        {"items": [{"architecture": {"platform_type": "x86_64"},
                    "node_name": node_names[1],
                    "node_type": node_types[1],
                    "gpu": {"gpu": False},
                    "storage_devices": [
                        {"media_type": "SSD", "humanized_size": "200 GB"},
                        {"media_type": "SSD", "humanized_size": "200 GB"}],
                    "type": "node",
                    "uid": node_uids[1]}]}
    ))


def test_get_site(site):
    chi.set('region_name', site)
    assert widgets.get_site() == site


def test_get_node(node):
    chi.set("node_type", node)
    assert widgets.get_node() == node


def test_get_discovery(requests_mock, sites_request, site_names, node_names,
                       discovery_request_one, discovery_request_two,
                       node_uids):
    sites_url = 'https://api.chameleoncloud.org/sites/'
    requests_mock.get(sites_url, text="", status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_discovery()

    requests_mock.get(sites_url, text=sites_request)
    assert requests.get(sites_url).text == sites_request

    node_urls = ['https://api.chameleoncloud.org/sites/' + uid
                 + '/clusters/chameleon/nodes' for uid in node_uids]
    requests_mock.get(node_urls[0], text="", status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_discovery()
    with pytest.raises(HTTPError):
        widgets.get_discovery(site_names[0])

    requests_mock.get(node_urls[0], text=discovery_request_one)
    requests_mock.get(node_urls[1], text=discovery_request_two)
    assert requests.get(node_urls[0]).text == discovery_request_one
    assert requests.get(node_urls[1]).text == discovery_request_two

    all_sites_ret_val = {site_names[0]: {
        node_names[0]: loads(discovery_request_one[11:-2])}, site_names[1]: {
        node_names[1]: loads(discovery_request_two[11:-2])}}
    assert widgets.get_discovery() == all_sites_ret_val

    site_one_ret_val = list(all_sites_ret_val.items())[0][1]
    assert widgets.get_discovery(site_names[0]) == site_one_ret_val
    site_two_ret_val = list(all_sites_ret_val.items())[0][1]
    assert widgets.get_discovery(site_names[0]) == site_two_ret_val

    with pytest.raises(ValueError):
        widgets.get_discovery("invalid_site_name")


def test_get_sites(requests_mock, sites_request, site_names):
    sites_url = 'https://api.chameleoncloud.org/sites.json'
    requests_mock.get(sites_url, text="", status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_sites()
    requests_mock.get(sites_url, text=sites_request)
    assert dumps(widgets.get_sites()) == sites_request[10:-1]
