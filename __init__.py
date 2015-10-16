# Copyright 2015 EMC Corporation

from flocker.node import BackendDescription, DeployerType
from .vnx import vnx_from_configuration


def api_factory(cluster_id, **kwargs):

    return vnx_from_configuration(cluster_id, kwargs[u"USER"],
                                  kwargs[u"PASSWORD"], kwargs[u"IP"],
                                  kwargs[u"STORAGE_POOL"])

FLOCKER_BACKEND = BackendDescription(
    name=u"emc_vnx_flocker_plugin",
    needs_reactor=False, needs_cluster_id=True,
    api_factory=api_factory, deployer_type=DeployerType.block)
