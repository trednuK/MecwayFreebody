# MecwayFreebody: stand van zaken

Laatst bijgewerkt: 10 november 2026. **V2026.1** (eerste release) uitgebracht op 10 november 2026 (`build` samengevoegd naar `main` en getagd).

## Versie en vereisten

- Versie: `VERSION` in `Scripts/fb_core.py` (schema `V<jaar>.<n>`, zoals MecwayAsterBridge, MecwayAdvancedBeamAnalysis en
  MecwaySectionProps; elk begon bij V2026.1). Het paneel toont hem in de kop en in de gekopieerde tabel; wijzigingen in `CHANGELOG.md`.
- Bridge: MecwayAsterBridge V2026.9 of nieuwer (`keep_base` en manifest schema 2). V2026.9 is uitgebracht op 10 november 2026,
  vóór MecwayFreebody V2026.1. V2026.8 en ouder hebben geen `keep_base`: de tool vindt dan geen run.
- Mecway 35, Code-Aster 17.4 met de starter op `...\<versie>\bin\run_aster.bat` (de versie komt uit dat pad).

## Klaar

- Bridge bewaart de base met manifest (`keep_base`, schema 1 en 2); vervolgrun, rekenkern en paneel (tekening, sleepbaar punt, tabel,
  CSV, pijlen in Mecway).
- Volumes, schalen, balken en gemengde sneden (fase 4); snede via knopen op een vlak, met kant en deeldoorsnede.
- Evenwichtscontrole met plek; oplegging op de snede zelf gemeld.
- Tabblad *Documentatie* met handleiding (NL en EN, genummerde afbeeldingen van het paneel) en README. **De gebruiker heeft in Mecway
  bevestigd dat de afbeeldingen in het tabblad Documentatie goed verschijnen.**
- Testvensters buiten beeld met `WS_EX_NOACTIVATE` en een focusval (WH_CBT-hook); bronregel: een focusaanroep in `Scripts/` alleen op
  een regel met `# focus:` en een reden.
- Alle Fable-reviews van fase 1 tot en met de knopensnede en het paneel zijn verwerkt.

### Laatste codecontrole (9 november), verwerkt

Elk punt eerst nagetrokken, dan een test die faalde, dan de herstelling; plan en wijziging door Fable en Opus gereviewd.

1. Schaal zonder dikte of balk zonder A: `area` is dan None (contract); de tabel gaf een TypeError en het hele resultaat ging verloren.
   Nu staat A als –, de getallen blijven, en `thickness_missing`/`section_missing` hebben een eigen tekst.
2. Balkdoorsnede in de tekening: de kern geeft de waarden (A, IY, ...), geen cara/vale; nu komt de omtrek uit het manifest in plaats
   van een cirkel.
3. De evenwichtsregel noemt nu het referentiepunt: het moment van de rest is om de oorsprong (0; 0; 0).
4. Melding van een mislukte run: de staart van de `.mess` werd overschreven door de console; nu wint de `.mess`.
5. `check_solution`: meer dan 2000 snedeknopen werden alleen steekproefsgewijs op aanwezigheid gecontroleerd; een ontbrekende knoop
   gaf een IndexError bij het schrijven. Nu wordt elke knoop op aanwezigheid gecontroleerd (posities nog steekproef). Concreet geval:
   een oplossing in Mecway met minder knopen dan het model. Of Mecway een oplossing na een meshwijziging laat staan, is niet nagegaan.
6. `assign_nodes` na de knopensnede: niet bereikbaar (elk snedevlak hoort bij een laagelement, dus de middenknopen van zijn ribben
   blijven). Bewaakt door `test_hex8_line_quad_keeps_the_midsides_of_the_cut` en de nieuwe `test_hex8_line_quad_without_a_kept_edge`.
7. README: de knopensnede loopt door volumes; schalen en balken elders in het vrije lichaam tellen mee.
8. Een starter zonder `<versie>\bin` gaf "andere Code-Aster-versie" en gaf de run de schuld. Nu eigen meldingen `launcher_version`
   (pad van de starter, met het pad) en `run_version` (manifest met `aster_version` null); `version` alleen bij een echt verschil, met
   de versie van de run ook als `start()` weigert. Zijn beide onbekend, dan eerst `launcher_version` (die weigert elke run). De versie
   uit het pad volgt nu de bridge: alleen een getal met een punt.
