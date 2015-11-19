# Copyright ClusterHQ Inc.  See LICENSE file for details.
# Utility for creating naviseccli cached credentials and for interacting with
# the VNX array.

FROM ubuntu:14.04
MAINTAINER ClusterHQ <contact@clusterhq.com>
ADD https://github.com/emc-openstack/naviseccli/raw/master/navicli-linux-64-x86-en-us_7.33.2.0.51-1_all.deb /tmp/naviseccli.deb
RUN dpkg -i /tmp/naviseccli.deb
ENTRYPOINT ["/opt/Navisphere/bin/naviseccli", "-h", "192.168.40.13", "-secfilepath", "/keys"]
