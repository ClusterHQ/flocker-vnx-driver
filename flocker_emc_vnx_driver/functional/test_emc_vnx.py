# Copyright ClusterHQ.
# See LICENSE file for details.

"""
Functional tests for
``flocker.node.agents.blockdevice.EMCVnxBlockDeviceAPI``
using a VNX cluster.
"""

import os
import re
import sys
import yaml
from uuid import uuid4

from bitmath import GiB

from .. import EMCVnxBlockDeviceAPI
from .._driver import UNKNOWN_COMPUTE_ID

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
                    # XXX A hack to work around the LUN name length limit. We
                    # need a better way to store the cluster_id.
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
    def test_list_foreign_attachments(self):
        """
        ``BlockDeviceVolume.attached_to`` is set to ``UNKNOWN_COMPUTE_ID`` for
        volumes that are attached to other nodes.
        """
        # Create the volume we'll detach.
        volume = self.api.create_volume(
            dataset_id=uuid4(), size=self.minimum_allocatable_size
        )
        # Attach volume to some other StorageGroup using _emc_vnx_client
        lun_name = self.api._get_lun_name_from_blockdevice_id(
            volume.blockdevice_id
        )
        alu = self.api._client.get_lun_by_name(lun_name)['lun_id']
        storage_groups = self.api._client.storage_groups()
        foreign_storage_group_name, foreign_storage_group = [
            (group_name, group)
            for group_name, group in storage_groups.items()
            if group_name != self.api._group
            and re.match(r'Docker\d+', group_name)
        ][0]
        hlu = self.api._choose_hlu(
            foreign_storage_group['lunmap']
        )
        rc, out = self.api._client.add_volume_to_sg(
            str(hlu), str(alu), foreign_storage_group_name
        )
        if rc == 0:
            self.addCleanup(
                lambda: self.api._client.remove_volume_from_sg(
                    str(hlu),
                    foreign_storage_group_name
                )
            )
        else:
            raise Exception(rc, out)

        self.assertEqual(
            [volume.set('attached_to', UNKNOWN_COMPUTE_ID)],
            self.api.list_volumes()
        )
