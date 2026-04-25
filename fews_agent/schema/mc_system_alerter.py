"""McSystemAlerter.xml — task properties for the MC System Alerter task.

Defines email / alarm-module / Azure Service Bus / AWS SNS alerts. The
top-level structure is shallow (root → ``<alerts>`` → 4 alert kinds).
Each alert has its own deep tree (recipients, attachments, configuration,
substitutions). Per project convention, deep alert subtrees pass through
as ``dict[str, Any]`` to the dict_to_xml renderer; the typed surface
covers the root and the ``<alerts>`` wrapper.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .common import FewsModel


class Alerts(FewsModel):
    """``<alerts>`` — container for the four alert kinds.

    Each kind is a list of single-key dicts rendered by dict_to_xml.
    Order across kinds is preserved by XSD (emailalert → alarmModuleAlert
    → azureServiceBusAlert → awsSimpleNotificationServiceAlert).
    """

    emailalert: list[dict[str, Any]] = Field(default_factory=list)
    alarmModuleAlert: list[dict[str, Any]] = Field(default_factory=list)
    azureServiceBusAlert: list[dict[str, Any]] = Field(default_factory=list)
    awsSimpleNotificationServiceAlert: list[dict[str, Any]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> Alerts:
        # XSD allows zero alerts (all four are minOccurs="0"), but a
        # zero-alert McSystemAlerter is meaningless; we don't enforce it.
        return self


class McSystemAlerter(FewsModel):
    """Root of McSystemAlerter.xml (``<mc-system-alerter>``)."""

    alerts: Alerts
