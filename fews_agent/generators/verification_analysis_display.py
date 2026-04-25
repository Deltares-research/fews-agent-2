"""VerificationAnalysisDisplay generator."""
from __future__ import annotations

from fews_agent.schema import VerificationAnalysisDisplay

from .base import render


def generate(model: VerificationAnalysisDisplay) -> str:
    return render("display/verification_analysis_display.xml.j2", model)
