# Adaptiv parallellism för existential-läget

Type: task
Status: open
Blocked by: 19

## Question

Kan begränsad, adaptiv parallellism minska antalet in-flight-anrop efter att en
blockerande konflikt hittats, utan att svarstiden till första konflikt blir
oacceptabel?

Bakgrund: existential-läget undvek 119 Jev-anrop men 34 anrop var redan påbörjade
när konflikten hittades.

- Jämför nuvarande fast concurrency med ett litet prioriterat fönster som bara
  fylls på medan stoppvillkoret inte är uppfyllt.
- Mät: tid till första verifierade konflikt, antal in-flight-anrop vid stopp,
  faktiskt undvikna anrop, väggtid, false-sufficient och ogiltiga stopp.
- Behåll D-konfigurationen, facit v2 och produktionsbeteendet oförändrat.
- SSR/ankare ska inte blandas in i detta experiment.

Ingen produktionsändring.
