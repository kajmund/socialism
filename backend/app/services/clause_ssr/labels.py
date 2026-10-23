"""Isolated OverGraph labels for the clause SSR library.

Kept out of ``app.services.overgraph.labels.KNOWLEDGE_TYPES`` so knowledge
search and research write-back do not treat these nodes as facts.
Edge names follow the ``legal.*`` convention rather than inventing global
``DERIVED_FROM`` / ``MEMBER_OF`` labels.
"""

CLASSIFICATION = "SsrClassification"
VERIFICATION = "SsrVerification"
VERIFICATION_REVISION = "SsrVerificationRevision"
ANCHOR = "SsrClauseAnchor"
ANCHOR_SET = "SsrClauseAnchorSet"
REVIEW_SESSION = "SsrReviewSession"

ABOUT = "ssr.ABOUT"
ANSWERS = "ssr.ANSWERS"
DERIVED_FROM = "ssr.DERIVED_FROM"
REPRESENTS = "ssr.REPRESENTS"
MEMBER_OF = "ssr.MEMBER_OF"
FOR = "ssr.FOR"
SUPERSEDES = "ssr.SUPERSEDES"
