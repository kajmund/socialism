# Slutgranskning: beslutscomplete plan för A1–B

Type: grilling
Status: open
Blocked by: 03, 04, 05, 06, 07, 08, 09, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45

## Question

Är planen beslutscomplete och kan implementationen börja utan ytterligare
designbeslut?

Granska och sy ihop:

- Per arm: låst kontrakt, reuse-vs-new-matris, ansvar och avgränsning.
- Frysta golden cases, labels och acceptanskriterier per arm.
- Täcknings- och mätprotokoll med artefaktformat.
- Att varje arms förbättring är isolerad: A1 får inte tillskrivas A2:s fix, A2
  inte A3:s, A3 inte B:s.
- Att B endast mäts efter att A1–A3 kan mätas separat.
- Att A1:s confidence-diagnostik redovisar alla fem NOUL-svar, så att
  `follow_up_change`/`additional_source`:s indirekta påverkan syns.
- Att ingen komponent ensam deklarera fullständighet.
- Scope-gränser: ingen produktionskoppling, ingen ny motor/graf, inget merge.
- Kvarvarande "Not yet specified"-punkter: lös dem eller flytta dem till
  Out of scope med skäl.

Leverans: `.scratch/evidence-sufficiency-v2/plan.md` — den beslutscompleta
handoff-planen, med länkar till respektive tickets svar. Kartan stängs när
planen är godkänd.
