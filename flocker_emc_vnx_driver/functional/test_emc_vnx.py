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

from flocker.testtools import skip_except

from vnx_flocker_driver import EMCVnxBlockDeviceAPI

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
    config = yaml.load(config_file.read())
    ip = config['IP']
    pool = config['STORAGE_POOL']
    keys = config['NAVISECCLI_KEYS']
    group = config['STORAGE_GROUP']
    host = config['HOSTNAME']
    api = EMCVnxBlockDeviceAPI(cluster_id, ip, pool, host, group, keys)
    test_case.addCleanup(detach_destroy_volumes, api)
    return api


# We could remove this, all tests are covered
@skip_except(
    supported_tests=[
        'test_interface',
        'test_created_is_listed',
        'test_list_volume_empty',
        'test_listed_volume_attributes',
        'test_created_volume_attributes',
        'test_destroy_unknown_volume',
        'test_destroy_volume',
        'test_destroy_destroyed_volume',
        'test_attach_unknown_volume',
        'test_attach_attached_volume',
        'test_attach_elsewhere_attached_volume',
        'test_attach_unattached_volume',
        'test_attached_volume_listed',
        'test_list_attached_and_unattached',
        'test_multiple_volumes_attached_to_host',
        'test_detach_unknown_volume',
        'test_detach_detached_volume',
        'test_detach_volume',
        'test_reattach_detached_volume',
        'test_attach_destroyed_volume',
        'test_get_device_path_unknown_volume',
        'test_get_device_path_unattached_volume',
        'test_get_device_path_device',
        'test_get_device_path_device_repeatable_results',
        'test_device_size',
        'test_compute_instance_id_nonempty',
        'test_compute_instance_id_unicode'
    ]
)
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