from chi import widgets
import pytest

# TODO: Implement tests

""" Look for data that can be reused and assign that under a pytest fixture

SITE = some default site (used as a parameter for get_discovery, get_node_ids)
DISCOVERY = mock discovery return data
CLIENT = mocked chi.blazar() client
HOSTS = mock blazar return data
OS_ACCESS_TOKEN = mock access token from the environment
REGION_NAME = some value to set as the region name, to be returned from get("region_name")
GET_NODE = none
"""


def test_get_site():
    # Check that get(REGION_NAME) returns the user's currently selected site
    return True


def test_get_node():
    # Check that get(NODE_TYPE) returns the user's currently selected site
    return True


def test_get_discovery():
    # Check for a HTTPError if the request fails (3x in total)
    return True


def test_get_nodes():
    # Test that the blazar network can be accessed
    # blazar = mocker.patch('chi.lease.blazar')()
    print("WIP")


def test_choose_node():
    # Test for all ValueErrors (7 total)
    # Test for return value of None when all nodes of given parameters reserved
    print("WIP")


def test_get_sites():
    # Mock the api get request
    # Check for a HTTPError if the request fails
    print("WIP")


def test_get_projects():
    # Get the mock access token from the environment
    # Mock jwt.decode call, which stores "project_names" attribute
    # Check that the project names are as defined in the environment
    print("WIP")


def test_choose_site():
    print("WIP")


def test_choose_project():
    print("WIP")


def test_setup():
    # test that the function can call test_choose_site and test_choose_project
    print("WIP")
