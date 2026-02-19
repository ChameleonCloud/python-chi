from unittest.mock import Mock

import cinderclient.exceptions

from chi.storage import get_volume


def test_get_volume_falls_back_to_name_lookup(mocker):
    cinder_mock = mocker.patch("chi.storage.cinder")()
    cinder_mock.volumes.get.side_effect = cinderclient.exceptions.NotFound(404)

    fake_volume = Mock()
    fake_volume.name = "my-vol"
    fake_volume.size = 10
    fake_volume.description = None
    fake_volume.metadata = {}
    fake_volume.volume_type = "ceph-ssd"
    fake_volume.id = "vol-123"
    fake_volume.status = "available"
    cinder_mock.volumes.list.return_value = [fake_volume]

    result = get_volume("my-vol")

    assert result.id == "vol-123"
    assert result.name == "my-vol"
