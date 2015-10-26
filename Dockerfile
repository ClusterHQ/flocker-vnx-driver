# Utility for testing VNX driver from inside a container
FROM clusterhq/flocker-dataset-agent:1.2.0-1rev1
MAINTAINER Madhuri Yechuri <madhuri.yechuri@clusterhq.com>

COPY config.yml.sfdata /opt/flocker/config.yml
ENV VNX_CONFIG_FILE /opt/flocker/config.yml

CMD ["/usr/bin/bash"]
