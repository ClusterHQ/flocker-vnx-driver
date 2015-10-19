# flocker-vnx-driver
EMC VNX driver for Flocker.

This driver is tested on Ubuntu 14.04 and CoreOS.

## Prereqs

### Naviseccli

Install naviseccli: https://github.com/emc-openstack/naviseccli/blob/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb

### sg3_utils


Get sg3_utils for ``rescan-scsi-bus``.

#### Ubuntu

apt-get install sg3-utils

### Install driver

```
python setup.py install
```

## Test Setup

Set VNX_CONFIG_FILE:

```
root@sclf200:~/flocker-vnx-driver# export VNX_CONFIG_FILE=/home/ctoguest/flocker-vnx-driver/config.yml
```


