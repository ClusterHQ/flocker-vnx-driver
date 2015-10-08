# Copyright ClusterHQ.
# See LICENSE file for details.

"""
Functional tests for
``flocker.node.agents.blockdevice.EMCVnxBlockDeviceAPI``
using a VNX cluster.
"""

import os
import yaml
from uuid import uuid4

from bitmath import GiB

from flocker.testtools import skip_except

from vnx import EMCVnxBlockDeviceAPI

from flocker.node.agents.test.test_blockdevice import (
    make_iblockdeviceapi_tests, detach_destroy_volumes
)


def emcvnxblockdeviceapi_for_test(cluster_id, test_case):
    """
    Create a ``EMCVnxIOBlockDeviceAPI`` instance for use in tests.

    :returns: A ``EMCVnxBlockDeviceAPI`` instance
    """
    config_file_path = os.environ.get('VNX_CONFIG_FILE')
    config_file = open(config_file_path)
    config = yaml.load(config_file.read())
    user = config['USER']
    password = config['PASSWORD']
    ip = config['IP']
    pool = config['STORAGE_POOL']
    group = config['STORAGE_GROUP']
    api = EMCVnxBlockDeviceAPI(cluster_id, user, password, ip, pool, group)
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
        # 'test_multiple_volumes_attached_to_host',
        'test_detach_unknown_volume',
        'test_detach_detached_volume',
        'test_detach_volume',
        'test_reattach_detached_volume',
        # 'test_attach_destroyed_volume',
        'test_get_device_path_unknown_volume',
        # 'test_get_device_path_unattached_volume',
        # 'test_get_device_path_device',
        # 'test_get_device_path_device_repeatable_results',
        # 'test_device_size',
        'test_compute_instance_id_nonempty',
        'test_compute_instance_id_unicode'
    ]
)
class EMCVnxBlockDeviceAPIInterfaceTests(
        make_iblockdeviceapi_tests(
            blockdevice_api_factory=(
                lambda test_case: emcvnxblockdeviceapi_for_test(
                    uuid4(),
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
