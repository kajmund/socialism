# Heading metadata to Jev rejected

PRESENT is not part of the simple Tabular answer path.
Text-only `answer_cell` stays. Default stays D.
Dense k=5 remains the strongest measured candidate.

Development TEXT 89.5% (85 correct positives) against PRESENT 88% (84). Silent false stayed 12. Changed cells 8/200. Lost positives 1.

Headings in embeddings left hit@5 at 81/84. Do not compare the development 89.5% with the separate Dense k=5 holdout 89%.

PRESENT did not reduce silent false answers and lost one previously correct positive. Headings in embeddings did not raise hit@5. Do not send more structure to Jev on this answer path. Do not start ingest labeling because the cheaper representations failed. Pause micro-optimization of the same five TextUnits.

Structure stays for navigation and citations.
It is not sent to Jev on this answer path.
Next quality needs a new capability, not another
variation of the same five TextUnits.
