from __future__ import annotations

from wait_local_agent.cloud_connectors.aws import AwsInventoryConnector
from wait_local_agent.cloud_connectors.azure import AzureInventoryConnector
from wait_local_agent.cloud_connectors.gcp import GCPInventoryConnector
from wait_local_agent.cloud_connectors.m365 import M365InventoryConnector

__all__ = [
    "AwsInventoryConnector",
    "AzureInventoryConnector",
    "GCPInventoryConnector",
    "M365InventoryConnector",
]
