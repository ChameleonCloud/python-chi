from json import dumps, loads

import pytest
import requests
from requests import HTTPError

import chi
from chi import widgets


@pytest.fixture()
def site_names():
    return ["CHI@Test1", "CHI@Test2"]


@pytest.fixture()
def node_types():
    return ["test_node_type_1", "test_node_type_2"]


@pytest.fixture()
def node_names():
    return ["test_node_1", "test_node_2"]


@pytest.fixture()
def node_uids():
    return ["test_uid_1", "test_uid_2"]


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
def resource_request_one(node_names, node_types, node_uids):
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
def resource_request_two(node_names, node_types, node_uids):
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
    return [{"hypervisor_hostname": node_uids[0], "node_name": node_names[0],
             "node_type": node_types[0], "reservable": False}]


def test_get_selected_site(site_names):
    chi.set("region_name", site_names[0])
    assert widgets.get_selected_site() == site_names[0]


def test_get_selected_node_type(node_types):
    chi.set("node_type", node_types[0])
    assert widgets.get_selected_node_type() == node_types[0]


def test_get_resource_data(requests_mock, sites_request, site_names,
                           node_names, resource_request_one, node_uids,
                           resource_request_two):
    sites_url = widgets._build_request(sites=True)
    requests_mock.get(sites_url, text='', status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_resource_data()

    requests_mock.get(sites_url, text=sites_request)
    assert requests.get(sites_url).text == sites_request

    node_urls = [widgets._build_request(sites=True, uid=uid, nodes=True)
                 for uid in node_uids]
    requests_mock.get(node_urls[0], text='', status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_resource_data()
    with pytest.raises(HTTPError):
        widgets.get_resource_data(site_names[0])

    requests_mock.get(node_urls[0], text=resource_request_one)
    requests_mock.get(node_urls[1], text=resource_request_two)
    assert requests.get(node_urls[0]).text == resource_request_one
    assert requests.get(node_urls[1]).text == resource_request_two

    all_sites_ret_val = {site_names[0]: {
        node_names[0]: loads(resource_request_one[11:-2])}, site_names[1]: {
        node_names[1]: loads(resource_request_two[11:-2])}}
    assert widgets.get_resource_data() == all_sites_ret_val

    site_one_ret_val = list(all_sites_ret_val.items())[0][1]
    assert widgets.get_resource_data(site_names[0]) == site_one_ret_val
    site_two_ret_val = list(all_sites_ret_val.items())[0][1]
    assert widgets.get_resource_data(site_names[0]) == site_two_ret_val

    with pytest.raises(ValueError):
        widgets.get_resource_data("invalid_site_name")


def test_get_nodes(requests_mock, site_names, sites_request, node_uids,
                   node_types, resource_request_one, resource_request_two,
                   mocker, blazar_request):
    # setup
    sites_url = widgets._build_request(sites=True)
    chi.set("region_name", site_names[0])
    requests_mock.get(sites_url, text=sites_request)
    node_urls = [widgets._build_request(sites=True, uid=uid, nodes=True)
                 for uid in node_uids]
    requests_mock.get(node_urls[0], text=resource_request_one)
    requests_mock.get(node_urls[1], text=resource_request_two)

    def blazar(request):
        mock_blazar = lambda: None
        mock_list = lambda: None
        mock_list.list = lambda: request
        mock_blazar.host = mock_list
        return mock_blazar

    mocker.patch("chi.blazar", return_value=blazar(blazar_request))
    mock_avail_nodes = {node_types[0]: loads(resource_request_one[11:-2])}
    mock_unavail_nodes = {}
    get_nodes_ret_val = {"avail": mock_avail_nodes,
                         "unavail": mock_unavail_nodes}
    assert widgets.get_nodes(display=False) == get_nodes_ret_val

    assert widgets.get_nodes(display=True).get("Type").tolist() == \
           [node_types[0]]
    assert widgets.get_nodes(display=True).get("Free").tolist() == [1]
    assert widgets.get_nodes(display=True).get("In Use").tolist() == [0]


def test_choose_node_type(requests_mock, site_names, sites_request, node_uids,
                          node_types, resource_request_one, blazar_request,
                          resource_request_two, mocker):
    # setup
    sites_url = widgets._build_request(sites=True)
    chi.set("region_name", site_names[0])
    requests_mock.get(sites_url, text=sites_request)
    node_urls = [widgets._build_request(sites=True, uid=uid, nodes=True)
                 for uid in node_uids]
    requests_mock.get(node_urls[0], text=resource_request_one)
    requests_mock.get(node_urls[1], text=resource_request_two)

    def blazar(request):
        mock_blazar = lambda: None
        mock_list = lambda: None
        mock_list.list = lambda: request
        mock_blazar.host = mock_list
        return mock_blazar

    mocker.patch("chi.blazar", return_value=blazar(blazar_request))

    with pytest.raises(ValueError):
        widgets.choose_node_type(gpu_count=1, has_gpu=False)
    with pytest.raises(ValueError):
        widgets.choose_node_type(gpu_count=0, has_gpu=True)

    def get_options(vbox):
        return [vbox.children[0].options[i] for i in
                range(len(vbox.children[0].options))] if vbox else None

    choose_node_type = widgets.choose_node_type()
    widget_options = get_options(choose_node_type)
    assert widget_options == [node_types[0]]

    choose_node_type = widgets.choose_node_type(has_gpu=True)
    widget_options = get_options(choose_node_type)
    assert widget_options == [node_types[0]]

    choose_node_type = widgets.choose_node_type(has_gpu=False)
    widget_options = get_options(choose_node_type)
    assert widget_options is None

    with pytest.raises(ValueError):
        widgets.choose_node_type(gpu_count=-1)

    choose_node_type = widgets.choose_node_type(storage_size_gb=225)
    widget_options = get_options(choose_node_type)
    assert widget_options == [node_types[0]]

    choose_node_type = widgets.choose_node_type(storage_size_gb=300)
    widget_options = get_options(choose_node_type)
    assert widget_options is None

    with pytest.raises(ValueError):
        widgets.choose_node_type(storage_size_gb=-1)

    choose_node_type = widgets.choose_node_type(architecture="x86_64")
    widget_options = get_options(choose_node_type)
    assert widget_options == [node_types[0]]

    choose_node_type = widgets.choose_node_type(architecture="does_not_exist")
    widget_options = get_options(choose_node_type)
    assert widget_options is None

    choose_node_type = widgets.choose_node_type(ssd=True)
    widget_options = get_options(choose_node_type)
    assert widget_options == [node_types[0]]

    choose_node_type = widgets.choose_node_type(ssd=False)
    widget_options = get_options(choose_node_type)
    assert widget_options is None


def test_get_sites(requests_mock, sites_request, site_names):
    requests_mock.get(widgets._build_request(sites=True, json=True),
                      text='', status_code=404)
    with pytest.raises(HTTPError):
        widgets.get_sites()
    requests_mock.get(widgets._build_request(sites=True, json=True),
                      text=sites_request)
    assert dumps(widgets.get_sites()) == sites_request[10:-1]


def test_get_projects(mocker):
    mocker.patch("jwt.decode", return_value={"project_names": [
        "test_project"]})
    assert widgets.get_projects() == ["test_project"]


def test_choose_site(mocker, site_names, requests_mock, sites_request):
    requests_mock.get(widgets._build_request(sites=True, json=True),
                      text=sites_request)
    mocker.patch("chi.widgets.get_sites", return_value=[
        {"name": site_names[0]}, {"name": site_names[1]}])
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
    mocker.patch("jwt.decode", return_value={"project_names": [
        "test_project"]})
    choose_project = widgets.choose_project()
    widget_options = choose_project.children[0].options[0]
    assert widget_options == "test_project"
