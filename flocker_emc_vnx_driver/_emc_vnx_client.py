import re
import time

import subprocess


CLI_PATH = '/opt/Navisphere/bin/naviseccli'


def execute(*cmd):
    try:
        _PIPE = subprocess.PIPE
        obj = subprocess.Popen(
            cmd, stdin=_PIPE, stdout=_PIPE,
            close_fds=True, shell=False)
        out, err = obj.communicate()
        obj.stdin.close()
        _returncode = obj.returncode
        return _returncode, out, err
    finally:
        time.sleep(0)


class PropertyDescriptor(object):
    def __init__(self, option, label, key, converter=None):
        self.option = option
        self.label = label
        self.key = key
        self.converter = converter


class EMCVNXClient(object):

    POOL_NAME = PropertyDescriptor(
        '-name',
        'Pool Name:\s*(.*)\s*',
        'pool_name')

    LUN_STATE = PropertyDescriptor(
        '-state',
        'Current State:\s*(.*)\s*',
        'state')
    LUN_STATUS = PropertyDescriptor(
        '-status',
        'Status:\s*(.*)\s*',
        'status')
    LUN_NAME = PropertyDescriptor(
        '-name',
        'Name:\s*(.*)\s*',
        'lun_name')
    LUN_CAPACITY = PropertyDescriptor(
        '-userCap',
        'User Capacity \(GBs\):\s*(.*)\s*',
        'total_capacity_gb',
        float)
    LUN_ID = PropertyDescriptor(
        '-id',
        'LOGICAL UNIT NUMBER\s*(\d+)\s*',
        'lun_id',
        int)

    LUN_UID = PropertyDescriptor(
        '-id',
        'UID:\s*([0-9A-F:]+)\s*',
        'lun_uid',
        lambda val: val.replace(':', '').lower())

    LUN_ALL = [LUN_STATE, LUN_STATUS, LUN_NAME, LUN_CAPACITY, LUN_ID, LUN_UID]

    def __init__(self, ip, key_path):
        self.ip = ip
        self.key_path = key_path
        self.cli = (CLI_PATH, '-h', self.ip, '-secfilepath', self.key_path)

        # This is a temporary fencing solution for a specific POC.
        # Please do not set ``base_lun`` for generic VNX usage.
        # self.next_lun = base_lun

    def check_pool(self, name):
        cmd = self.cli + ('storagepool', '-list', '-name', name)
        data = self._get_obj_props(cmd, [self.POOL_NAME])
        return data != {}

    def get_lun_by_name(self, name):
        cmd = self.cli + ('lun', '-list', '-name', name)
        return self._get_obj_props(cmd, self.LUN_ALL)

    def get_all_luns(self):
        cmd = self.cli + ('lun', '-list')
        rc, out, err = execute(*cmd)
        luns = []
        if rc == 0:
            raw_luns = out.split('\n\n')
            for each in raw_luns:
                if each == '':
                    continue
                lun = {
                    prop.key:
                        self._get_prop_value(each, prop)
                    for prop in self.LUN_ALL
                }
                luns.append(lun)
        return luns

    def _get_obj_props(self, cmd, props):
        rc, out, err = execute(*cmd)
        data = {}
        if rc == 0:
            data = {
                prop.key:
                    self._get_prop_value(out, prop)
                for prop in props
            }
        return data

    def _get_prop_value(self, out, prop):
        label = prop.label
        m = re.search(label, out)
        if m:
            if (prop.converter is not None):
                try:
                    return prop.converter(m.group(1))
                except ValueError:
                    return None
            else:
                return m.group(1)
        else:
            return None

    def create_volume(self, name, size, pool):
        # TODO: pass in lun number (below) for lun fencing.
        # '-poolName', pool, '-l', self.next_lun, '-name', name)
        cmd = ('lun', '-create', '-capacity', size, '-sq', 'gb',
               '-poolName', pool, '-name', name)
        cmd = self.cli + cmd
        rc, out, err = execute(*cmd)
        # self.next_lun = self.next_lun + 1
        return rc, out

    def wait_for_volume(self, name, timeout=300):
        start = time.time()
        while time.time() - start < timeout:
            lun = self.get_lun_by_name(name)
            if not lun:
                return
            elif lun['state'] in ['Ready', 'Faulted']:
                return
        raise Exception('Timeout when waiting for a volume')

    def destroy_volume(self, name):
        cmd = ('lun', '-destroy', '-name', name,
               '-forceDetach', '-o')
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def create_storage_group(self, name):
        cmd = ('storagegroup', '-create', '-gname', name)
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def get_storage_group(self, name):
        cmd = ('storagegroup', '-list', '-gname', name,
               '-host', '-iscsiAttributes')
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def storage_groups(self):
        cmd = ('storagegroup', '-list', '-host', '-iscsiAttributes')
        rc, out, err = execute(*(self.cli + cmd))
        if rc != 0:
            raise Exception(rc, out, err)
        groups = {}
        for group_content in out.split('Storage Group Name:    '):
            group_name, group_content = group_content.split('\n', 1)
            group_name = group_name.strip()
            group_info = self.parse_sg_content(group_content)
            groups[group_name] = group_info
        return groups

    def parse_sg_content(self, content):
        lun_map = {}
        data = {'storage_group_uid': None,
                'lunmap': lun_map,
                'raw_output': ''}
        data['raw_output'] = content
        re_storage_group_id = 'Storage Group UID:\s*(.*)\s*'
        m = re.search(re_storage_group_id, content)
        if m is not None:
            data['storage_group_uid'] = m.group(1)

        re_hlu_alu_pair = 'HLU\/ALU Pairs:\s*HLU Number' \
                          '\s*ALU Number\s*[-\s]*(?P<lun_details>(\d+\s*)+)'
        m = re.search(re_hlu_alu_pair, content)
        if m is not None:
            lun_details = m.group('lun_details').strip()
            values = re.split('\s*', lun_details)
            while (len(values) >= 2):
                key = values.pop()
                value = values.pop()
                lun_map[int(key)] = int(value)
        return data

    def add_volume_to_sg(self, hlu, alu, sg_name):
        cmd = ('storagegroup', '-addhlu', '-hlu', hlu,
               '-alu', alu, '-gname', sg_name, '-o')
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def remove_volume_from_sg(self, hlu, sg_name):
        cmd = ('storagegroup', '-removehlu', '-hlu', hlu,
               '-gname', sg_name, '-o')
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def connect_host_to_sg(self, host, sg_name):
        cmd = ('storagegroup', '-connecthost', '-host', host,
               '-gname', sg_name, '-o')
        rc, out, err = execute(*(self.cli + cmd))
        return rc, out

    def get_iscsi_targets(self):
        cmd = ('connection', '-getport', '-address', '-vlanid')
        rc, out, err = execute(*(self.cli + cmd))
        if rc != 0:
            raise Exception("Get port failed")
        iscsi_target_dict = {'A': [], 'B': []}
        iscsi_spport_pat = r'(A|B)\s*' + \
                           r'Port ID:\s+(\d+)\s*' + \
                           r'Port WWN:\s+(iqn\S+)'
        iscsi_vport_pat = r'Virtual Port ID:\s+(\d+)\s*' + \
                          r'VLAN ID:\s*\S*\s*' + \
                          r'IP Address:\s+(\S+)'
        for spport_content in re.split(r'^SP:\s+|\nSP:\s*', out):
            m_spport = re.match(iscsi_spport_pat, spport_content,
                                flags=re.IGNORECASE)
            if not m_spport:
                continue
            sp = m_spport.group(1)
            port_id = int(m_spport.group(2))
            iqn = m_spport.group(3)
            for m_vport in re.finditer(iscsi_vport_pat, spport_content):
                vport_id = int(m_vport.group(1))
                ip_addr = m_vport.group(2)
                if ip_addr.find('N/A') != -1:
                    continue
                iscsi_target_dict[sp].append({'SP': sp,
                                              'Port ID': port_id,
                                              'Port WWN': iqn,
                                              'Virtual Port ID': vport_id,
                                              'IP Address': ip_addr})
        return iscsi_target_dict


if __name__ == '__main__':
    cli = EMCVNXClient('192.168.40.13')
    luns = cli.get_all_luns()
    print luns
