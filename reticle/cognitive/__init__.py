from reticle.cognitive.llm_client import LLMClient, StepMetric, MODEL_PRICING
from reticle.cognitive.capability_ledger import CapabilityLedger
from reticle.cognitive.autotelic_drive import AutotelicDriveEngine
from reticle.cognitive.falsification import (
    DeadEnd,
    DeadEndLedger,
    RunReport,
    code_fingerprint,
    parse_approach,
    parse_unittest_output,
)

# The legacy harness still lives in root-level checkout modules, so load it only on
# use; the package's own modules must stay importable from an installed wheel.
_LEGACY_HARNESS_NAMES = {
    "BlankSlateHarness",
    "EpistemicNoteBoard",
    "DynamicToolRegistry",
    "FalsificationLedger",
    "GroundingLedger",
}


def __getattr__(name):
    if name in _LEGACY_HARNESS_NAMES:
        from reticle.cognitive import stateless_harness

        return getattr(stateless_harness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LLMClient",
    "StepMetric",
    "MODEL_PRICING",
    "CapabilityLedger",
    "AutotelicDriveEngine",
    "DeadEnd",
    "DeadEndLedger",
    "RunReport",
    "code_fingerprint",
    "parse_approach",
    "parse_unittest_output",
    "BlankSlateHarness",
    "EpistemicNoteBoard",
    "DynamicToolRegistry",
    "FalsificationLedger",
    "GroundingLedger",
]

