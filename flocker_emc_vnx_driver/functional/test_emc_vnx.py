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
    def test_list_foreign_attachments(self):
        """
        A node can see that a LUN has been added to another storage group but
        that's all.  It can't know whether the host in that foreign storage
        group has created a device for the LUN.  As far as we know, it's
        non-manifest.  But problems occure if we report it as non-manifest and
        our BlockDeviceDeployer reports it as a non-manifest volume in the
        NodeState.  The control service ends up seeing and reporting a
        DeployementState where a dataset is both manifest on the other node and
        non-manifest.  This would be fixed if there was a remote dataset agent,
        responsible for creating, remote_attach, remote_detach, delete.  And a
        local dataset agent responsible for detecting and assigning a device
        path to the volume on the host.

        There are two possible workarounds:
         * List the volume as attached to a random non-local compute_id...the
           local deployer only reports the state of locally attached and
           non-manifest datasets.
         * Don't list volumes which appear to be attached to other nodes.
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

        self.assertEqual([], self.api.list_volumes())
