import os
import time

from flocker.node.agents.blockdevice import (
    AlreadyAttachedVolume, UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI, _blockdevicevolume_from_dataset_id,
    _blockdevicevolume_from_blockdevice_id,
)

from eliot import Message
from pyrsistent import pmap
from twisted.python.filepath import FilePath
from zope.interface import implementer
from subprocess import check_output, CalledProcessError

import random

from emc_vnx_client import EMCVNXClient

LUN_NAME_PREFIX = 'flocker-'


def vnx_from_configuration(cluster_id, ip, pool):
    return EMCVnxBlockDeviceAPI(cluster_id, ip, pool)


class Timeout(Exception):
    """
    """


def wait_for(predicate, timeout):
    start_time = time.time()
    while True:
        result = predicate()
        if result:
            return result
        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
            raise Timeout(predicate)
        else:
            time.sleep(1)


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
        self._device_path_map = pmap()

    def _convert_volume_size(self, size):
        """
        convert KB to GB
        """
        return size/(1024*1024*1024)

    def _get_lun_name_from_blockdevice_id(self, blockdevice_id):
        return LUN_NAME_PREFIX + str(blockdevice_id)

    def _get_blockdevice_id_from_lun_name(self, lun_name):
        return unicode(lun_name.split(LUN_NAME_PREFIX, 1)[1])

    def create_volume(self, dataset_id, size):
        Message.new(operation=u'create_volume',
                    dataset_id=str(dataset_id),
                    size=size).write()
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
                    out=out).write()
        if rc != 0:
            raise Exception(rc, out)
        return volume

    def destroy_volume(self, blockdevice_id):
        Message.new(operation=u'destroy_volume',
                    blockdevice_id=blockdevice_id).write()
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        rc, out = self._client.destroy_volume(lun_name)
        Message.new(operation=u'destroy_volume_output',
                    blockdevice_id=blockdevice_id,
                    lun_name=lun_name,
                    rc=rc,
                    out=out).write()
        if rc != 0:
            if rc == 9:
                raise UnknownVolume(blockdevice_id)
            else:
                raise Exception(rc, out)

    def attach_volume(self, blockdevice_id, attach_to):
        Message.new(operation=u'attach_volume',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to).write()
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

        # Rescan and wait for the expected bus 3 times and wait successively
        # longer for the device to appear.
        # Sometimes the bus doesn't appear until you rescan repeatedly.
        # XXX Often it never appears....which is a problem
        counter = 1
        start_time = time.time()
        hlu_bus = FilePath(
            '/sys/class/scsi_disk/1:0:0:{}'.format(hlu)
        )
        while True:
            with open(os.devnull, 'w') as discard:
                check_output(
                    ["rescan-scsi-bus", "--luns={}".format(hlu)],
                    stderr=discard
                )
            try:
                wait_for(
                    predicate=hlu_bus.exists,
                    timeout=5 * counter
                )
                break
            except Timeout:
                if counter > 3:
                    import pdb; pdb.set_trace()
                    elapsed_time = time.time() - start_time
                    raise Timeout(
                        "HLU bus did not appear. "
                        "Expected {}. "
                        "Waited {}s and performed {} scsi bus rescans.".format(
                            hlu_bus,
                            elapsed_time,
                            counter,
                        ),
                        hlu_bus, elapsed_time, counter
                    )
                else:
                    counter += 1

        # Once the bus is available we can discover the device path and check
        # that the device path is usable It may not be usable. For example the
        # device is sometimes initially 0 size until you force a rescan:

        # (echo 1 > /sys/class/scsi_disk/1:0:0:219/device/rescan)
        # Nov 07 04:55:40 00009bb1a4558a12 kernel: sd 1:0:0:219: [sdup] 16777216 512-byte logical blocks: (8.58 GB/8.00 GiB)
        # Nov 07 04:55:40 00009bb1a4558a12 kernel: sdup: detected capacity change from 0 to 8589934592
        def device_is_usable(device_path):
            try:
                check_output(['lsblk', device_path.path])
            except CalledProcessError:
                return False
            else:
                return True

        [device_name_pointer] = hlu_bus.descendant(
            ['device', 'block']
        ).children()
        new_device = FilePath('/dev').child(
            device_name_pointer.basename()
        )
        rescan_device = hlu_bus.descendant(['device', 'rescan'])
        counter = 1
        while True:
            try:
                wait_for(
                    predicate=lambda: device_is_usable(new_device),
                    timeout=5 * counter
                )
                break
            except Timeout:
                if counter > 3:
                    import pdb; pdb.set_trace()
                    elapsed_time = time.time() - start_time
                    raise Timeout(
                        "Device did not appear. "
                        "Expected {}. "
                        "Waited {}s and performed {} scsi bus rescans.".format(
                            new_device,
                            elapsed_time,
                            counter,
                        ),
                        new_device, elapsed_time, counter
                    )
                else:
                    with rescan_device.open('w') as f:
                        f.write('1\n')
                    counter += 1

        self._device_path_map = self._device_path_map.set(
            blockdevice_id, new_device
        )
        Message.new(
            operation=u'attach_volume_output',
            blockdevice_id=blockdevice_id,
            attach_to=attach_to,
            lun_name=lun_name,
            alu=alu,
            hlu=hlu,
            device_path_map=repr(self._device_path_map)
        ).write()
        return volume

    def detach_volume(self, blockdevice_id):
        Message.new(operation=u'detach_volume',
                    blockdevice_id=blockdevice_id).write()
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

        # Delete the specific buses that we're detached *before* we remove the
        # LUN from the Storage group
        for child in FilePath('/sys/bus/scsi/drivers/sd').children():
            alu_suffix = ':{}'.format(hlu)
            if child.basename().endswith(alu_suffix):
                with child.child('delete').open('w') as f:
                    f.write('1\n')

        rc, out = self._client.remove_volume_from_sg(str(hlu), self._group)
        if rc != 0:
            raise Exception(rc, out)

        self._device_path_map = self._device_path_map.remove(blockdevice_id)
        Message.new(operation=u'detach_volume_output',
                    blockdevice_id=blockdevice_id,
                    lun_name=lun_name,
                    alu=alu,
                    hlu=hlu,
                    rc=rc,
                    out=out,
                    device_path_map=repr(self._device_path_map)).write()

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
                    blockdevice_id=blockdevice_id).write()
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
                    allocation_unit=allocation_unit).write()
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
