
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


_logger = Logger()


def vnx_api(cluster_id, user, password, ip, pool):
    return EMCVNXBlockAPI(cluster_id, user, password, ip, pool)

def rescan_iscsi(number=None):
    cmd = ["rescan-scsi-bus", "-r", "-c"]
    if number:
       cmd.append(str(number))
    check_output(["rescan-scsi-bus", "-r", "-c"])

def get_iqn():
    out = check_output(["cat", "/etc/iscsi/initiatorname.iscsi"])
    return out.split('\n')[-2].split('=')[-1]


@implementer(IBlockDeviceAPI)
class EMCVNXBlockAPI(object):

    VERSION = '0.1'
    driver_name = 'VNX'

    def __init__(self, cluster_id, user, password, ip, pool):
        self._client = EMCVNXClient(user, password, ip)
        self._cluster_id = cluster_id
        self._pool = pool
        self._hostname = socket.gethostname()
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

    def create_volume(self, dataset_id, size):
        Message.new(info=u'Entering EMC VNX create_volume').write(_logger)
        volume = _blockdevicevolume_from_dataset_id(
            size=size, dataset_id=dataset_id)
        rc, out = self._client.create_volume(
            str(volume.blockdevice_id),
            str(self._convert_volume_size(size)),
            self._pool)
        if rc != 0 and out.find('Unable to create the LUN because the specified name is already in use') == -1: 
            raise Exception(out)
        return volume

    def destroy_volume(self, blockdevice_id):
        Message.new(info=u'Entering EMC VNX destroy_volume',
                    blockdevice_id=blockdevice_id).write(_logger)
        self.destroy_volume(str(blockdevice_id))

    def attach_volume(self, blockdevice_id, attach_to):
        Message.new(info=u'Entering EMC VNX attach_volume',
                    blockdevice_id=blockdevice_id,
                    attach_to=attach_to).write(_logger)
        self._client.create_storage_group(str(attach_to))
        self._client.connect_host_to_sg(str(attach_to), str(attach_to))
        lun = self._client.get_lun_by_name(blockdevice_id)
        alu = lun['lun_id']
        hlu = self.choose_hlu(str(attach_to))
        self._client.add_volume_to_sg(str(hlu), str(alu), str(attach_to))
        volume = _blockdevicevolume_from_blockdevice_id(
            blockdevice_id=blockdevice_id,
            size=int(lun['total_capacity_gb']*1024*1024*1024),
            attached_to=unicode(attach_to)
        )
        return volume
        
    def resize_volume(self, blockdevice_id, size):
        Message.new(info=u'Entering EMC VNX resize_volume',
                    blockdevice_id=blockdevice_id).write(_logger)

    def detach_volume(self, blockdevice_id):
        Message.new(info=u'Entering EMC VNX detach_volume',
                    blockdevice_id=blockdevice_id).write(_logger)
        alu = self._client.get_lun_by_name(blockdevice_id)['lun_id'] 
        rc, out = self._client.get_storage_group(self._hostname)
        if rc != 0:
             raise Exception('SG does not exist')
        hlu = self._client.parse_sg_content(out)['lunmap'][alu]
        self._client.remove_volume_from_sg(str(hlu), self._hostname)
        rescan_iscsi(hlu)

    def list_volumes(self):
        Message.new(info=u'Entering EMC VNX list_volumes').write(_logger)
        fake_vol = _blockdevicevolume_from_blockdevice_id(
            blockdevice_id=u'block-886ed03a-5606-453a-94a9-a1cbaf35164c',
            size=1024*1024*1024,
            attached_to=u'f_host')
        volumes = []
        volumes.append(fake_vol)

        # get lun_map of this node
        rc, out = self._client.get_storage_group(self._hostname)
        if rc != 0:
             raise Exception('SG does not exist')
        lun_map = self._client.parse_sg_content(out)['lunmap']
        
        # add luns which belong to flocker
        luns = self._client.get_all_luns()
        for each in luns:
            if each['lun_name'].startswith('block-'):
                attached_to = None
                if lun_map.has_key(each['lun_id']):
                    attached_to = unicode(self._hostname)
                vol = _blockdevicevolume_from_blockdevice_id(
                    blockdevice_id=unicode(each['lun_name']),
                    size=int(1024*1024*1024*each['total_capacity_gb']),
                    attached_to=attached_to)
                volumes.append(vol)
        return volumes

    def get_device_path(self, blockdevice_id):
        Message.new(info=u'Entering EMC VNX get_device_path',
                    blockdevice_id=blockdevice_id).write(_logger)
        lun = self._client.get_lun_by_name(blockdevice_id)
        rc, out = self._client.get_storage_group(self._hostname)
        if rc != 0:
             raise Exception('SG does not exist')
        lun_map = self._client.parse_sg_content(out)['lunmap']
        hlu = lun_map[lun['lun_id']]
        portals = self.get_iscsi_target_portals(get_iqn(),
                                                self._hostname)
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


if __name__ == '__main__':
    api = EMCVNXBlockAPI(None, 'sysadmin', 'sysadmin', '192.168.1.94', 'Pool_1')
    import pdb;pdb.set_trace()
    #volume = api.attach_volume('flocker-test-02', api._hostname)
    
    #api.get_device_path('flocker-test-02')
    vols = api.list_volumes()
    print vols
