# Facit-QA v2b: låg lexikal relation som granskningssignal

Type: task
Status: resolved
Blocked by: 31

## Answer

Implementerad i commit `e53b4e79`. `validate_facit(policy="v2b")` bevarar
v2-reglerna och v2-historiken, men ett giltigt sufficient-fall med låg lexikal
relation och verifierad provenance + stödjande/kompatibel relation får
`independent_review_required` som varning i stället för automatisk ogiltighet.
Utan provenance är fallet fortfarande ogiltigt. Artefakt: `facit-qa-v2b.json`.
Tester: 6 facit-QA-tester gröna.
