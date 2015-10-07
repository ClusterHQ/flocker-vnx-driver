
from flocker.node.agents.blockdevice import (
    VolumeException, AlreadyAttachedVolume,
    UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI, _blockdevicevolume_from_dataset_id,
    _blockdevicevolume_from_blockdevice_id
)

from eliot import Message, Logger
from twisted.python.filepath import FilePath
from zope.interface import implementer
from subprocess import check_output

import base64
import urllib
import urllib2
import json
import os
import random
import re
import socket

from emc_vnx_client import EMCVNXClient

LUN_NAME_PREFIX = 'flocker-'

_logger = Logger()


def vnx_api(cluster_id, user, password, ip, pool):
    return EMCVNXBlockDeviceAPI(cluster_id, user, password, ip, pool)

def rescan_iscsi(number=None):
    check_output(["rescan-scsi-bus", "-r", "-c", "2"])

def get_iqn():
    out = check_output(["cat", "/etc/iscsi/initiatorname.iscsi"])
    return out.split('\n')[-2].split('=')[-1]


@implementer(IBlockDeviceAPI)
class EMCVnxBlockDeviceAPI(object):

    VERSION = '0.1'
    driver_name = 'VNX'

    def __init__(self, cluster_id, user, password, ip, pool, group):
        self._client = EMCVNXClient(user, password, ip)
        self._cluster_id = cluster_id
        self._pool = pool
        self._hostname = unicode(socket.gethostname())
        self._group = group
        self._setup()

    def _setup(self):
        #print('New EMC VNX flocker driver setup')
        Message.new(info=u'Entering EMC VNX _setup').write(_logger)
        if not self._client.check_pool(self._pool):
             raise Exception('The pool does not exist')
        self.iscsi_targets = self._client.get_iscsi_targets()

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
        Message.new(info=u'Entering EMC VNX create_volume').write(_logger)
        volume = _blockdevicevolume_from_dataset_id(
            size=size, dataset_id=dataset_id)
        lun_name = self._get_lun_name_from_blockdevice_id(volume.blockdevice_id)
        out = os.system("lsscsi")
        rc, out = self._client.create_volume(
            lun_name,
            str(self._convert_volume_size(size)),
            self._pool)
        if rc != 0 and out.find('Unable to create the LUN because the specified name is already in use') == -1: 
            raise Exception(out)
        return volume

    def destroy_volume(self, blockdevice_id):
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        self._client.destroy_volume(lun_name)

    def _get_device_list(self):
        """
        """
        cmd = ('lsscsi')
        output = check_output([b"lsscsi"])
        device_names = []
        for line in output.splitlines():
            device_file = line.split()[5]
            device_names.append(device_file)
        return device_names

    def attach_volume(self, blockdevice_id, attach_to):
        Message.new(info=u'Entering EMC VNX attach_volume',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        lun = self._client.get_lun_by_name(lun_name)
        alu = lun['lun_id']
        hlu = self.choose_hlu(self._group)

        # Get list of devices before adding volume to storage group
        device_list_before_attach = self._get_device_list()

        self._client.add_volume_to_sg(str(hlu), str(alu), self._group)
        volume = _blockdevicevolume_from_blockdevice_id(
            blockdevice_id=blockdevice_id,
            size=int(lun['total_capacity_gb']*1024*1024*1024),
            attached_to=unicode(attach_to)
        )
        # Rescan scsi bus to discover new volume
        rescan_iscsi(hlu)

        device_list_after_attach = self._get_device_list()
        import pdb; pdb.set_trace()
        return volume
        
    def detach_volume(self, blockdevice_id):
        Message.new(info=u'Entering EMC VNX detach_volume',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        alu = self._client.get_lun_by_name(lun_name)['lun_id'] 
        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
             raise Exception('SG does not exist')
        hlu = self._client.parse_sg_content(out)['lunmap'][alu]
        self._client.remove_volume_from_sg(str(hlu), self._group)
        rescan_iscsi(hlu)

    def list_volumes(self):
        Message.new(info=u'Entering EMC VNX list_volumes').write(_logger)
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
                if lun_map.has_key(each['lun_id']):
                    attached_to = unicode(self._hostname)
                lun_name = each['lun_name']
                blockdevice_id = self._get_blockdevice_id_from_lun_name(lun_name)
                vol = _blockdevicevolume_from_blockdevice_id(
                    blockdevice_id=blockdevice_id,
                    size=int(1024*1024*1024*each['total_capacity_gb']),
                    attached_to=attached_to)
                volumes.append(vol)
        return volumes

    def get_device_path(self, blockdevice_id):
        Message.new(info=u'Entering EMC VNX get_device_path',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun_name = self._get_lun_name_from_blockdevice_id(blockdevice_id)
        lun = self._client.get_lun_by_name(lun_name)
        rc, out = self._client.get_storage_group(self._group)
        if rc != 0:
             raise Exception('SG does not exist')
        lun_map = self._client.parse_sg_content(out)['lunmap']
        hlu = lun_map[lun['lun_id']]
        portals = self.get_iscsi_target_portals(get_iqn(),
                                                self._group)
        device_name = "ip-%s:3260-iscsi-%s-lun-%s" % (portals[0]['IP Address'],
                                                      portals[0]['Port WWN'],
                                                      str(hlu))
        device = '/dev/disk/by-path/%s' % device_name
        if self.discover_device(device):
            return FilePath(device).realpath()
        else:
            raise Exception('Device not found')

    def discover_device(self, device):
        a = 5
        tries = 0
        while tries < a:
            tries = tries + 1
            if os.path.exists(device):
                return True
            else:
                rescan_iscsi() 
        return False 
 
    def allocation_unit(self):
        Message.new(info=u'Entering EMC VNX allocation_unit').write(_logger)
        return 1

    def compute_instance_id(self):
        Message.new(info=u'Entering EMC VNX compute_instance_id',
                    hostanme=self._hostname).write(_logger)
        return self._hostname

    def choose_hlu(self, sg_name):
        rc, out = self._client.get_storage_group(sg_name)
        if rc != 0:
             raise Exception('SG does not exist')
        lun_map = self._client.parse_sg_content(out)['lunmap']
        candicates = list(set(range(1, 256)) - set(lun_map.values()))
        return candicates[random.randint(0, len(candicates)-1)] 

    def get_iscsi_target_portals(self, initiator, sg_name):
        rc, out = self._client.get_storage_group(sg_name)
        if rc != 0:
             raise Exception('SG does not exist')
        spport_set = set()
        for m_spport in re.finditer(
                r'\n\s+%s\s+SP\s.*\n.*\n\s*SPPort:\s+(A|B)-(\d+)v(\d+)\s*\n'
                % initiator, out, flags=re.IGNORECASE):
            spport_set.add((m_spport.group(1), int(m_spport.group(2)),
                           int(m_spport.group(3))))

        target_portals = []
        all_portals = self.iscsi_targets['A'] + self.iscsi_targets['B']
        random.shuffle(all_portals)
        for portal in all_portals:
            spport = (portal['SP'],
                      portal['Port ID'],
                      portal['Virtual Port ID'])
            if spport not in spport_set:
                continue
            target_portals.append(portal)
        return target_portals
