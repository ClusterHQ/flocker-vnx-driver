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
$ docker build --tag=clusterhq/flocker-vnx-driver .
```

Create ``naviseccli`` credentials

```
docker run \
       --rm \
       --net host \
       --volume /home/core/navisecclisec:/keys \
       --entrypoint /opt/Navisphere/bin/naviseccli \
       clusterhq/flocker-vnx-driver \
       -secfilepath /keys \
       -h 192.168.40.13 \
       -AddUserSecurity \
       -Scope 0 \
       -user <VNX_USERNAME> \
       -password <VNX_PASSWORD>
```

```
ls -1 /home/core/navisecclisec
SecuredCLISecurityFile.xml
SecuredCLIXMLEncrypted.key
```

Run the tests in a container.
Mount naviseccli security keys path into container.

```
$ docker run \
       --rm \
       --privileged \
       --net host
       --volume /dev:/dev \
       --volume /home/core/navisecclisec:/keys \
       --volume $PWD/flocker-vnx-driver:/flocker-vnx-driver \
       clusterhq/flocker-vnx-driver
```
