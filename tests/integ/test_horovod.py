# Copyright 2017-2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import json
import os
import tarfile
from six.moves.urllib.parse import urlparse

import boto3
import pytest

import sagemaker.utils
import tests.integ as integ
from sagemaker.tensorflow import TensorFlow
from tests.integ import timeout

horovod_dir = os.path.join(os.path.dirname(__file__), "..", "data", "horovod")


@pytest.fixture(scope="module")
def gpu_instance_type(request):
    return "ml.p2.xlarge"


@pytest.mark.canary_quick
def test_hvd_cpu(sagemaker_session, cpu_instance_type, tmpdir):
    __create_and_fit_estimator(sagemaker_session, cpu_instance_type, tmpdir)


@pytest.mark.canary_quick
@pytest.mark.skipif(
    integ.test_region() in integ.HOSTING_NO_P2_REGIONS, reason="no ml.p2 instances in this region"
)
def test_hvd_gpu(sagemaker_session, gpu_instance_type, tmpdir):
    __create_and_fit_estimator(sagemaker_session, gpu_instance_type, tmpdir)


@pytest.mark.local_mode
@pytest.mark.parametrize("instances, processes", [[1, 2], (2, 1), (2, 2)])
def test_horovod_local_mode(sagemaker_local_session, instances, processes, tmpdir):
    output_path = "file://%s" % tmpdir
    job_name = sagemaker.utils.unique_name_from_base("tf-horovod")
    estimator = TensorFlow(
        entry_point=os.path.join(horovod_dir, "hvd_basic.py"),
        role="SageMakerRole",
        train_instance_count=2,
        train_instance_type="local",
        sagemaker_session=sagemaker_local_session,
        py_version=integ.PYTHON_VERSION,
        script_mode=True,
        output_path=output_path,
        framework_version="1.12",
        distributions={"mpi": {"enabled": True, "processes_per_host": processes}},
    )

    with timeout.timeout(minutes=integ.TRAINING_DEFAULT_TIMEOUT_MINUTES):
        estimator.fit(job_name=job_name)

        tmp = str(tmpdir)
        extract_files(output_path.replace("file://", ""), tmp)

        size = instances * processes

        for rank in range(size):
            assert read_json("rank-%s" % rank, tmp)["rank"] == rank


def extract_files(output_path, tmpdir):
    with tarfile.open(os.path.join(output_path, "model.tar.gz")) as tar:
        tar.extractall(tmpdir)


def read_json(file, tmp):
    with open(os.path.join(tmp, file)) as f:
        return json.load(f)


def extract_files_from_s3(s3_url, tmpdir):
    parsed_url = urlparse(s3_url)
    s3 = boto3.resource("s3")

    model = os.path.join(tmpdir, "model")
    s3.Bucket(parsed_url.netloc).download_file(parsed_url.path.lstrip("/"), model)

    with tarfile.open(model, "r") as tar_file:
        tar_file.extractall(tmpdir)


def __create_and_fit_estimator(sagemaker_session, instance_type, tmpdir):
    job_name = sagemaker.utils.unique_name_from_base("tf-horovod")
    estimator = TensorFlow(
        entry_point=os.path.join(horovod_dir, "hvd_basic.py"),
        role="SageMakerRole",
        train_instance_count=2,
        train_instance_type=instance_type,
        sagemaker_session=sagemaker_session,
        py_version=integ.PYTHON_VERSION,
        script_mode=True,
        framework_version="1.12",
        distributions={"mpi": {"enabled": True}},
    )

    with timeout.timeout(minutes=integ.TRAINING_DEFAULT_TIMEOUT_MINUTES):
        estimator.fit(job_name=job_name)

        tmp = str(tmpdir)
        extract_files_from_s3(estimator.model_data, tmp)

        for rank in range(2):
            assert read_json("rank-%s" % rank, tmp)["rank"] == rank
