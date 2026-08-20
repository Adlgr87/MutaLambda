"""Diagnostics helpers: tipping detection and evolution reports."""

from __future__ import annotations

from mutalambda.muta_ext.diagnostics.tipping import TippingEvent, detect_tipping, mad
from mutalambda.muta_ext.diagnostics.evolution_report import EvolutionReport

__all__ = [
    "TippingEvent",
    "detect_tipping",
    "mad",
    "EvolutionReport",
]
