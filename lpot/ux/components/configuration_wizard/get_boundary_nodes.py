# -*- coding: utf-8 -*-
# Copyright (c) 2021 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Configuration to yaml."""

import json
from typing import Any, Dict

from lpot.ux.components.model.repository import ModelRepository
from lpot.ux.utils.exceptions import ClientErrorException, NotFoundException
from lpot.ux.utils.logger import log
from lpot.ux.utils.utils import check_module, get_module_version
from lpot.ux.web.communication import MessageQueue

mq = MessageQueue()


def get_boundary_nodes(data: Dict[str, Any]) -> None:
    """Get configuration."""
    from lpot.ux.utils.utils import find_boundary_nodes

    request_id = str(data.get("id", ""))
    model_path = data.get("model_path", None)

    if not (request_id and model_path):
        message = "Missing model path or request id."
        mq.post_error(
            "boundary_nodes_finish",
            {"message": message, "code": 404, "id": request_id},
        )
        return

    try:
        mq.post_success(
            "boundary_nodes_start",
            {"message": "started", "id": request_id},
        )
        model_repository = ModelRepository()
        try:
            model = model_repository.get_model(model_path)
        except NotFoundException:
            supported_frameworks = model_repository.get_frameworks()
            raise ClientErrorException(
                f"Framework for specified model is not yet supported. "
                f"Supported frameworks are: {', '.join(supported_frameworks)}.",
            )
        framework = model.get_framework_name()
        try:
            check_module(framework)
        except ClientErrorException:
            raise ClientErrorException(
                f"Detected {framework} model. "
                f"Could not find installed {framework} module. "
                f"Please install {framework}.",
            )
        framework_version = get_module_version(framework)

        response_data = find_boundary_nodes(model_path)
        response_data["id"] = request_id
        response_data["framework"] = framework
        response_data["framework_version"] = framework_version
    except ClientErrorException as err:
        mq.post_error(
            "boundary_nodes_finish",
            {"message": str(err), "code": 404, "id": request_id},
        )
        return
    log.debug(f"Parsed data is {json.dumps(response_data)}")
    mq.post_success("boundary_nodes_finish", response_data)
