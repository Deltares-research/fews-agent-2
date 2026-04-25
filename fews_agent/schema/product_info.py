"""ProductInfo.xml — per-product metadata (user, confidence,
classification, comment). Root element: ``<productInfo>``.

Note: different from ``fews_agent.schema.forecast_product_info_display``
(the forecast-product-info-display panel config) and from the
region-chapter ``Products.xml`` (which we already cover via
``GenericXmlFile``).
"""
from __future__ import annotations

from typing import Literal

from .common import FewsModel


class ProductInfo(FewsModel):
    """Root of ProductInfo.xml."""

    user: str
    confidence: Literal["High", "Medium", "Low"]
    classification: Literal["Confidential", "Restricted", "Internal", "Public"]
    commentText: str
