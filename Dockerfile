# Utility for testing VNX driver from inside a container
FROM ubuntu:14.04
MAINTAINER Madhuri Yechuri <madhuri.yechuri@clusterhq.com>

ENV FLOCKER_VERSION 1.2.0-1

RUN sudo apt-get update
RUN sudo apt-get -y install apt-transport-https software-properties-common
RUN sudo add-apt-repository -y ppa:james-page/docker
RUN sudo add-apt-repository -y "deb https://clusterhq-archive.s3.amazonaws.com/ubuntu/$(lsb_release --release --short)/\$(ARCH) /"

RUN sudo apt-get update && sudo apt-get -y --force-yes install \
      clusterhq-python-flocker=${FLOCKER_VERSION} \
      clusterhq-flocker-node=${FLOCKER_VERSION} \
      clusterhq-flocker-cli=${FLOCKER_VERSION}

RUN sudo apt-get -y --force-yes install \
      git \
      build-essential \
      libncurses5-dev \
      libslang2-dev \
      gettext \
      zlib1g-dev \
      libselinux1-dev \
      debhelper \
      lsb-release \
      pkg-config \
      po-debconf \
      autoconf \
      automake \
      autopoint \
      libtool

RUN sudo git clone git://git.kernel.org/pub/scm/utils/util-linux/util-linux.git util-linux
RUN sudo bash -c "cd util-linux; \
                  ./autogen.sh; \
                  ./configure --without-python --disable-all-programs --enable-nsenter; \
                  make"
RUN sudo cp /util-linux/nsenter /bin

ADD wrap_command.sh /tmp/wrap_command.sh

RUN bash /tmp/wrap_command.sh /bin mount 4755
RUN bash /tmp/wrap_command.sh /bin umount 4755
RUN bash /tmp/wrap_command.sh /bin lsblk 755
RUN bash /tmp/wrap_command.sh /sbin losetup 755
RUN bash /tmp/wrap_command.sh /sbin mkfs 755
RUN bash /tmp/wrap_command.sh /sbin blkid 755

# this is for the VNX driver
RUN mkdir -p /flocker-vnx-driver
RUN apt-get install -y sg3-utils wget python2.7 python-setuptools
RUN apt-get install -y scsitools
RUN wget https://github.com/emc-openstack/naviseccli/raw/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
RUN dpkg -i navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
ENV PATH /opt/Navisphere/bin:$PATH
RUN git clone https://github.com/ClusterHQ/flocker-vnx-driver.git /flocker-vnx-driver
ENV VNX_CONFIG_FILE /flocker-vnx-driver/config.yml
ENV PYTHONPATH /opt/flocker/lib/python2.7/site-packages:$PYTHONPATH

# Prereq packages for testing VNX
RUN apt-get install -y python-twisted
RUN sudo apt-get install -y python-yaml
RUN sudo apt-get install -y python-pip
RUN sudo pip install bitmath

WORKDIR /flocker-vnx-driver
