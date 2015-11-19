# Copyright ClusterHQ Inc.  See LICENSE file for details.
# Utility for testing VNX driver from inside a container

FROM ubuntu:14.04
MAINTAINER Madhuri Yechuri <madhuri.yechuri@clusterhq.com>

RUN sudo apt-get update
RUN sudo apt-get -y install apt-transport-https software-properties-common
RUN sudo apt-get -y --force-yes install \
      python-pip \
      git \
      python-dev \
      libffi-dev \
      libssl-dev
      sg3-utils \
      scsitools \
      lsscsi \

RUN wget https://github.com/emc-openstack/naviseccli/raw/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
RUN dpkg -i navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb

RUN pip install git+https://github.com/ClusterHQ/flocker.git@1.7.2

RUN git clone https://github.com/ClusterHQ/flocker-vnx-driver.git /flocker-vnx-driver
ENV VNX_CONFIG_FILE /flocker-vnx-driver/config.yml
ENTRYPOINT ["/usr/local/bin/trial"]
CMD ["flocker_emc_vnx_driver"]
