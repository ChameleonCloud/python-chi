from json import dumps, loads

import pytest
import requests
from chi.widgets import IllegalArgumentError
from requests import HTTPError

import chi
from chi import widgets


@pytest.fixture()
def site_names():
    return ['CHI@Test1', 'CHI@Test2']


@pytest.fixture()
def node_types():
    return ['test_node_type_1', 'test_node_type_2']


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
                    "uid": node_uids[0]}],
         }
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


@pytest.fixture()
def blazar_request(node_uids, node_names, node_types):
    return [{'hypervisor_hostname': node_uids[0], 'node_name': node_names[0],
             'node_type': node_types[0], 'reservable': True}]


def test_get_site(site_names):
    chi.set('region_name', site_names[0])
    assert widgets.get_site() == site_names[0]


def test_get_node(node_types):
    chi.set("node_type", node_types[0])
    assert widgets.get_node() == node_types[0]


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


def test_get_nodes(requests_mock, site_names, sites_request, node_uids,
                   node_types, discovery_request_one, discovery_request_two,
                   mocker, blazar_request):
    with pytest.raises(IllegalArgumentError):
        widgets.get_nodes(None)

    # setup
    chi.set('region_name', site_names[0])
    sites_url = 'https://api.chameleoncloud.org/sites/'
    requests_mock.get(sites_url, text=sites_request)
    node_urls = ['https://api.chameleoncloud.org/sites/' + uid
                 + '/clusters/chameleon/nodes' for uid in node_uids]
    requests_mock.get(node_urls[0], text=discovery_request_one)
    requests_mock.get(node_urls[1], text=discovery_request_two)

    def blazar(request):
        mock_blazar = lambda: None
        mock_list = lambda: None
        mock_list.list = lambda: request
        mock_blazar.host = mock_list
        return mock_blazar

    mocker.patch('chi.blazar', return_value=blazar(blazar_request))

    mock_avail_nodes = {node_types[0]: loads(discovery_request_one[11:-2])}
    mock_unavail_nodes = {}
    get_nodes_ret_val = (mock_avail_nodes, mock_unavail_nodes)
    assert widgets.get_nodes(display=False) == get_nodes_ret_val

    assert widgets.get_nodes(display=True).get("Type").tolist() == \
           [node_types[0]]
    assert widgets.get_nodes(display=True).get("Free").tolist() == [1]
    assert widgets.get_nodes(display=True).get("In Use").tolist() == [0]


def test_get_sites(requests_mock, sites_request, site_names):
    sites_url = 'https://api.chameleoncloud.org/sites.json'
    requests_mock.get(sites_url, text="", status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_sites()
    requests_mock.get(sites_url, text=sites_request)
    assert dumps(widgets.get_sites()) == sites_request[10:-1]


def test_get_projects(mocker):
    mocker.patch("jwt.decode", return_value={'project_names': [
        'test_project']})
    assert widgets.get_projects() == ['test_project']


def test_choose_site(mocker, site_names, requests_mock, sites_request):
    sites_url = 'https://api.chameleoncloud.org/sites.json'
    requests_mock.get(sites_url, text=sites_request)
    mocker.patch("chi.widgets.get_sites", return_value=[
        {'name': site_names[0]}, {'name': site_names[1]}])
    mocker.patch("chi.context.set", return_value=None)
    mocker.patch("chi.context._sites",
                 {site_names[0]: {"name": site_names[0],
                                  "web": "https://www.google.com",
                                  "location": "None",
                                  "user_support_contact": "None"}})
    choose_site = widgets.choose_site()
    widget_options = [choose_site.children[0].options[i][0] for i in
                      range(len(site_names))]
    assert widget_options == site_names


def test_choose_project(mocker):
    mocker.patch("jwt.decode", return_value={'project_names': [
        'test_project']})
    choose_project = widgets.choose_project()
    widget_options = choose_project.children[0].options[0]
    assert widget_options == 'test_project'
