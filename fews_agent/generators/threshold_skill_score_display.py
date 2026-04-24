"""ThresholdSkillScoreDisplay generator."""
from __future__ import annotations

from fews_agent.schema import ThresholdSkillScoreDisplay

from .base import render


def generate(model: ThresholdSkillScoreDisplay) -> str:
    return render("display/threshold_skill_score_display.xml.j2", model)
