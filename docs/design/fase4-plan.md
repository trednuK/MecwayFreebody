# Fase 4: schalen, balken en gemengde modellen

Status: plan, versie 3, na twee Fable-reviews. De regels staan uitgewerkt in het contract, sectie "Phase 4"; bij verschil geldt het contract. Basis: `docs/STAND.md`, het contract (`docs/design/contract.md`) en de metingen E7
in `docs/research/00_onderzoeksverslag.md` §5.

## Doel

Een selectie mag schaal- en balkelementen bevatten, ook gemengd met volume-elementen. Per snede komen N, V, T en M met de juiste
assen en het juiste punt, of een duidelijke weigering. Hoofddoel blijft Code-Aster via de bridge.

## Wat al gemeten is (E7, Code-Aster-runs in bridge-stijl, statica op twee sneden)

- DKT vlak en gedraaid, met druk en met `EXCENTREMENT`: tot 3e-10. COQUE_3D: tot 4e-10. POU_D_E en POU_D_T, recht en frame: 1e-11.
- Niet-lineair DKT en COQUE_3D (GROT_GDEP): tot 2e-8.
- `REAC_NODA` bevat DRX, DRY en DRZ; de vervolgrun leest ze al.
- **Fout door boorstijfheid:** de fictieve boorstijfheid van schalen werkt als een veer naar de grond op elke schaalknoop. Het moment
  dat daarin verdwijnt, staat niet in `REAC_NODA` van de snedeknopen. Gemeten: geknikte en gebogen schalen tot 4e-2 (afhankelijk
  van `COEF_RIGI_DRZ`), en ook een **vlakke** plaat met een knoopmoment om de normaal: 3e-2 (`b_dkt_q4_drill`, `b_c3d_q8_drill`).
  DKT en COQUE_3D allebei.

## Wat niet in fase 4 komt, en wordt geweigerd

| Geval | Waarom |
|---|---|
| POU_D_TG (welving) | `REAC_NODA` per knoop is fout bij deze balk (bridge KNOWN_BUGS 123). De vervolgrun zou het fout herberekenen. Weigeren tot gemeten |
| POU_D_T_GD of andere balken met grote rotaties | de assen draaien mee; de onvervormde assen zijn fout |
| (geen weigering) schaalstrook of balk die met grote verplaatsingen rekende | globale assen en een waarschuwing: lokale assen draaien mee |
| `offset_links` (COQUE_3D- of balk-offset met verschoven knopen) | de snede loopt via knopen die de selectie niet deelt |
| voorspanning, flexibele verbindingen, discrete veren | niet gemeten |
| een schema 1-manifest bij een selectie met schalen of balken | melding "bridge te oud" |

## Ontwerp

### 1. Snede per elementsoort (contract eerst bijwerken)

De krachten blijven knoopgebaseerd: snedeknopen zijn de knopen die de selectie deelt met de rest. Meetkunde en groepering per soort:

| Soort | Snede-entiteit | Buurregel |
|---|---|---|
| Volume | vlak | buur buiten de selectie is een volume-element (zoals nu) |
| Schaal | ribbe | buur buiten de selectie is een **schaal**element over dezelfde ribbe. Een schaal waarvan alle knopen op een buitenliggend volumevlak liggen (huidschaal), is een grensvlak: waarschuwen, geen snede-entiteit |
| Balk | eindknoop | de knoop hoort ook bij een element buiten de selectie. Een balk met beide knopen op de snede (langs de snede) telt mee, met een waarschuwing |

- Entiteiten die knopen delen, vormen één snede. Een balk die eindigt op een knoop van een schaalribbe of volumevlak maakt de snede
  gemengd: globale assen.
- Line3-balken die de bridge splitst (`M<eid>`, `H<eid>`): per cel. Quad8- en tri6-middenknopen op een snederibbe zijn snedeknopen;
  de strooklengte wordt kwadratisch geïntegreerd. De middenknoop van COQUE_3D (QUAD9, TRIA7) wordt nooit gedeeld.

**Tekens.**

- Balk: N positief bij trek, langs de uitwaartse normaal van de selectie. Is de snede bij knoop 2 van het element, dan is dat de
  lokale +x; bij knoop 1 is het -x, en dan worden x en z gespiegeld en blijft y gelijk aan de lokale y van Code-Aster.
- Schaalstrook: normaal n in het vlak van de schaal, loodrecht op de ribbe, uit het geselecteerde element; t langs de ribbe;
  w de schaalnormaal. Componenten: N langs n, V_t, V_w, T om n, M_t om t (betrouwbaar), M_w om w (onbetrouwbaar, zie §3).

### 2. Meetkunde, neutraal punt en assen

- **Vlak van de snede.** Stroken: het vlak door de ribben, opgespannen door ribberichting en schaalnormaal. Liggen alle stroken in één
  vlak (bijvoorbeeld een I-profiel van schalen), dan is dat de doorsnede. Balk: het vlak loodrecht op de balkas.
- **Neutraal punt.** Met E gewogen zwaartepunt van vlakken (A), stroken (t x L, op de middenlijn; bij `EXCENTREMENT` verschoven over
  e langs de normaal) en balken (A in de knoop). Krachten blijven op de knoopposities.
- **Assen.**
  - volume, of een vlakke verzameling stroken: hoofdassen van de doorsnede; voor stroken met een eigen dunwandige integrator (t·L³/12
    om de ribbe meegenomen);
  - één losse strook: de lokale assen n, t, w;
  - één balk: de balkassen zoals Code-Aster ze gebruikte. Bij een L- of General-profiel zijn dat niet de hoofdassen; het paneel zegt het;
  - gemengd of niet-vlak: globaal, met een melding.
