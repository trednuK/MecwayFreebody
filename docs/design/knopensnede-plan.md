# Snede via een set knopen op een vlak

Status: plan, versie 2, na de Fable-review (verwerkt in de sectie "Regels na review"; bij verschil gelden die regels). Hoort bij het stappenplan in `docs/STAND.md`. De vaste regels van het contract (`docs/design/contract.md`)
gelden ook hier.

## Wens

De gebruiker selecteert in Mecway een set knopen die op een vlak liggen, bijvoorbeeld de knopen van een dwarsdoorsnede. MecwayFreebody
rekent de krachten en momenten door dat vlak uit, net als bij een selectie van elementen.

## Idee

Een set knopen op een vlak beschrijft een snede, maar nog niet welke kant het vrije lichaam is. Het script maakt van de knopen een
elementselectie, en daarna loopt alles zoals nu: dezelfde vervolgrun, dezelfde som, hetzelfde paneel.

1. **Vlak.** Kleinste-kwadratenvlak door de geselecteerde knopen. Liggen knopen verder dan een tolerantie (relatief tot de grootte
   van de set) van dat vlak, dan weigeren met `nodes_not_planar`: het script gokt niet welke knopen bedoeld zijn.
2. **Kant.** Standaard de kant waar de normaal heen wijst, met een knop "andere kant". De kant staat in beeld in de tekening en in de
   tabel; de resultanten van de twee kanten zijn tegengesteld, en het paneel zegt dat.
3. **Snede op elementgrenzen.** Een element met knopen strikt aan beide kanten van het vlak dat een geselecteerde knoop raakt, betekent dat
   het vlak door elementen loopt: weigeren met `plane_through_elements`. De snede moet langs elementvlakken lopen.
4. **Vrij lichaam.** Vanuit de elementen aan de gekozen kant die een geselecteerde knoop raken, groeit de selectie over gedeelde knopen,
   zonder over de geselecteerde knopen heen te gaan.
   - **Volledige doorsnede.** Blijft de gegroeide selectie aan haar kant, en zijn de knopen die ze met de rest deelt precies de
     geselecteerde knopen (plus middenknopen daartussen), dan is het een echte vrijsnede. Alles werkt als nu, ook de evenwichtscontrole
     `rest` en `on_cut`.
   - **Deeldoorsnede.** Lekt de groei naar de andere kant (de knopen sluiten het lichaam niet af, bijvoorbeeld alleen een flens), dan is
     het vrije lichaam de laag elementen aan de gekozen kant die een geselecteerde knoop raakt. De som loopt alleen over de geselecteerde
     knopen (en middenknopen van ribben tussen twee geselecteerde knopen). De evenwichtscontrole `rest` geldt dan niet, want de andere
     knopen van de laag dragen ook kracht; het paneel zegt dat duidelijk, met de melding `partial_section`.
5. **Middenknopen.** Bij kwadratische elementen of LINE_QUAD horen middenknopen op ribben tussen twee geselecteerde knopen bij de snede,
   ook als de gebruiker ze niet selecteerde. Middenknopen buiten de selectie horen er niet bij.
6. **Schalen en balken.** Bij een node-set op een vlak door schalen of balken gelden dezelfde regels als in fase 4 (strook, balkeind). Tot
   fase 4 klaar is: alleen volume-elementen, anders de bestaande weigering.

## Regels na review

1. **Eigen plan.** `fb_nodecut` bouwt zelf het gereduceerde plan: snedeknopen = de geselecteerde knopen plus middenknopen van ribben waarvan
   beide hoeken geselecteerd zijn; vlakken = vlakken van de laag met alle hoeken geselecteerd en een buur aan de andere kant; groepen daaruit.
   `plan_cuts` op de laag wordt hier niet gebruikt: die zou de achterkant van de laag als snede zien. `assign_nodes` en `section_geometry`
   werken ongewijzigd op het gereduceerde plan.
2. **Eén filter.** Eén functie filtert alle parallelle reeksen van het resultaat per stap samen (`nodes`, `forces`, `disp`, `on_cut`,
   `rest`), zodat een kracht nooit bij een andere knoop terechtkomt.