9. Tolerantie van de evenwichtscontrole (kleinste resultante van de sneden): bewuste keuze, nu ook in de handleiding uitgelegd.
- De afbeeldingen van het paneel (`docs/images/window_*`) zijn opnieuw gemaakt met `tools/fb_figures.py`: versie in de kop en de
  nieuwe evenwichtsregel. Een getaperde balk (HY1/HY2) wordt nog als cirkel van oppervlak A getekend.
- Overgenomen bridge-regels (`model_stem`, map naast het model, `mesh_fingerprint`, versie uit het starterpad, instellingen in
  `bridge_utils.py`) worden in `tests/test_aster.py` vergeleken met `develop` van de bridge, via `git show`; zonder bridge overgeslagen.

## Bekende grenzen

- Geen waarschuwing voor een knooplast op een snedeknoop: hij telt aan de selectiezijde (staat in de documentatie).
- Met `elem_beam` = POU_D_TG in de bridge-instellingen weigert de tool elke balk (`beam_warping`).
- Het moment om de schaalnormaal is onbetrouwbaar (boorstijfheid); gemarkeerd.
- Snede via knopen: de geselecteerde knopen moeten op volume-elementen liggen, zonder schaal of balk erop.
- Pijlen in Mecway volgen een andere stap pas na opnieuw *Schrijf pijlen*. Een resultantepijl op een binnenknoop zit vaak in het volume;
  het paneel zegt dat (niet bij delen met eigen knopen op een raakvlak).
- `beam_axes_missing`, `relation_on_cut` en `not_shared` verschijnen als code, niet in woorden.
- Staan in één map een run zonder versie en een oudere goede run van hetzelfde model, dan kiest het paneel de nieuwste en meldt
  `run_version` (sortering op `run_id` in `scan_runs`). Of de oudere run dan in het paneel te kiezen is, is niet nagegaan.
- Resultaten van Mecway's eigen solver en van CalculiX worden niet ondersteund; modaal, knik, harmonisch, HOMARD en XFEM worden geweigerd.

## Niet in de keten met Code-Aster getest

- Niet-lineaire schalen en balken, tie en RBE3 met schalen en balken, orthotrope schalen, kabels.
- Het paneel met een echte vervolgrun op een snede via knopen (de kern wel: `tests/test_nodecut_e2e.py`), een snede via knopen met
  schalen in het vrije lichaam (unit-test: hetzelfde plan als de elementselectie), `noderotation` op een schaal.
- Een gemengd hex8/hex20-model waarin de bridge alleen het hex8-deel kwadratisch maakt (LINE_QUAD) terwijl elk snedevlak op hex20 ligt:
  dan zou `assign_nodes` onterecht `node_mismatch` geven. Of de bridge zo'n model zo rekent, is niet nagegaan.
- `run_version` via de route van Mecway zelf: daar geeft de bridge eerst de versie uit de `.mess` door, dus null komt alleen bij een
  `.mess` zonder versiekop én een starter zonder `<versie>\bin`. In de keten getest is de terugval van `finish_run` op het starterpad
  (zie *Testen*); de melding in het paneel (`run_problem`, die `no_aster` eerst noemt) alleen als unit-test.
- Pijlen op een door de bridge teruggeschreven oplossing binnen `real_run` (vraagt `FB_BRIDGE`): niet gedraaid, de werkmap van de
  bridge was in gebruik.
- De automatische ketentests voor schalen, balken en de volumevormen (`test_aster_shells_e2e`, `test_solids_e2e`): hun bases
  ontbreken (`WorkDir/shells`, `WorkDir/solids`), dus die sloegen op 9 november over.

## Niet automatisch getest (handmatig in Mecway)

- Schalen en volumes: op 10 november door de gebruiker in Mecway getest, in orde.
- Het echte browserelement (`WebBrowser`) van het tabblad *Documentatie* met de focusval; de klik op een tabblad. De afbeeldingen zelf
  zijn door de gebruiker bevestigd.
