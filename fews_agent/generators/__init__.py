"""Generator registry.

`SPECS` is the authoritative list of FEWS file types this pipeline can
produce. Each spec binds an input-JSON key, a Pydantic model, a Jinja
template, the generator callable, and the output path relative to
`examples/generated-config-tutorial/`.

Adding a new file type = append a spec here.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.schema import Locations, Parameters, Qualifiers

from . import locations, parameters, qualifiers
from .base import GeneratorSpec

SPECS: list[GeneratorSpec] = [
    GeneratorSpec(
        name="locations",
        input_key="locations",
        model_class=Locations,
        template_name="locations.xml.j2",
        generate=locations.generate,
        output_relpath=Path("RegionConfigFiles/Locations.xml"),
    ),
    GeneratorSpec(
        name="parameters",
        input_key="parameters",
        model_class=Parameters,
        template_name="parameters.xml.j2",
        generate=parameters.generate,
        output_relpath=Path("RegionConfigFiles/Parameters.xml"),
    ),
    GeneratorSpec(
        name="qualifiers",
        input_key="qualifiers",
        model_class=Qualifiers,
        template_name="qualifiers.xml.j2",
        generate=qualifiers.generate,
        output_relpath=Path("RegionConfigFiles/Qualifiers.xml"),
    ),
]

__all__ = ["SPECS", "GeneratorSpec"]