3. **Middenknopen via de mesh.** Een middenknoop hoort bij de snede als beide hoeken van zijn ribbe geselecteerd zijn: bij hex20 via de
   knoopnummers, bij LINE_QUAD via het ribbemidpunt. Nooit via de afstand tot het vlak.
4. **Weigeringen.** Minder dan drie knopen of knopen op één lijn: `nodes_collinear`. Knopen zonder volume-element: `nodes_without_solid`.
   Niet in één vlak: `nodes_not_planar`. Vlak door elementen: `plane_through_elements`. Eén tolerantie voor "op het vlak", in de vlakcontrole
   en de kantregel.
5. **Volledig of deel.** Volledig als de gedeelde knopen van het gegroeide lichaam een deelverzameling zijn van de geselecteerde knopen plus
   hun middenknopen, en de groei niet naar de andere kant lekt. Een extra geselecteerde knoop die niet gedeeld wordt (inspringende hoek), maakt
   een volledige snede dus geen deeldoorsnede.
6. **Normaal.** De normaal wijst van de gekozen kant af en krijgt een vast teken (zoals `_sign_fixed`), zodat "andere kant" tussen runs niet
   wisselt. Andere kant = exact tegengestelde resultant om hetzelfde punt; dat is een test.
7. **Wat het paneel zegt bij een deeldoorsnede:** "de knopen sluiten geen lichaam af; de som is de kracht door het vlak bij deze knopen".
   Randknopen dragen een deel van de aangrenzende vlakken mee, dus oppervlak en zwaartepunt passen niet precies bij de som. Ook dat staat erbij.
8. **Fase 4.** `not_shared_on_cut` toetst tegen de gereduceerde snedeknopen. Een tie in de laag blijft bij een deeldoorsnede onzichtbaar,
   omdat `rest` dan uit staat; het paneel noemt dat.

## Waar het komt

| Deel | Bestand | Inhoud |
|---|---|---|
| Kern | nieuw `Scripts/fb_nodecut.py` (Python 2/3, zonder Mecway) | vlak, kant, controle op elementgrenzen, groei, volledige of deeldoorsnede, filter op de geselecteerde knopen |
| Aansluiting | `fb_core` en `fb_aster` ongewijzigd, op één punt na: een filter op `result["nodes"]` vóór `assign_nodes` bij een deeldoorsnede, en `rest` uit | via `fb_nodecut` |
| Mecway | `fb_mecway.read_selection` | knopen lezen met `mw.selected_nodes()` |
| Paneel | `fb_gui` | keuze "elementen" of "knopen op een vlak", knop "andere kant", melding bij een deeldoorsnede, vlak in de tekening |

Eigen module, zodat het niet botst met het fase 4-werk in `fb_core` en `fb_aster`. Het paneeldeel gaat mee met het fase 4-paneel.

## Testen

Statica met twee sneden blijft de referentie, op kleine eigen modellen door de bridge-code en Code-Aster, zoals E9:

- blok, knopen van een volledige dwarsdoorsnede: zelfde getallen als bij de elementselectie aan die kant, beide kanten (tegengesteld);
- dezelfde snede met hex20 en met hex8 + LINE_QUAD: middenknopen goed meegenomen;
- deeldoorsnede (alleen de bovenste helft van de doorsnede): som over die knopen gelijk aan de som uit de volledige run over dezelfde
  knopen; melding `partial_section`; `rest` niet getoond als evenwicht;
- weigeringen: knopen niet in een vlak, vlak door elementen, geen knopen;
- U-vormig lichaam, beide kanten: vanaf het uiteinde volledig, vanaf de basis deel; gelijk en tegengesteld;
- extra geselecteerde knoop die niet gedeeld wordt: blijft volledig;
- knopen op één lijn: weigering; hex20 niet-lineair met achterknopen in het resultaat: het filter houdt krachten bij hun knoop;
- tet10-mesh met een snede over een vlak dat samenvalt met elementvlakken.

Elk onderdeel wordt getest en door Fable gereviewd. Testvensters nooit op het scherm, geen focus, niet aan het klembord.
