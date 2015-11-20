# flocker-vnx-driver
EMC VNX driver for Flocker.

This driver is tested on Ubuntu 14.04.

## Prerequisites

### Flocker

See https://docs.clusterhq.com/en/1.7.2/install

### SCSI Utilities

```
apt-get install \
      sg3-utils \
      scsitools \
      lsscsi
```

### Naviseccli

Install the CLI.

```
wget https://github.com/emc-openstack/naviseccli/raw/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
dpkg -i navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
```

Create credential files.

```
/opt/Navisphere/bin/naviseccli \
       -secfilepath /keys \
       -h 192.168.40.13 \
       -AddUserSecurity \
       -Scope 0 \
       -user <VNX_USERNAME> \
       -password <VNX_PASSWORD>
```


## Install driver

```
# /opt/flocker/bin/pip install git+https://github.com/ClusterHQ/flocker-vnx-driver.git
```

## Standalone Test Setup

```
# export VNX_CONFIG_FILE=/etc/flocker/agent.yml
# /opt/flocker/bin/trial flocker_emc_vnx_driver
```

### Test inside a Docker container

Build a Docker image for functional testing.

```
$ docker build --tag=clusterhq/flocker-vnx-driver-test-runner .
```

Create ``naviseccli`` credentials

```
docker run --rm \
       --net host \
       --volume $HOME/etc_flocker/keys:/keys \
       clusterhq/naviseccli \
       -addusersecurity -scope 0 -user <USER> -password <PASSWORD>
```

```
ls -1 /home/core/etc_flocker/keys
SecuredCLISecurityFile.xml
SecuredCLIXMLEncrypted.key
```

Run the tests in a container.

```
docker run \
       --rm \
       --net host \
       --privileged \
       --volume /dev:/dev \
       --volume /home/core/etc_flocker:/etc/flocker \
       --env VNX_CONFIG_FILE=/etc/flocker/agent.yml \
       clusterhq/flocker-vnx-driver-test-runner
```
