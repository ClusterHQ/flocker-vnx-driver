# flocker-vnx-driver
EMC VNX driver for Flocker.

This driver is tested on Ubuntu 14.04.

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

## Standalone Test Setup

Set VNX_CONFIG_FILE:

```
root@sclf200:~/flocker-vnx-driver# export VNX_CONFIG_FILE=/home/ctoguest/flocker-vnx-driver/config.yml
```

### Test inside a Docker container

Build and start a container for unit testing.  Mount naviseccli security keys path into container.

```
$ ls /home/core/myechuri | grep Secured
SecuredCLISecurityFile.xml
SecuredCLIXMLEncrypted.key
$ docker build -t myechuri/vnxtest .
$ docker run -v /home/core/myechuri:/root -v /home/core/navisecclisec:/keys -ti myechuri/vnxtest
root@0a290220ae82:/flocker-vnx-driver# trial test_emc_vnx.EMCVnxBlockDeviceAPIInterfaceTests.test_interface
```
