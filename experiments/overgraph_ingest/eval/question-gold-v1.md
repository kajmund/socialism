# User questions versus gold

Gold, user questions, and P0 are unchanged.
This is not a retune of gold after model answers.
Historical 78% cell accuracy is agreement with passage gold,
not user-question quality.

## Three wordings, three tasks

Jev sees the user question. Gold was written for retrieval
inventory and classify. Tabular scores cells against passage gold.

| Fråga | Användarfråga (Jev) | Gold-query | Classify | Gold+ i urvalet |
|---|---|---|---|---:|
| auto-renewal | Förlängs avtalet automatiskt? | Vilka avtal innehåller bestämmelser om automatisk förlängning? | Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett nytt uttryckligt godkännande från båda parterna? | 5 |
| notice-period | Vilken uppsägningstid gäller enligt avtalet? | Vilka avtal innehåller en uppsägningstid? | Innehåller texten en stående uppsägningstid för att avsluta avtalet? | 6 |
| liability-cap | Finns det en begränsning av parternas skadeståndsansvar? | Vilka avtal begränsar ansvaret för skada? | Innehåller texten en avtalsenlig ansvarsbegränsning, till exempel ett takbelopp eller ett undantag för indirekt skada? | 5 |
| confidentiality | Finns det en sekretessplikt i avtalet? | Vilka avtal innehåller en sekretessplikt? | Innehåller texten en skyldighet att hålla information hemlig eller att inte röja konfidentiella uppgifter? | 8 |
| liability-secrecy-carveout | Undantas brott mot sekretess från ansvarsbegränsningen? | Vilka avtal undantar brott mot sekretess från ansvarsbegränsningen? | Innehåller texten att ansvarsbegränsningen inte gäller vid brott mot sekretess? | 3 |

Liability-cap gold includes a monetary cap *or* an exclusion of
indirect loss. The user question only asks whether liability is
limited. Vite, settlement, insurance, and statutory allocation
are left to the notes.

Auto-renewal notes exclude `tills vidare`, but Avtal 18 gold is
`Avtal_18_Hyresavtal_bostad.docx: Annars förlängs avtalet tills vidare.`.

## P1 false ANSWERED are mostly gold-negative

Of 17 false `ANSWERED` on the probability run:

- Gold-negative (model answered, gold has no unit): 14
- Gold-positive, wrong citation: 3

| Kind | n |
|---|---:|
| gold_omission | 2 |
| gold_narrower | 7 |
| nearby_relation | 7 |
| product_polarity | 1 |

## What this is not

- Not a reason to change gold so the model scores higher.
- Not a reason to connect D's named exclusions.
- Not a new prompt, controller, or score threshold.

Carve-out is the best-aligned question: user, classify, and
gold notes ask for the same relation. It was also the only
question with zero false `ANSWERED` on P1.

The user question is the contract for Socialism Tabular Review.
