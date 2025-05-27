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


def example_create_share():
    """Create a share.

    <div class="alert alert-info">

    **Functions used in this example:**

    * [create_share](../modules/share.html#chi.share.create_share)

    </div>

    """
    from chi.share import create_share

    share_name = "my_share"
    create_share(size=1, name=share_name)


def test_example_create_share(mocker):
    manila = mocker.patch("chi.share.manila")()

    def _get_default_share_type_id():
        return "fakesharetypeid"

    mocker.patch(
        "chi.share._get_default_share_type_id", side_effect=_get_default_share_type_id
    )

    example_create_share()

    manila.shares.create.assert_called_once_with(
        share_proto="NFS",
        size=1,
        name="my_share",
        description=None,
        metadata=None,
        share_type=_get_default_share_type_id(),
        is_public=False,
    )