- Grote DPI-letters; CSV in Excel; de grijze tabel na een andere selectie; een andere stap in een oplopend model (`c_ramp`).
- Pijlen: in de handmatige test van 9 november werkten ze bij een elementselectie. Bij een snede via knopen met *Resultante* zag de
  gebruiker geen pijl; gemeten staat die wel in Mecway, op de middelste snedeknoop binnen het volume. Het paneel meldt dat nu
  (`a_inside`). Of de pijl op een buitenknoop zichtbaar is, is nog niet door de gebruiker bekeken.
- Een activering door Windows na het sluiten van een ander venster (bewust niet nagebootst).

## Testen

- `python -B tests/test_gui_all.py` (alle paneeldelen, verborgen Mecway, focusval; `real_run` alleen met FB_E2E),
  `tests/test_core.py`, `tests/test_aster.py`, `tests/test_nodecut.py`; dezelfde drie ook in Mecway's IronPython 2.7.9 zonder Mecway
  (via `tools/run_ipy.ps1`, de bridgevergelijking slaat daar over). `FB_RUN_MECWAY=1 python -m unittest tests.test_core_ipy` (echte
  vervolgrun in een verborgen Mecway) vraagt de bases `c_lin` en `c_nl` in `WorkDir/e2e`. Ketentests met Code-Aster: zie de README.
- Uitslag 9 november (na de codecontrole): alle genoemde suites groen. Later die avond met `FB_E2E` = `WorkDir/e2e`: `trap` en
  `real_run` groen (24 checks, vervolgrun 2,7 s; paneel buiten beeld, voorgrond nooit van ons).
- Ketentests 9 november (later), bridge `develop` op `343eb61`, Code-Aster 17.4 zonder venster: de bases opnieuw gemaakt in
  `WorkDir/e2e` (schema 2): `c_lin`, `c_nl`, `c_lq` met `e9_chain.py lin nl lq` (28 s), `c_other` en `c_nover` met
  `tests/test_aster_e2e.py build c_other c_nover` (15 s); 140-180 MB per base, samen 0,76 GB. Geen nieuwe zichtbare vensters of
  consoles tijdens bouwen en testen.
  - `tests.test_aster_e2e`: 30 tests groen (60 s). Grootste fout tegen de statica: lineair eF 8,0e-12; `c_nl` stap 1 eF 1,4e-6
    (grens 1e-5, de convergentie), laatste stap 6,7e-13.
  - Versieweigeringen in de keten (nieuw: `VersionsOfTheLauncher`, `VersionsOfTheRun`): `c_nover` is het model van `c_lin`, door de
    bridge gerekend met een eigen starter `...\aster\bin\run_aster.bat` die de echte aanroept; de bridge schreef `aster_version: null`
    (de `.mess` van die run noemt wel 17.4). Dan `run_version`; met de starter zonder versie `launcher_version` (ook bij beide
    onbekend, ook vóór `no_aster` en `no_cut`), met het pad als detail; `version` bij 17.2 in het manifest (detail 17.2) en bij een
    starter `...\17.2\bin` (detail 17.4). De base blijft ongewijzigd; met de versie erbij rekent dezelfde base goed (eF 8,0e-12).
  - `FB_RUN_MECWAY=1 tests.test_core_ipy`: groen; verborgen Mecway 35 (eigen proces, 22 s), geen consolevenster; de sommen uit
    IronPython gelijk aan CPython, ook in mappen met Latijnse en Griekse tekens.
  - `test_core`, `test_aster`, `test_nodecut`, `test_nodecut_e2e`, `test_aster_shells_e2e` en `test_solids_e2e` samen: 384 tests
    groen, 68 overgeslagen (de laatste twee, zonder bases).
- `find_case` zoekt na `WorkDir/e2e` ook in `WorkDir/exp9b` (oude bases van schema 1 van `c_lq` en `c_nl`): zonder `WorkDir/e2e`
  draaien die tests stil op die oude bases.

## Besluiten van de gebruiker

- 10 november 2026: release goedgekeurd. Volgorde van uitbrengen: MecwaySectionProps, MecwayAsterBridge V2026.9,
  MecwayAdvancedBeamAnalysis, MecwayFreebody V2026.1 (samenvoegen naar `main` en tag).

## Op te ruimen, na akkoord

- `WorkDir/exp*` (9 GB of meer, met de oude bases in `WorkDir/exp9b`) en `WorkDir/proef` (de handmatige test is gedaan).
- Lokale werkmappen en hulpbranches van het bouwen; hun inhoud zit in `build`.
