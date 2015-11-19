# Copyright ClusterHQ.
# See LICENSE file for details.

"""
Functional tests for
``flocker.node.agents.blockdevice.EMCVnxBlockDeviceAPI``
using a VNX cluster.
"""

import os
import sys
import yaml
from uuid import uuid4

from bitmath import GiB

from .. import EMCVnxBlockDeviceAPI

from flocker.node.agents.test.test_blockdevice import (
    make_iblockdeviceapi_tests, detach_destroy_volumes
)

if os.path.basename(sys.argv[0]) == "trial":
    from eliot.twisted import redirectLogsForTrial
    redirectLogsForTrial()


def emcvnxblockdeviceapi_for_test(cluster_id, test_case):
    """
    Create a ``EMCVnxIOBlockDeviceAPI`` instance for use in tests.

    :returns: A ``EMCVnxBlockDeviceAPI`` instance
    """
    config_file_path = os.environ.get('VNX_CONFIG_FILE')
    config_file = open(config_file_path)
    config = yaml.load(config_file.read())['dataset']
    ip = config['spa_ip']
    pool = config['storage_pool']
    keys = config['naviseccli_keys']
    group = config['storage_group']
    host = config['hostname']
    api = EMCVnxBlockDeviceAPI(cluster_id, ip, pool, host, group, keys)
    test_case.addCleanup(detach_destroy_volumes, api)
    return api


class EMCVnxBlockDeviceAPIInterfaceTests(
        make_iblockdeviceapi_tests(
            blockdevice_api_factory=(
                lambda test_case: emcvnxblockdeviceapi_for_test(
                    # XXX A hack to work around the LUN name length limit. We need a better way to store the cluster_id.
                    unicode(uuid4()).split('-')[0],
                    test_case)
            ),
            minimum_allocatable_size=int(GiB(8).to_Byte().value),
            device_allocation_unit=int(GiB(8).to_Byte().value),
            unknown_blockdevice_id_factory=lambda test: unicode(uuid4())
        )
):
    """
    Interface adherence Tests for ``EMCVnxBlockDeviceAPI``
    """
