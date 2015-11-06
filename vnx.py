import os
import time

from flocker.node.agents.blockdevice import (
    AlreadyAttachedVolume, UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI, _blockdevicevolume_from_dataset_id,
    _blockdevicevolume_from_blockdevice_id,
)

from eliot import Message, Logger
from pyrsistent import pmap
from twisted.python.filepath import FilePath
from zope.interface import implementer
from subprocess import check_output

import random
# import socket

from emc_vnx_client import EMCVNXClient

LUN_NAME_PREFIX = 'flocker-'

_logger = Logger()


def vnx_from_configuration(cluster_id, ip, pool):
    return EMCVnxBlockDeviceAPI(cluster_id, ip, pool)


@implementer(IBlockDeviceAPI)
class EMCVnxBlockDeviceAPI(object):

    VERSION = '0.1'
    driver_name = 'VNX'

    def __init__(self, cluster_id, ip, pool, host, group, keys):
        self._client = EMCVNXClient(ip, keys)
        self._cluster_id = cluster_id
        self._pool = pool
        self._hostname = unicode(host)
        self._group = unicode(group)
        # self._hostname = unicode(socket.gethostname())
        # hardcoded preprovisioned group for poc
        # self._group = u'Docker_Block'
        # self._group = u'Flocker' + self._hostname
        # self._client.create_storage_group(self._group)
        # self._client.connect_host_to_sg(self._hostname, self._group)
        self._device_path_map = pmap()

    def _rescan_scsi_bus(self):
        # Manual testing commands (in case of rescan-scsi-bus issues)
        # check_output(["echo", "1", ">",
        #               "/sys/class/fc_host/host6/issue_lip"])
        # check_output(["echo", "- - -", ">", "/sys/class/fc_host/host6/scan"])
        # Wait for 60s since lip is asynchronous.
        # time.sleep(60)
        # XXX: This is buggy. See:
        # https://bugzilla.novell.com/show_bug.cgi?id=815156#c8
        with open(os.devnull, 'w') as discard:
            for p in FilePath("/sys/class/fc_host").children():
                channel_number = p.basename()[len('host'):]
                check_output(
                    ["rescan-scsi-bus", "-r", "-c", channel_number],
                    stderr=discard
                )

    def _convert_volume_size(self, size):
        """
        convert KB to GB
        """
        return size/(1024*1024*1024)

    def _get_lun_name_from_blockdevice_id(self, blockdevice_id):
        """
        """
        return LUN_NAME_PREFIX + str(blockdevice_id)

    def _get_blockdevice_id_from_lun_name(self, lun_name):
        """
        """
        return unicode(lun_name.split(LUN_NAME_PREFIX, 1)[1])

    def create_volume(self, dataset_id, size):
        Message.new(operation=u'create_volume',
                    dataset_id=str(dataset_id),
                    size=size).write(_logger)
        volume = _blockdevicevolume_from_dataset_id(
            size=size, dataset_id=dataset_id
        )
        lun_name = self._get_lun_name_from_blockdevice_id(
            volume.blockdevice_id
        )
        rc, out = self._client.create_volume(
            lun_name,
            str(self._convert_volume_size(size)),
            self._pool
        )
        Message.new(operation=u'create_volume_output',
                    dataset_id=str(dataset_id),
                    size=size,
                    lun_name=lun_name,
                    rc=rc,
                    out=out).write(_logger)
        if rc != 0:
            raise Exception(rc, out)
        return volume

    def destroy_volume(self, blockdevice_id):
        Message.new(operation=u'destroy_volume',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        rc, out = self._client.destroy_volume(lun_name)
        Message.new(operation=u'destroy_volume_output',
                    blockdevice_id=blockdevice_id,
                    lun_name=lun_name,
                    rc=rc,
                    out=out).write(_logger)
        if rc != 0:
            if rc == 9:
                raise UnknownVolume(blockdevice_id)
            else:
                raise Exception(rc, out)

    def attach_volume(self, blockdevice_id, attach_to):
        Message.new(operation=u'attach_volume',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        lun = self._client.get_lun_by_name(lun_name)

        if lun == {}:
            raise UnknownVolume(blockdevice_id)
        alu = lun['lun_id']
        hlu = self.choose_hlu(self._group)

        rc, out = self._client.add_volume_to_sg(str(hlu),
                                                str(alu),
                                                self._group)
        if rc != 0:
            if rc == 66:
                raise AlreadyAttachedVolume(blockdevice_id)
            else:
                raise Exception(rc, out)

        volume = _blockdevicevolume_from_blockdevice_id(
            blockdevice_id=blockdevice_id,
            size=int(lun['total_capacity_gb']*1024*1024*1024),
            attached_to=unicode(attach_to)
        )
        # Rescan scsi bus to discover new volume
        self._rescan_scsi_bus()
        wwn_path = FilePath(
            '/dev/disk/by-id/wwn-0x{}'.format(lun['lun_uid'])
        )
        start_time = time.time()
        while not wwn_path.exists():
            elapsed_time = time.time() - start_time
            if elapsed_time > 10:
                raise Exception('Time out waiting for', wwn_path)
            else:
                time.sleep(1)
        new_device = wwn_path.realpath()
        self._device_path_map = self._device_path_map.set(
            blockdevice_id, new_device
        )
        Message.new(operation=u'attach_volume_output',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to,
                    lun_name=lun_name,
                    alu=alu,
                    hlu=hlu,
                    device_path_map=self._device_path_map).write()
        return volume

    def detach_volume(self, blockdevice_id):
        Message.new(operation=u'detach_volume',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        lun = self._client.get_lun_by_name(lun_name)
        if lun == {}:
            raise UnknownVolume(blockdevice_id)
        alu = lun['lun_id']
        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
            raise Exception(rc, out)

        lunmap = self._client.parse_sg_content(out)['lunmap']
        try:
            hlu = lunmap[alu]
        except KeyError:
            raise UnattachedVolume(blockdevice_id)

        rc, out = self._client.remove_volume_from_sg(str(hlu), self._group)
        if rc != 0:
            raise Exception(rc, out)

        self._rescan_scsi_bus()
        self._device_path_map = self._device_path_map.remove(blockdevice_id)
        Message.new(operation=u'detach_volume_output',
                    blockdevice_id=blockdevice_id,
                    lun_name=lun_name,
                    alu=alu,
                    hlu=hlu,
                    rc=rc,
                    out=out,
                    device_path_map=self._device_path_map).write()

    def list_volumes(self):
        volumes = []

        # get lun_map of this node
        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
            raise Exception(rc, out)

        lun_map = self._client.parse_sg_content(out)['lunmap']

        # add luns which belong to flocker
        luns = self._client.get_all_luns()
        for each in luns:
            if each['lun_name'].startswith(LUN_NAME_PREFIX):
                attached_to = None
                if each['lun_id'] in lun_map:
                    attached_to = unicode(self._hostname)
                lun_name = each['lun_name']
                blockdevice_id = self._get_blockdevice_id_from_lun_name(
                    lun_name)
                size = int(1024*1024*1024*each['total_capacity_gb'])
                vol = _blockdevicevolume_from_blockdevice_id(
                    blockdevice_id=blockdevice_id,
                    size=size,
                    attached_to=attached_to)
                Message.new(operation=u'list_volumes_output',
                            blockdevice_id=blockdevice_id,
                            size=size,
                            attached_to=attached_to).write()
                volumes.append(vol)
        return volumes

    def get_device_path(self, blockdevice_id):
        Message.new(operation=u'get_device_path',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        lun = self._client.get_lun_by_name(lun_name)
        if lun == {}:
            raise UnknownVolume(blockdevice_id)
        device_path = self._device_path_map.get(blockdevice_id)
        if device_path is None:
            raise UnattachedVolume(blockdevice_id)
        Message.new(operation=u'get_device_path_output',
                    blockdevice_id=blockdevice_id,
                    device_path=device_path.path).write()
        return device_path

    def allocation_unit(self):
        allocation_unit = 1
        Message.new(operation=u'allocation_unit',
                    allocation_unit=allocation_unit).write(_logger)
        return allocation_unit

    def compute_instance_id(self):
        Message.new(operation=u'compute_instance_id',
                    hostname=self._hostname).write()
        return self._hostname

    def choose_hlu(self, sg_name):
        rc, out = self._client.get_storage_group(sg_name)
        if rc != 0:
            raise Exception(rc, out)
        lun_map = self._client.parse_sg_content(out)['lunmap']
        candidates = list(set(range(1, 256)) - set(lun_map.values()))
        return candidates[random.randint(0, len(candidates)-1)]
