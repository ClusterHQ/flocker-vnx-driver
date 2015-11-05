# Utility for testing VNX driver from inside a container
FROM ubuntu:14.04
MAINTAINER Madhuri Yechuri <madhuri.yechuri@clusterhq.com>

RUN sudo apt-get update
RUN sudo apt-get -y install apt-transport-https software-properties-common
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
      libtool \
      wget \
      sg3-utils \
      python2.7 \
      python-setuptools \
      python-pip \
      scsitools \
      lsscsi \
      python-dev \
      libffi-dev \
      libssl-dev

RUN wget https://github.com/emc-openstack/naviseccli/raw/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
RUN dpkg -i navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb
ENV PATH /opt/Navisphere/bin:$PATH
RUN mkdir -p /flocker-vnx-driver

# Install Flocker
RUN git clone https://github.com/ClusterHQ/flocker.git /flocker
WORKDIR /flocker
RUN git checkout 1.2.0
WORKDIR /
RUN pip install /flocker
RUN git clone https://github.com/ClusterHQ/flocker-vnx-driver.git /flocker-vnx-driver

ENV VNX_CONFIG_FILE /flocker-vnx-driver/config.yml
ENV PYTHONPATH /opt/flocker/lib/python2.7/site-packages:$PYTHONPATH

WORKDIR /flocker-vnx-driver
