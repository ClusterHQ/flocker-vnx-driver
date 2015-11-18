import os
import time

from flocker.node import BackendDescription, DeployerType
from flocker.node.agents.blockdevice import (
    AlreadyAttachedVolume, UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI,
)
from flocker.node.agents.loopback import (
    _blockdevicevolume_from_dataset_id,
    _blockdevicevolume_from_blockdevice_id,
)

from eliot import Message
from pyrsistent import pmap
from twisted.python.filepath import FilePath, UnlistableError
from zope.interface import implementer
from subprocess import check_output, CalledProcessError

import random

from ._emc_vnx_client import EMCVNXClient

LUN_NAME_PREFIX = 'flocker'


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


def _fc_hosts():
    return sorted(
        int(f.basename()[len('host'):])
        for f
        in FilePath('/sys/class/fc_host').children()
    )


def _hlu_bus_paths(hlu):
    return sorted(
        FilePath(
            '/sys/class/scsi_disk/{}:0:0:{}'.format(fc_host, hlu)
        )
        for fc_host in _fc_hosts()
    )


def _device_paths_for_hlu_bus_path(hlu_bus_path):
    return sorted(
        FilePath('/dev').child(
            device_name_pointer.basename()
        )
        for device_name_pointer
        in hlu_bus_path.descendant(
            ['device', 'block']
        ).children()
    )


def _device_path_is_usable(device_path):
    try:
        check_output(['lsblk', device_path.path])
    except CalledProcessError:
        return False
    else:
        return True


def _directory_listable(directory):
    try:
        directory.children()
    except UnlistableError:
        return False
    return True


@implementer(IBlockDeviceAPI)
class EMCVnxBlockDeviceAPI(object):

    VERSION = '0.1'
    driver_name = 'VNX'

    def __init__(self, cluster_id, spa_ip, storage_pool, hostname,
                 storage_group, naviseccli_keys):
        self._client = EMCVNXClient(spa_ip, naviseccli_keys)
        self._cluster_id = cluster_id
        self._pool = storage_pool
        self._hostname = unicode(hostname)
        self._group = unicode(storage_group)
        self._device_path_map = pmap()

    def _convert_volume_size(self, size):
        """
        convert KB to GB
        """
        return size/(1024*1024*1024)

    def _get_lun_name_from_blockdevice_id(self, blockdevice_id):
        return (
            LUN_NAME_PREFIX + '--' +
            str(self._cluster_id).split('-')[0] + '--' +
            str(blockdevice_id)
        )

    def _get_blockdevice_id_from_lun_name(self, lun_name):
        try:
            prefix, cluster_id, blockdevice_id = lun_name.rsplit('--', 2)
        except ValueError:
            return None
        # XXX This is risky, but VNX LUN names must be <=64 characters.
        short_lun_cluster_id = str(cluster_id).split('-')[0]
        short_api_cluster_id = str(self._cluster_id).split('-')[0]
        if short_lun_cluster_id != short_api_cluster_id:
            return None
        return blockdevice_id

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

        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
            raise Exception(rc, out)

        lunmap = self._client.parse_sg_content(out)['lunmap']
        try:
            # The LUN has already been added to this storage group....perhaps
            # by a previous attempt to attach in which the OS device did not
            # appear.
            hlu = lunmap[alu]
        except KeyError:
            # Add LUN to storage group
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
        # XXX This will only operate on the first available HLU bus
        hlu_bus_path = _hlu_bus_paths(hlu)[0]
        # /sys/class/scsi_disks/<fc_port>:0:0:<hlu>/device/block/ contains
        # symlinks whose names are the device names that have been allocated eg
        # sdvb.
        block_device_pointers = hlu_bus_path.descendant(['device', 'block'])
        while True:
            with open(os.devnull, 'w') as discard:
                check_output(
                    ["rescan-scsi-bus", "--luns={}".format(hlu)],
                    stderr=discard
                )
            try:
                wait_for(
                    predicate=lambda: _directory_listable(
                        block_device_pointers
                    ),
                    timeout=5 * counter
                )
                break
            except Timeout:
                if counter > 5:
                    import pdb; pdb.set_trace()
                    elapsed_time = time.time() - start_time
                    raise Timeout(
                        "HLU bus did not appear. "
                        "Expected {}. "
                        "Waited {}s and performed {} scsi bus rescans.".format(
                            hlu_bus_path,
                            elapsed_time,
                            counter,
                        ),
                        hlu_bus_path, elapsed_time, counter
                    )
                else:
                    counter += 1

        # Once the bus is available we can discover the device path and check
        # that the device path is usable It may not be usable. For example the
        # device is sometimes initially 0 size until you force a rescan:

        # (echo 1 > /sys/class/scsi_disk/1:0:0:219/device/rescan)
        # Nov 07 04:55:40 00009bb1a4558a12 kernel: sd 1:0:0:219: [sdup] 16777216 512-byte logical blocks: (8.58 GB/8.00 GiB)
        # Nov 07 04:55:40 00009bb1a4558a12 kernel: sdup: detected capacity change from 0 to 8589934592
        # XXX This will only operate on one of the resulting device paths.
        # /sys/class/scsi_disk/x:x:x:HLU/device/block/sdvb for example.
        new_device = _device_paths_for_hlu_bus_path(hlu_bus_path)[0]
        rescan_device = hlu_bus_path.descendant(['device', 'rescan'])
        counter = 1
        while True:
            try:
                wait_for(
                    predicate=lambda: _device_path_is_usable(new_device),
                    timeout=5 * counter
                )
                break
            except Timeout:
                if counter > 5:
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

        Message.new(
            operation=u'attach_volume_output',
            blockdevice_id=blockdevice_id,
            attach_to=attach_to,
            lun_name=lun_name,
            alu=alu,
            hlu=hlu,
            device_path=repr(new_device)
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

        Message.new(
            operation=u'detach_volume_output',
            blockdevice_id=blockdevice_id,
            lun_name=lun_name,
            alu=alu,
            hlu=hlu,
            rc=rc,
            out=out,
        ).write()

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
            blockdevice_id = self._get_blockdevice_id_from_lun_name(
                each['lun_name'].decode('ascii')
            )
            if blockdevice_id is not None:
                attached_to = None
                if each['lun_id'] in lun_map:
                    attached_to = unicode(self._hostname)
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

        alu = lun['lun_id']

        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
            raise Exception(rc, out)
        lunmap = self._client.parse_sg_content(out)['lunmap']
        try:
            # The LUN has already been added to this storage group....perhaps
            # by a previous attempt to attach in which the OS device did not
            # appear.
            hlu = lunmap[alu]
        except KeyError:
            raise UnattachedVolume(blockdevice_id)
        hlu_bus_path = _hlu_bus_paths(hlu)[0]

        # XXX This will only operate on one of the resulting device paths.
        # /sys/class/scsi_disk/x:x:x:HLU/device/block/sdvb for example.
        device_path = _device_paths_for_hlu_bus_path(hlu_bus_path)[0]

        if not _device_path_is_usable(device_path):
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


def api_factory(cluster_id, **kwargs):
    api = EMCVnxBlockDeviceAPI(cluster_id, **kwargs)
    return api


FLOCKER_BACKEND = BackendDescription(
    name=u"vnx_flocker_driver",
    needs_reactor=False,
    needs_cluster_id=True,
    api_factory=api_factory,
    deployer_type=DeployerType.block
)
