"""ProductInfo generator."""
from __future__ import annotations

from fews_agent.schema import ProductInfo

from .base import render


def generate(model: ProductInfo) -> str:
    return render("region/product_info.xml.j2", model)
