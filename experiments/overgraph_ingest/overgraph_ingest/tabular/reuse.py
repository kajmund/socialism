"""What Tabular Review reuses. Not Coverage v3 hop-always."""

REUSED = {
    "document_local_rank": "exhaustive_rank + rrf_fuse on units filtered by relative_path",
    "classify": "jev.classify_candidates, one TextUnit per prompt",
    "hops": "navigation.hop section_hops / child_clause_hops / referenced_clause_hops",
    "citations": "coverage.evidence.validate_span exact substring",
    "gold_map": "gold-map-v2 relevant unit keys",
}
NOT_REUSED = {
    "coverage_v3": "run_coverage_v3 / hop-always / EVIDENCE_FOUND",
    "resolve_status": "VERIFIED_ABSENT and yes-plus-hop completion",
    "controllers": "run_controller / run_budget_controller",
    "proof_engine": "assess_chain / admit_evidence_found / predicate",
    "second_opinion": "Jev plus GPT-OSS routing",
}
NEW = {
    "cell_contract": "ANSWERED / UNCERTAIN / NOT_FOUND plus source-grounded excerpt",
    "jev_decide": "choose ANSWER or a valid hop, never invent unit ids",
    "sync_runner": "one cell at a time, no parallel documents or questions",
}