- **E.** Uit de materialen via Mecway's API. Ontbreekt E (orthotrope of composietschaal), dan de bestaande melding `E_missing` en een
  ongewogen zwaartepunt.
- **Tekening.** Stroken als dunne rechthoeken (t x L), balken met hun omtrek als die bekend is, anders een cirkel met A.

### 3. Boormoment van schalen

Er komt geen aandeel-criterium: het verloren moment zit niet in de snedeknopen (zie de meting hierboven). In plaats daarvan:

- **waarschuwen** zodra de selectie of haar directe omgeving schalen heeft die niet in één vlak liggen (knik, kromming), of zodra er een
  knoopmoment op schalen in de selectie aangrijpt; met de gemeten orde (E7) en de waarde van `COEF_RIGI_DRZ` uit het manifest;
- M_w van een losse strook staat altijd als onbetrouwbaar gemarkeerd;
- fouten en toleranties overal genormeerd als in E6/E7: max(|M|, |F|·L), zodat een component nabij nul geen schijnfout geeft.

### 4. Gegevens uit Mecway en uit de bridge

- **Doorsnede van balken:** uit het manifest (`cara`/`vale`), omdat Mecway voor de meeste profieltypen alleen de maten geeft.
- **Uit Mecway's API:** dikte per component (`mw.material(component)`, `material_property(m, "thickness" | "area" |
  "iyy" | "izz" | ...)`), en E. Dikte hoort bij het materiaal, dus per component.
- **Uit het manifest (schema 2), alleen wat Code-Aster gebruikte en Mecway niet weet:**
  - `components`: per Mecway-component `model` (DKT, DST, COQUE_3D, POU_D_E, POU_D_T, POU_D_TG, POU_D_T_GD, BARRE, CABLE, 3D),
    `has_warping`, en per run `COEF_RIGI_DRZ`;
  - `beam_axes`: lokale x, y, z per balk**cel**, zoals de bridge ze aan Code-Aster gaf (`_mecway_v_axis` per halve cel bij line3);
  - `excentrement`: per element, want een offset hoort bij een selectie, niet bij een component;
  - `not_shared`: per soort ook de **knopen** die eraan vastzitten, en bij constraint equations of de bridge ze zelf maakte (line3-truss,
    flexibele verbinding) of de gebruiker.
  - Namen via `mecway_name`, zoals bij `deformation_by_component`.
- De bridge schrijft al `_beams.json` voor een andere tool. Dat contract blijft ongewijzigd; het manifest is de enige bron voor
  MecwayFreebody.

### 5. `not_shared` als waarschuwing

Pas na deze voorwaarden:

1. `rest` en `on_cut` tellen ook momenten, genormeerd met een lengte (nu alleen krachten: een koppeling die alleen een moment geeft,
   zou onzichtbaar blijven).
2. Raakt een verbinding uit `not_shared` een snedeknoop, dan weigeren (de knopen staan in het manifest).
3. Anders waarschuwen met wat `rest` laat zien.

### 6. Volgorde en verdeling

1. **Contract** bijwerken met §1 tot en met §5, en Fable laten reviewen. Daarna pas bouwen.
2. Tegelijk:
   - **A. Kern:** entiteiten, stroken, balkpunten, assen en tekens, dunwandige integrator, momenten in `rest`/`on_cut`, weigeringen.
   - **B. Bridge:** manifest schema 2, in een eigen werkkopie van de bridge-repo. `section-results` is geland; stem de bestanden
     opnieuw af met de bridge.
3. **C. Paneel** zodra A staat: assen per geval, teksten, tekening van stroken en balken, waarschuwingen.
4. **D. Ketentests** met de bridge-code en Code-Aster, zonder Mecway, zoals E9. Mecway zelf alleen voor de leeskant (API).

Elk deel wordt getest en door Fable gereviewd. Kleine modellen, tot circa 2000 elementen.

### 7. Testplan

Altijd statica met twee sneden. Negatieve controles staan erbij.

- Vlakke plaat DKT (quad4, tri3) en COQUE_3D (quad8, tri6), lineair en niet-lineair.
- Geknikte en gebogen plaat: getallen plus de waarschuwing. Vlakke plaat met knoopmoment: moet waarschuwen (negatief zonder waarschuwing).
- I-profiel van schalen, dwars gesneden: dunwandige hoofdassen tegen een handberekening.
- Balkframe POU_D_E en POU_D_T: snede bij knoop 1 en bij knoop 2 van een element (tekens), balk langs de snede, line3 gebogen, truss.
- Gemengd: blok met schaal eraan, en balk aan schaal; huidschaal op een blok; verschillende E.
- DKT met `EXCENTREMENT`.
- Weigeringen: POU_D_TG, POU_D_T_GD, `offset_links`, schema 1 met schalen.
- Model met tie of RBE3 buiten de snede: waarschuwing, getallen correct. Koppeling die alleen een moment op een binnenknoop zet: moet
  zichtbaar zijn in `rest`. Verbinding op een snedeknoop: weigering.
- Orthotrope schaal: `E_missing`.

## Buiten fase 4

Mecway's eigen solver en CalculiX (M4L), modale, knik- en harmonische resultaten, en elke release zonder expliciet ja van de gebruiker.
