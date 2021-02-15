from neutronclient.common.exceptions import NotFound
import pytest

from chi.network import get_network, get_subnet, get_router, get_floating_ip


def fake_network():
    return {
        "id": "network-id",
        "name": "network-name",
        "project_id": "network-project-id",
    }


def fake_subnet():
    return {
        "id": "subnet-id",
        "name": "subnet-name",
        "network_id": "network-id",
    }


def fake_router():
    return {
        "id": "router-id",
        "name": "router-name",
        "project_id": "router-project-id",
    }


def fake_floating_ip():
    return {
        "id": "floatingip-id",
        "name": "floatingip-name",
        "project_id": "floatingip-project-id",
    }


@pytest.mark.parametrize("test_fn,neutron_resource,expected", [
    pytest.param(get_network, "network", fake_network(), id="network"),
    pytest.param(get_subnet, "subnet", fake_subnet(), id="subnet"),
    pytest.param(get_router, "router", fake_router(), id="router"),
])
def test_get_resource_by_id(mocker, test_fn, neutron_resource, expected):
    neutron = mocker.patch("chi.network.neutron")()

    neutron_show = getattr(neutron, f"show_{neutron_resource}")
    neutron_show.return_value = {neutron_resource: expected}

    search_id = f"{neutron_resource}-id"
    assert test_fn(search_id) == expected
    neutron_show.assert_called_once_with(search_id)


@pytest.mark.parametrize("test_fn,neutron_resource,expected", [
    pytest.param(get_network, "network", fake_network(), id="network"),
    pytest.param(get_subnet, "subnet", fake_subnet(), id="subnet"),
    pytest.param(get_router, "router", fake_router(), id="router"),
])
def test_get_resource_by_name(mocker, test_fn, neutron_resource, expected):
    neutron = mocker.patch("chi.network.neutron")()

    search_id = f"{neutron_resource}-id"
    search_name = f"{neutron_resource}-name"

    def _show(ref):
        if ref == search_name:
            raise NotFound
        elif ref == search_id:
            return {neutron_resource: expected}
        else:
            raise ValueError(f"Unexpected ref {ref}")

    neutron_show = getattr(neutron, f"show_{neutron_resource}")
    neutron_list = getattr(neutron, f"list_{neutron_resource}s")
    neutron_show.side_effect = _show
    neutron_list.return_value = {f"{neutron_resource}s": [expected]}

    assert test_fn(search_name) == expected
    # In this case we expect 1 call for the name, which will fail, then a call
    # to list resources to find the ID, then a call to look up by ID.
    neutron_show.assert_any_call(search_name)
    neutron_list.assert_called_once()
    neutron_show.assert_any_call(search_id)
    assert neutron_show.call_count == 2
