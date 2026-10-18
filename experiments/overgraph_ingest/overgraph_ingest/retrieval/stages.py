"""Measurable pipeline stages. Search intelligence is not one retriever."""

PIPELINE_STAGES = (
    "question",
    "representation",
    "retrieval",
    "classify",
    "coverage",
)
EVIDENCE_LAYERS = (
    "retrieval",
    "proof_evaluation",
    "navigation",
)
