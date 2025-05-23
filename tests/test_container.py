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

from chi.container import upload


@pytest.fixture()
def now():
    return datetime(2021, 1, 1, 0, 0, 0, 0)


def _tar_data(source):
    fd = io.BytesIO()
    with tarfile.open(fileobj=fd, mode="w") as tar:
        tar.add(source, arcname=os.path.basename(source))
    fd.seek(0)
    data = fd.read()
    fd.close()
    return data


def test_container_upload(mocker):
    zun = mocker.patch("chi.container.zun")()

    fake_data = b"fake_infile_data"

    with tempfile.NamedTemporaryFile() as sourcefp:
        # populate tmpfile with fake data
        sourcefp.write(fake_data)

        tarred_data = _tar_data(sourcefp.name)
        upload(
            "fake_uuid",
            source=sourcefp.name,
            dest="fake_path",
        )

    # ensure the data we sent to zun is the expected format
    zun.containers.put_archive.assert_called_once_with(
        "fake_uuid", "fake_path", tarred_data
    )

    newfd = io.BytesIO(tarred_data)
    with tempfile.TemporaryDirectory() as dest:
        with tarfile.open(fileobj=newfd, mode="r") as tar:
            tar.extraction_filter = lambda member, path: member
            tar.extractall(dest)
