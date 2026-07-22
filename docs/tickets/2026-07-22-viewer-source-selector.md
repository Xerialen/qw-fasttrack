# Viewer: källväljare i GUI:t i stället för unika URL:er

**Rapportör:** ägaren (Xerial)
**Datum:** 2026-07-22
**Kontext:** live-användning av movement-lab-viewern
**Prioritet:** medel (UX-friktion, ingen funktionsblockerare)

## Problem

För att växla mellan olika demouppspelningar och en livevy från
testservern måste man idag hålla reda på unika URL:er med
query-parametrar (`?graph=<namn>&live=<port>` — t.ex. `live=8095`,
`live=8096` för olika demon, `live=8093` för livebryggan). Det är inte
användarvänligt — källvalet ska göras inne i GUI:t, inte via
URL-mangling.

## Önskat beteende

En källväljare i viewerns panel (samma ställe som
grafversion-dropdownen) som listar:

1. Tillgängliga demouppspelningar (aktiva replay-servrar med
   demonamn).
2. Livebryggan, om aktiv.
3. "Ingen källa" (bara mesh).

Byte ska ske utan sidladdning, och grafversion ska följa källan
automatiskt (sha-guard) med tydlig mismatch-indikator och en-klicks-fix
— precis som designpromptens versionsmedvetenhetskrav.

## Teknisk not

Källorna är WS-servrar på lokala portar. En enkel discovery-endpoint i
overlay-sidecarn (18089), eller en portlista i en JSON som
replay/live-servrarna registrerar sig i, skulle räcka för enumerering.

## Referenser

- `C:\Users\benya\Downloads\movement-lab-frontend-designprompt.md`
  (designprompten till Claude Design — denna ticket ska in i det
  arbetet)
- `docs/design/2026-07-21-fasttrack-design.md` (qw-fasttrack)
