
from flocker.node.agents.blockdevice import (
    AlreadyAttachedVolume, UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI, _blockdevicevolume_from_dataset_id,
    _blockdevicevolume_from_blockdevice_id
)

from eliot import Message, Logger
from pyrsistent import pmap
from twisted.python.filepath import FilePath
from zope.interface import implementer
from subprocess import check_output

import random
import socket

from emc_vnx_client import EMCVNXClient

LUN_NAME_PREFIX = 'flocker-'

_logger = Logger()


def vnx_from_configuration(cluster_id, ip, pool, lun_base):
    return EMCVnxBlockDeviceAPI(cluster_id, ip, pool, lun_base)


@implementer(IBlockDeviceAPI)
class EMCVnxBlockDeviceAPI(object):

    VERSION = '0.1'
    driver_name = 'VNX'

    def __init__(self, cluster_id, ip, pool, lun_base):
        self._client = EMCVNXClient(ip, lun_base)
        self._cluster_id = cluster_id
        self._pool = pool
        self._hostname = unicode(socket.gethostname())
        self._group = u'Flocker' + self._hostname
        self._client.create_storage_group(self._group)
        self._client.connect_host_to_sg(self._hostname, self._group)
        self._device_path_map = pmap()

    def _rescan_iscsi(self, number=None):
        check_output(["rescan-scsi-bus", "-r", "-c", "2"])

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
            size=size, dataset_id=dataset_id)
        lun_name = self._get_lun_name_from_blockdevice_id(
            volume.blockdevice_id)
        rc, out = self._client.create_volume(
            lun_name,
            str(self._convert_volume_size(size)),
            self._pool)
        Message.new(operation=u'create_volume_output',
                    dataset_id=str(dataset_id),
                    size=size,
                    lun_name=lun_name,
                    rc=rc,
                    out=out).write(_logger)
        if rc != 0 and out.find('Unable to create the LUN \
                because the specified name is already in use') == -1:
            raise Exception(out)
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
        if rc == 9:
            raise UnknownVolume(blockdevice_id)

    def _get_device_list(self):
        """
        """
        output = check_output([b"lsscsi"])
        device_names = []
        Message.new(operation=u'lsscsi',
                    output=output).write(_logger)
        for line in output.splitlines():
            device_file = line.split()[5]
            device_names.append(device_file)
        return set(device_names)

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

        # Get list of devices before adding volume to storage group
        self._rescan_iscsi(hlu)
        devices_before_attach = self._get_device_list()

        rc, out = self._client.add_volume_to_sg(str(hlu),
                                                str(alu),
                                                self._group)
        if rc == 66:
            raise AlreadyAttachedVolume(blockdevice_id)

        volume = _blockdevicevolume_from_blockdevice_id(
            blockdevice_id=blockdevice_id,
            size=int(lun['total_capacity_gb']*1024*1024*1024),
            attached_to=unicode(attach_to)
        )
        # Rescan scsi bus to discover new volume
        self._rescan_iscsi(hlu)
        devices_after_attach = self._get_device_list()
        new_device = list(devices_after_attach - devices_before_attach)[0]
        self._device_path_map = self._device_path_map.set(blockdevice_id,
                                                          FilePath(new_device))
        Message.new(operation=u'attach_volume_output',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to,
                    lun_name=lun_name,
                    alu=alu,
                    hlu=hlu,
                    devices_before_attach=devices_before_attach,
                    devices_after_attach=devices_after_attach,
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
            raise Exception('SG does not exist')

        try:
            hlu = self._client.parse_sg_content(out)['lunmap'][alu]
        except KeyError:
            raise UnattachedVolume(blockdevice_id)

        self._client.remove_volume_from_sg(str(hlu), self._group)
        self._rescan_iscsi(hlu)
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
            raise Exception('SG does not exist')
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
            raise Exception('SG does not exist')
        lun_map = self._client.parse_sg_content(out)['lunmap']
        candicates = list(set(range(1, 256)) - set(lun_map.values()))
        return candicates[random.randint(0, len(candicates)-1)]
