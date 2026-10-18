# Tabular Review holdout gold

Gold before models. Default stays D (hybrid k=5).
E (dense k=5) is the next candidate, not the new default.
No Cerebras. No Qwen. No new prompt. No special rules.
A cell may list several structured answers.

## Selection

Twenty documents from the 66 leftovers that are neither the
diagnostic twenty nor the status-v2 cases. Every third leftover
by Avtal number, stride 3.

| Document |
|---|
| Avtal_15_Bonusavtal.docx |
| Avtal_24_Kopeavtal_fastighet.docx |
| Avtal_28_Aktieagaravtal.docx |
| Avtal_33_Agentavtal.docx |
| Avtal_40_Laneavtal_revers.docx |
| Avtal_43_Leasingavtal_utrustning.docx |
| Avtal_48_Mjukvaruutvecklingsavtal.docx |
| Avtal_51_Anvandarvillkor_webbplats_app.docx |
| Avtal_55_Overlatelse_domannamn.docx |
| Avtal_58_IT_policy_BYOD.docx |
| Avtal_61_PUB_avtal_DevBrains_ansvarig.docx |
| Avtal_64_Byraavtal_reklam.docx |
| Avtal_67_Evenemangsavtal.docx |
| Avtal_71_Konstnarsavtal.docx |
| Avtal_74_Forsakringsavtal.docx |
| Avtal_78_Uppdragsavtal_juridiskt_ombud.docx |
| Avtal_81_VD_anstallningsavtal.docx |
| Avtal_84_Villkorat_aktieagartillskott.docx |
| Avtal_87_Investeringsavtal.docx |
| Avtal_90_Anslutningsavtal.docx |

Addressed cells: 43/100. Silent: 57.

## What each question means

### auto-renewal

Asked: Förlängs avtalet automatiskt?

Whether the agreement continues or starts a new period without the parties signing a new agreement.

### notice-period

Asked: Vilken uppsägningstid gäller enligt avtalet?

Which notice period or periods apply, and to what.

### liability-cap

Asked: Finns det en begränsning av parternas skadeståndsansvar?

Whether the parties' damages liability is limited, how, and with what exceptions.

### confidentiality

Asked: Finns det en sekretessplikt i avtalet?

Whether this agreement creates a duty to keep information secret, who, and for how long.

### liability-secrecy-carveout

Asked: Undantas brott mot sekretess från ansvarsbegränsningen?

Whether a liability limitation excludes a secrecy breach, and which provision says so.

## What this is not

- Not a run of D, E, or K.
- Not a default change.
- Not more work on the diagnostic twenty.
