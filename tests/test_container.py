# Copyright 2021 University of Chicago
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import io
import os
import tarfile
import tempfile
from datetime import datetime

import pytest
from zunclient.exceptions import Conflict

from chi.container import Container, download, upload


@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


def test_container_upload_method(mocker):
    # Arrange
    mock_upload = mocker.patch("chi.container.upload")
    container = Container(
        name="test",
        image_ref="image",
        exposed_ports=[],
    )
    container.id = "fake_id"
    source = "/tmp/sourcefile"
    remote_dest = "/container/path"

    # Act
    container.upload(source, remote_dest)

    # Assert
    mock_upload.assert_called_once_with("fake_id", source, remote_dest)


def test_container_download_method(mocker):
    # Arrange
    mock_download = mocker.patch("chi.container.download")
    container = Container(
        name="test",
        image_ref="image",
        exposed_ports=[],
    )
    container.id = "fake_id"
    remote_source = "/container/path"
    dest = "/tmp/destfile"

    # Act
    container.download(remote_source, dest)

    # Assert
    mock_download.assert_called_once_with("fake_id", remote_source, dest)


def test_upload_creates_tar_and_calls_put_archive(mocker):
    # Patch zun client
    zun_mock = mocker.patch("chi.container.zun")()
    # Create a temporary file to upload
    with tempfile.NamedTemporaryFile() as tmpfile:
        tmpfile.write(b"hello world")
        tmpfile.flush()

        upload("container_id", tmpfile.name, "/remote/path")
        # Check that put_archive was called
        assert zun_mock.containers.put_archive.call_count == 1
        args = zun_mock.containers.put_archive.call_args[0]
        assert args[0] == "container_id"
        assert args[1] == "/remote/path"
        # The third argument should be a tar archive containing the file
        tar_bytes = args[2]
        tarfileobj = io.BytesIO(tar_bytes)
        with tarfile.open(fileobj=tarfileobj, mode="r") as tar:
            names = tar.getnames()
            assert os.path.basename(tmpfile.name) in names


def test_download_extracts_tar_and_writes_file(mocker):
    # Patch zun client
    zun_mock = mocker.patch("chi.container.zun")()
    # Create a tar archive in memory with a test file
    file_content = b"test content"
    file_name = "testfile.txt"
    tar_bytes_io = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes_io, mode="w") as tar:
        info = tarfile.TarInfo(name=file_name)
        info.size = len(file_content)
        tar.addfile(info, io.BytesIO(file_content))
    tar_bytes = tar_bytes_io.getvalue()
    zun_mock.containers.get_archive.return_value = {"data": tar_bytes}

    # Use a temporary directory for extraction
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_path = os.path.join(tmpdir, file_name)

        download("container_id", file_name, tmpdir)
        # Check that the file was extracted
        assert os.path.exists(dest_path)
        with open(dest_path, "rb") as f:
            assert f.read() == file_content


def test_delete_calls_force(mocker):
    destroy_mock = mocker.patch("chi.container.destroy_container")
    container = Container(name="test", image_ref="img")
    container.id = "fake-id"

    container.delete()

    destroy_mock.assert_called_once_with("fake-id", force=True)
    assert container.id is None
    assert container._status is None


def test_submit_idempotent_returns_existing_without_create(mocker):
    # idempotent=true, wait=true
    chi_container = Container(name="dup-name", image_ref="img")
    existing_zun_container = mocker.Mock(uuid="existing-uuid", status="Running")

    mocker.patch("chi.container.get_container", return_value=existing_zun_container)
    create_mock = mocker.patch("chi.container.create_container")

    submit_result = chi_container.submit(
        idempotent=True, wait_for_active=True, wait_timeout=123, show="text"
    )
    create_mock.assert_not_called()
    existing_zun_container.wait.assert_called_once_with(status="Running", timeout=123)
    existing_zun_container.show.assert_called_once_with(
        type="text", wait_for_active=True
    )

    # submit returns only on idempotent=true
    assert submit_result is existing_zun_container


def test_submit_idempotent_returns_existing_without_create_no_wait(mocker):
    # idempotent=true, wait=false
    chi_container = Container(name="dup-name", image_ref="img")
    existing_zun_container = mocker.Mock(uuid="existing-uuid", status="Running")

    mocker.patch("chi.container.get_container", return_value=existing_zun_container)
    create_mock = mocker.patch("chi.container.create_container")

    submit_result = chi_container.submit(
        idempotent=True, wait_for_active=False, show=None
    )
    create_mock.assert_not_called()
    existing_zun_container.wait.assert_not_called()
    existing_zun_container.show.assert_not_called()

    # submit returns only on idempotent=true
    assert submit_result is existing_zun_container


def test_submit_duplicate_name_tracks_created_uuid(mocker):
    """Test the case where we re-run submit after a failure.

    An "old" container alreday already exists, with name = "dup-name".
    If idempotent=false, it should be possible to make a new container with the same name.
    However, name-based lookups will fail with a 409.
    """

    chi_container = Container(name="dup-name", image_ref="img")
    new_zun_container = mocker.Mock(uuid="new-uuid", status="Running")

    def _get_side_effect(ref):
        if ref == "dup-name":
            raise Conflict(
                "Multiple containers exist with same name. Please use the container uuid instead."
            )
        if ref == "new-uuid":
            return new_zun_container
        raise AssertionError(ref)

    mocker.patch("chi.container.create_container", return_value=new_zun_container)
    zun_mock = mocker.patch("chi.container.zun")()
    zun_mock.containers.get.side_effect = _get_side_effect

    # disable optional behavor from wait_for_active and show
    chi_container.submit(wait_for_active=False, show=None)
    assert chi_container.id == "new-uuid"
