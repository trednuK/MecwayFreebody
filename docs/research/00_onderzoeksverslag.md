# MecwayFreebody: onderzoeksverslag en voorstel

Datum: 7 november 2026. Mecway 35 (35.0.9802; eigen oudere notities noemen 34). Status: vooronderzoek;
er is nog niets gebouwd. Dit verslag is onafhankelijk gereviewd door Fable; de verwerking staat in §11.

Labels: **getest** = zelf gemeten in Mecway 35 op eigen proefmodellen (§5); **gedocumenteerd** = gelezen in
de handleiding, de API-referentie of de genoemde bron; **aanname** = afgeleid, nog niet gemeten.

## 1. Samenvatting

**Vraag.** Bij een selectie elementen in een grotere constructie willen we op elk snedevlak de resulterende
kracht en het resulterende moment zien: in Mecway, met vectoren en getallen, ook als tabel om te kopiëren.
Standaard rond het neutrale punt, of rond een willekeurig punt dat de gebruiker kiest.

**Bestaande tools.** Er is geen open-source tool die dit in Mecway doet. Mecway zelf biedt geen moment rond
een punt op een snede; het forum komt niet verder dan een handmatige omweg waarvan de ontwikkelaar het
moment zelf niet vertrouwt. CalculiX, FreeCAD, PrePoMax en Code-Aster kennen het principe, maar alleen in hun
eigen wereld en deels vooraf in te stellen. OpenAEC heeft een FEM-programma, maar geen snedefunctie, en dat
staat onder AGPL. Alleen de concepten zijn overdraagbaar. Dat is ook de bruikbare opbrengst van de
closed-source pakketten: de vorm van het gereedschap (Abaqus *free body cut*, Altair *FBD*).

**Kernbevinding.** De voor de hand liggende aanpak, spanning over het snedevlak integreren, is onnauwkeurig. Op
een grove mesh zit in de kracht tot 24% fout: bij hex20 vooral in de dwarskracht (36% in de dunne richting, met
twee elementen over de breedte; N is daar goed), bij tet10 ook in de normaalkracht (29%). Naast een inspringende
hoek is de fout 60-112%. Rekenen met de **knoopkrachten** van de elementen is veel beter, en dat staat ook zo in
de literatuur (§3). Knoopkrachten zijn niet via de API te krijgen, maar er is een route gevonden en getest:

**Hoofddoel.** De tools ontsluiten primair Code-Aster, met Mecway als voorkant. Daarom is de hoofdroute anders dan
in de eerste versie van dit verslag: de krachten komen uit Code-Aster zelf.

**Code-Aster: bewaarde base, korte vervolgrun (route C, hoofdroute).** De bridge bewaart per run de rekenbasis. Na een
selectie in Mecway volgt een korte `POURSUITE` die de knoopkrachten van de selectie uitrekent (3-5 s, ook op 20 736
elementen). Op eigen modellen klopte dit op elke snede apart: tot circa 1e-9 lineair, tot 2e-7 niet-lineair (begrensd
door de convergentie-eis), op volume-elementen, schalen en balken, ook voorbij vloei en met grote verplaatsingen.
Uitzondering: moment om de normaal bij gebogen en geknikte schalen (§5).

**Mecway's eigen solver en CalculiX: laag opnieuw rekenen (M4L, op verzoek).** Alleen de laag elementen aan de snede
wordt in een verborgen Mecway doorgerekend met alle knopen vast op de berekende verplaatsing. In 530 metingen klopte
dit op elke snede apart, beter dan 1e-6, behalve gebogen quad8/tri6 met oppervlaktelast (0,13%, door Mecway's eigen
lastintegratie). Alleen voor lineaire resultaten. Het hoofdplan bouwt dit niet: resultaten van Mecway's eigen solver krijgen
dus nog geen snedekrachten.

**Voorstel.** Een paneel naast Mecway, in de stijl van MecwaySectionProps. De gebruiker selecteert elementen; het script
vindt de sneden en haalt de krachten op. Daarna is alles rekenwerk op de vaste lijst knoopkrachten: het punt verslepen
op een tekening van de doorsnede, andere assen, de tabel. Pijlen staan in het paneel en ook in Mecway's eigen
oplossingsbeeld: een script kan via `solution.set_variable` de vectorgroep *external force* of *reaction moment* live
vullen (§6.3). Getallen kunnen alleen in het paneel staan.

## 2. Wat de beschrijving vraagt

- Resultanten op de snedevlakken van een selectie elementen die deel is van een grotere constructie.
- Weergave in de Mecway-omgeving, visueel met vectoren en getallen, en als tabel die makkelijk te
  kopiëren of op te slaan is.
- De vectoren staan op de gekozen plek op de doorsnede; een apart scherm met een tekening van de doorsnede
  mag ook, liefst dynamisch.
- Standaard het neutrale punt, en een willekeurig ander punt dat een herberekening geeft.
- Vooraf onderzoek naar bestaande open-source tools (expliciet OpenAEC en de FreeCAD-gemeenschap), concepten
  uit closed-source en wetenschappelijke literatuur. Alles moet legaal zijn en commercieel gebruikt mogen
  worden voor eigen gebruik binnen het bedrijf.

## 3. Bestaande tools en concepten

### 3.1 Open source

| Tool | Licentie | Wat het kan | Bruikbaar? |
|---|---|---|---|
| **OpenAEC**: `open-fem-studio-mechanics` | AGPL-3.0, alpha | Eigen FEM voor raamwerken en schalen, met snedekrachtlijnen van staven; zoekopdrachten in de repo op section cut, free body en integration strip gaven niets | Geen functie om over te nemen. Niets kopiëren: AGPL past niet in een MPL-project |
| **OpenAEC**: overige repo's (lijst op naam doorzocht, plus codezoekopdrachten) | wisselend | Geen snede- of post-processinggereedschap gevonden | Nee |
| **FreeCAD FEM**: *Section print feature* | LGPL-2.1 | Schrijft de CalculiX-kaart `*SECTION PRINT` weg; de krachten komen als tekst in het `.dat`-bestand; een vlak per keer | Bevestigt het concept. Aanvraag vooraf, geen weergave, geen gekozen punt. Forumzoektocht gaf geen macro die dit achteraf doet |
| **CalculiX** `*SECTION PRINT` (SOF, SOM, SOAREA) | GPL-2.0 of later | Kracht en moment op een oppervlak, uit spanningen op de vlakken; forumgebruikers melden onnauwkeurigheid op grove meshes | Moet vooraf aan het model worden toegevoegd; dezelfde zwakte als M1. Alleen volume en balk, geen schalen (forum) |
| **PrePoMax** | GPL-3.0 of later | Section-uitvoer op gekozen vlakken, bovenop CalculiX | Concept. Geen route naar Mecway |
| **Code-Aster** `CALC_CHAMP FORC_NODA` + `POST_RELEVE_T` (`RESULTANTE`, `MOMENT`, `POINT`) | GPL-3.0 | Knoopkrachten per groep cellen, sommatie rond een punt. Dit is precies de knoopkrachtenaanpak | Sterk concept, en via de bridge later direct te gebruiken (§6.5) |
| **pyNastran**: `extract_freebody_loads`, `shear_moment_diagram` | BSD-3-achtig | Sommeert *grid point forces* uit Nastran-resultaten | Nette referentie; leest OP2, niet Mecway. Docs melden beperkingen rond sommatie om een punt in oudere versies |
| **MYSTRAN** (meegeleverd bij Mecway) | MIT | Kent als Nastran-achtige solver in principe `GPFORCE`-uitvoer; Mecway staat eigen case control toe | Mecway noemt de solver zelf nog niet aanbevolen. Geen hoofdroute |
| **ParaView / VTK** | BSD-3 | Slice + integratie, met eigen Python voor tractie | Zelfde zwakte als M1; aparte toepassing |
| **sectionproperties** | MIT | Doorsnede-eigenschappen, ook samengesteld | MecwaySectionProps doet dit al met dezelfde formulering; niet nodig |
| **MecwaySectionProps** | MPL-2.0, eigen | Vlakken lezen, randlussen, zwaartepunt, tekening met `System.Drawing`, paneel, kopiëren | **Hergebruiken** als basis voor doorsnede en tekening |
| **MecwayAsterBridge** | MPL-2.0, eigen | Lezen en schrijven `.liml`, `<results>`, belastingen uit XML, veilig starten van processen | **Hergebruiken** als patroon voor het tweede rekenproces |

### 3.2 Mecway zelf (gedocumenteerd)

- *Solution > Surface Integral*, *Surface Normal Integral*, *Sum* en *Formula* bestaan. *Sum* werkt alleen op
  reactie- en externe krachten en formules; moment om de oorsprong is met een formule te maken voor
  reactiekrachten, maar niet voor interne krachten.
- Forum, draad *Cross section forces* (2020): vlakselectie langs de snede, *force per length* en
  *Surface integral*. Voor het moment stelt de ontwikkelaar een formule voor, maar noemt die zelf onzeker.
- Membraankrachten en dwarskracht in schalen zijn beperkt beschikbaar; CalculiX geeft geen interne krachten
  van schalen (forum, ontwikkelaar).

### 3.3 Concepten uit closed-source

| Pakket | Concept | Wat we overnemen |
|---|---|---|
| **Abaqus/CAE** free body cut | Vectoren in beeld; sommatiepunt standaard in het zwaartepunt van de snede, of aangeklikt. De documentatie waarschuwt dat het over elementen integreert | Standaardpunt in het zwaartepunt; vectoren op het punt; keuze uit zwaartepunt, gemiddelde knoop, zelf opgegeven |
| **Patran**, **Altair FBD** | Vrij lichaam uit een elementenset; knoopbalans; resultant versus kracht per knoop; sommatiepunt of zwaartepunt per snede | Weergavekeuze *resultant* of *per knoop* |
| **Nastran** GPFORCE | Balans per knoop: element, belasting, oplegging, MPC | Vier bijdragen uit elkaar houden in de controle op evenwicht |
| **ANSYS** FSUM | Knopen van de doorsnede plus elementen aan één kant selecteren, dan sommeren | Dezelfde betekenis: alleen de elementen aan de geselecteerde kant tellen mee |
| **SAP2000** section cut | Som van krachten op knopen, naar een gemeenschappelijk punt verplaatst en gedraaid naar een assenstelsel | Bevestigt de werkwijze; rapportage in een eigen assenstelsel |
| **HyperWorks** FBD section plot | Reeks sneden langs een lijn | Latere uitbreiding: krachtlijn langs een doorsnedereeks |

Concepten en werkwijzen zijn vrij bruikbaar. Teksten, schermafbeeldingen en code van deze pakketten nemen we
niet over.

### 3.4 Literatuur

De kern: in een FEM met verplaatsingen voldoen **gebalanceerde knoopkrachten exact aan het discrete
evenwicht**, terwijl teruggerekende spanningen dat niet doen.

- **Hughes, Engel, Mazzei & Larson (2000)**, *The continuous Galerkin method is locally conservative*, J.
  Comput. Phys. 163(2), 467-488. Knoopkrachten en randflux uit de zwakke vorm voldoen aan lokaal evenwicht.
- **Carey, Chow & Seager (1985)**, *Approximate boundary-flux calculations*, CMAME 50(2), 107-120;
  **Chow, Pehlivanov, Carey & Lazarov (1994)**, *Superconvergence analysis of approximate boundary-flux
  calculations*. **Mizukami (1986)**, *A mixed finite element method for boundary flux computation*.
  **Zhong, Gurnis & Hulbert (1993)**, de *consistent boundary flux*-methode. De flux via de zwakke vorm
  convergeert sneller dan de flux via de gradiënt op het vlak. Dat is de theorie achter M3 en M4.
- **Dong (2001)**, *A structural stress definition and numerical implementation for fatigue analysis of
  welded joints*, Int. J. Fatigue 23(10), 865-876. Praktijkvoorbeeld: knoopkrachten geven een vrijwel
  mesh-onafhankelijke structurele spanning. Zie §7 over het patent.
- **Zienkiewicz & Zhu (1992)**, *The superconvergent patch recovery and a posteriori error estimates*, IJNME
  33, 1331-1364, en **Hinton & Campbell (1974)**, IJNME 8, 461: verklaren waarom spanning op knopen een
  benadering is en beter is op integratiepunten dan op het vlak.
- **Pilkey** (doorsnede-eigenschappen): al gebruikt in MecwaySectionProps.

Van deze publicaties zijn bibliografische gegevens en secundaire beschrijvingen gezien, niet de volledige
teksten. Titel, auteurs en vindplaats van Hughes e.a., Carey e.a., Dong en Zienkiewicz & Zhu zijn gecontroleerd
in Crossref. De inhoud van de artikelen is **niet geverifieerd**; de conclusie is daarom in §5 zelf nagemeten.

## 4. Wat Mecway mogelijk maakt

**Gedocumenteerd of getest in zustermappen:**

- Lezen kan: `selected_elements()`, knopen, elementen, `face_nodes`, `solution.node_value`,
  `solution.element_node_value` (spanning per element, niet gemiddeld), `surface_integral`, `interpolate`.
- Niet kan: camera, kleuren, zichtbaarheid, tekst of pijlen tekenen, selectie zetten, belastingen uitlezen,
  knoopkrachten opvragen. Belastingen komen uit het `.liml`.
- Vectorvelden tonen als pijlen wanneer de groep in de boom is gekozen. `solution.set_variable` kan een nieuw
  knoopveld maken, alleen op knopen van de laatste solve (zie §6.3 voor wat dat oplevert).
- Niet-modale WinForms-panelen werken (patroon uit een apart hulpmiddel en MecwaySectionProps).
- `mw.open()` sluit een paneel; hulpschillen zonder materiaal kunnen een solve leeg maken.

**Nieuw getest in dit onderzoek (Mecway 35, verborgen runs):**

- Een `.liml` waarvan knoop- of elementnummers gaten hebben of niet bij 1 beginnen, gaf met `mecway.exe ...
  solve` **zonder melding geen oplossing**; hernummeren loste het op. Welk van de twee de oorzaak is, is niet
  uitgesplitst. Eigen notities zeggen dat gaten mogen; dat geldt dus niet voor deze solve.
- `<fixed>` op een knopenselectie van schalen hield het model niet vast in deze proef (singuliere oplossing,
  geen reacties); `displacement` plus `noderotation` wel. De oorzaak is niet onderzocht.
- De reacties bestaan alleen op vastgezette knopen (`reactionforcex`, `reactionmomx`).
- CalculiX via Mecway slaat **geen `element_node`-spanning** op en geen `reaction force`, maar wel **`external
  force` op alle knopen**; dat zijn CalculiX' knoopkrachten.
- Een solve van een elementlaag met tot circa 2 750 vastgezette vrijheidsgraden kostte 2-6 s, inclusief het starten van Mecway.
- Een script start in een open model via *File > Import*; *File > Open* van een `.py` sluit het model. In de stand `mecway.exe model script x.py` blijft de gebruikersinterface leeg,
  ook als het script het venster zichtbaar maakt.
- `set_variable("externalforcex/y/z")` en `("reactionmomx/y/z")` maken in een lopend script de vectorgroepen *external
  force* en *reaction moment* aan, inclusief *magnitude*. Eigen namen (`fbforcex`) geven alleen losse scalaire velden.
- `<moment>` op een selectie van twee of meer knopen doet stil niets (quad4; één knoop werkt wel).
- Rotaties in de oplossing zijn globale vectoren; alle drie vastzetten met `rotx/y/z` werkt, ook op een vouwlijn.
- Traction op een schaalvlak grijpt aan op het schaaloppervlak, niet op het middenvlak. Bij een offset grijpt
  zwaartekracht aan op het offsetvlak en een knoopkracht op de knoop.
- Zes verborgen solves naast een zichtbare, stilstaande Mecway gaven geen dialoog en hetzelfde resultaat (3e-12
  relatief). Niet getest: een gebruiker die in die Mecway werkt of daar tegelijk rekent.

## 5. Experimenten

Alle modellen zijn eigen blokken van 200 x 20 x 40 mm, staal, ingeklemd op `x = 0`, met kracht op de top,
torsie door een excentrische kracht, en zwaartekracht. Referentie: de statica van wat er aan de andere kant
van de snede hangt. Code in `experiments/`; de resultaten zijn reproduceerbaar met `e1_methods.py` en
`e2_shell.py`.

| Methode | Omschrijving |
|---|---|
| **M1** | Gemiddelde knoopspanning over het vlak integreren (de forumroute, en in opzet `*SECTION PRINT`) |
| **M2** | Element-knoopspanning van de geselecteerde kant over het vlak integreren |
| **M3** | Knoopkrachten uit spanning: ∫Bᵀσ dV over de elementen aan de snede, som over de snedeknopen, min de lasten daar |
| **M4** | Hele selectie opnieuw rekenen met de snedeknopen vast op hun verplaatsing; reacties aflezen |
| **M4L** | Alleen de elementlaag aan de snede opnieuw rekenen, met **alle** knopen van die laag vast |

Bij één snede is de totale reactie van M4 ook bij een verkeerde berekening gelijk aan de belasting (globaal
evenwicht). Daarom is de echte toets de **selectie tussen twee sneden** (`mid`): daar moet elke snede apart
kloppen.

### Fout in kracht / moment (procent, rechte mesh, interne solver)

| Geval | M1 | M2 | M3 | M4 |
|---|---|---|---|---|
| hex20, 80 el. | 18,6 / 0,002 | 18,6 / 0,59 | < 1e-9 | < 1e-9 |
| hex20, 640 el. | 4,8 / 0,0004 | 4,8 / 0,08 | < 1e-8 | < 1e-8 |
| hex20, 2160 el. | 2,1 / 0,0002 | 2,1 / 0,02 | < 1e-7 | < 1e-7 |
| hex8, 640 el. | < 1e-8 / 0,001 | 0,01 / 5,0 | < 1e-8 | < 1e-8 |
| tet10, 480 el. | 24 / 0,02 | 27 / 2,5 | < 1e-8 | < 1e-8 |
| tet4, 480 el. | 10 / 58 | 282 / 65 | < 1e-9 | < 1e-9 |
| Trapsnede, hex20 | 19 / 0,1 | 19 / 0,8 | < 1e-8 | < 1e-8 |
| Snede op inspringende hoek, hex20 480 el. | 60 / 6,6 | 20 / 2,7 | < 1e-8 | < 1e-8 |
| Idem, hex8 | 98 / 20 | 0,006 / 5,0 | < 1e-8 | < 1e-8 |
| Idem, tet10 | 112 / 16 | 18 / 1,7 | < 1e-8 | < 1e-8 |

Per component is het beeld genuanceerder (M1, 80 el., N, Vy, Vz, exact -2000, -1300, 1006 N): hex20 geeft
-2000, -1772, 1100, dus N goed en Vy 36% en Vz 9% af. tet10 geeft -1414, -1510, 1060, dus ook N 29% af. Op de
inspringende hoek is N zelf fout (hex20: -1143 in plaats van -2000 N). M1 op hex20 convergeert met h² (18,6 → 4,8 →
2,1), dus dit is een discretisatiefout en geen rekenfout. De CalculiX-data geven dezelfde waarde.

### Scheve mesh, twee sneden (slechtste snede)

| Geval | M1 | M3 | M4 | M4L |
|---|---|---|---|---|
| hex20, 640 el. | 5,5 / 0,20 | 0,14 / 0,03 | < 1e-9 | < 1e-9 |
| hex8, 640 el. | 0,70 / 0,44 | 1,3 / 0,15 | < 1e-9 | < 1e-9 |
| tet10, 3840 el. | 6,7 / 0,41 | 0,31 / 0,05 | < 1e-8 | < 1e-8 |
| tet4, 3840 el. | 7,9 / 31 | < 1e-9 | < 1e-9 | niet gedraaid |

Op een scheve mesh is M3 dus **niet** exact. De waarschijnlijke oorzaak is dat M3 teruggerekende knoopspanning
gebruikt, die het veld in de integratiepunten alleen bij rechte elementen teruggeeft; tet4 (constante spanning)
blijft exact. Evalueren in 2x2x2 of 4 punten hielp niet. Die verklaring is **niet bewezen**. De eerlijke kanttekening
bij M4 en M4L: bij een correcte lineaire solver kunnen ze niet anders dan kloppen, want reactie = K·u - f van de
laag. De toets met twee sneden bewijst dus de implementatie (teken, knopen, lasten), niet een nauwkeurigheid. Dat
M3 op rechte meshes langs een andere weg tot 1e-11 hetzelfde geeft, is de onafhankelijke controle.

### CalculiX via Mecway, twee sneden, rechte mesh

| Geval | M1 | M3 op gemiddelde spanning | M4 op `external force` |
|---|---|---|---|
| hex20, 80 el. | 19 / 0,6 | 1,1 / 0,6 | 0,008 / 0,001 |
| hex20, 640 el. | 4,8 / 0,01 | 0,02 / 0,09 | 0,004 / 0,0002 |
| tet10, 480 el. | 24 / 0,14 | 0,6 / 1,1 | 0,008 / 0,002 |
| hex8, 640 el. | 0,004 / 0,008 | 0,004 / 0,006 | 0,01 / 0,0004 |

### Schalen en balken, twee sneden, M4 met rotaties vast

quad4, quad8 en line2 op rechte modellen: fout kleiner dan 1e-8 procent op elke snede, voor alle zes componenten
(`e2_shell.py`). De rotaties op de snedeknopen moeten mee worden vastgezet, en de *reaction moment* hoort bij de som.

### Overige elementen en gevallen (M4 en M4L, 507 solves)

Fracties, geen procenten; slechtste snede, slechtste van M4 en M4L. Maat: eF = |ΔF| / max(|F|, |M|/L), eM = |ΔM| /
max(|M|, |F|·L), zodat een snede met bijna geen moment geen schijnfout geeft. De ruwe fout op |M| is hooguit 1,4 keer eM.
Code: `e6_*.py`. Deze metingen liepen in een aparte sessie; de slechtste waarden zijn nagerekend uit de resultaatbestanden.

| Geval | Element | eF | eM |
|---|---|---|---|
| Vlakke schaal, in 3D gedraaid, scheef | quad4, tri3, quad8, tri6 | 9e-11 | 2e-10 |
| Geknikte schaal 90/60 graden, ook snede precies op de vouw | alle vier | 2e-10 | 3e-10 |
| Boog 90 graden, zwaartekracht | quad4, tri3 | 5e-11 | 7e-11 |
| Idem | quad8, tri6 | 3e-8 | 9e-7 |
| Balk recht, gedraaid, frame, T met drie sneden | line2 | 1e-11 | 3e-11 |
| Blok recht en scheef | wedge6, pyr5, pyr13, hex + pyr | 2e-11 | 4e-10 |
| Idem | wedge15 | 6e-9 | 4e-8 |
| `refine_x2`, trapsnede door de overgang | hex, pyr, tet, wedge gemengd | 8e-12 | 2e-11 |
| Druk, traction, kracht in de laag, recht en scheef | hex8, hex20, tet4, tet10, wedge15, pyr13 | 1e-10 | 1e-9 |
| Idem op schaal, vlak en knik | alle vier | 2e-10 | 2e-10 |
| Idem op boog | quad4, tri3 | 9e-11 | 2e-11 |
| Idem op boog | quad8, tri6 | **1,3e-3** | **8,9e-4** |
| Kracht exact op een snedeknoop, geteld als overkant | hex8, hex20 | 9e-12 | 1e-11 |
| T-profiel volume + schaal, gedeelde knopen | vier volume-, vier schaaltypen | 8e-12 | 2e-11 |
| Schaal met offset, vlak en knik | alle vier | 2e-10 | 2e-10 |

De 1,3e-3 op de boog is geen fout van M4L. Mecway's eigen lastintegratie op gebogen quad8/tri6 wijkt af van de exacte
integraal (druk: 1,6% in de totale kracht op deze mesh). Tegen Mecway's eigen knooplasten klopt M4L tot 1e-9. De
evenwichtscontrole toont daar dus een restverschil. De oorzaak en de convergentie zijn niet onderzocht.

**Negatieve controles**: de metingen kunnen wel degelijk falen. Rotaties weglaten geeft 40-700% fout, twee van de drie
rotaties 17-460%, offset niet meekopiëren een veelvoud, geen last in de laag 2-10% bij volume-elementen en 0,7% bij
vlakke quad8/tri6.

**M3 op andere elementen**: op wedges en pyramiden fors slechter (pyr13 scheef 50%, wedge15 scheef grof 220%), ook op
de gemengde laag uit `refine_x2` (20%). De oorzaak is niet gevonden. Dat bevestigt dat M3 geen hoofdmethode kan zijn.

### Code-Aster 17.4: vier routes (E7)

Eén definitie: `CALC_CHAMP FORCE='REAC_NODA'` met `GROUP_MA` = selectie plus de huidcellen ervan, gesommeerd over de
snedeknopen. Dat is wat de rest via die knopen op de selectie doet. Zonder huidcellen geeft Code-Aster alleen een alarm en
is de fout 1,6%. Eigen modellen, zelf nagebouwd in de stijl van de bridge; de echte bridge en Mecway zijn hier niet gebruikt.
Code: `e7_*.py`. Maat als bij E6, slechtste snede en slechtste stap.

| Route | Hoe | Selectie vrij na de run? |
|---|---|---|
| **A** | Mee in de eerste run, via `#ASTER-POST` | Nee |
| **B** | Tweede run uit de `.rmed` met `LIRE_RESU` | Ja |
| **C** | Tweede run met `POURSUITE` op de bewaarde base | Ja |
| **D** | Eerste run dumpt elementkrachten; sommeren in het paneel zonder Code-Aster | Ja |

| Model | A, B, C: eF / eM | D: eF / eM |
|---|---|---|
| HEXA20, recht en scheef | 2e-11 / 2e-11 | 2e-11 / 2e-11 |
| TETRA10, recht en scheef | 5e-12 / 2e-10 | 5e-12 / 2e-10 |
| HEXA8, recht en scheef | 1e-11 / 5e-12 | 2e-12 / 7e-13 (scheef) |
| HEXA20 + PENTA15 scheef | 5e-12 / 2e-11 | 5e-12 / 2e-11 |
| Druk, traction, zwaartekracht naast de snede | 2e-11 / 2e-10 | 2e-12 / 2e-11 |
| DKT vlak, gedraaid, met druk | 7e-11 / 4e-11 | 6e-11 / 2e-11 |
| DKT geknikt, gebogen | 3e-11 / 9e-4 | niet gedraaid |
| COQUE_3D, ook met druk | 4e-10 / 2e-10 | 2e-10 / 1e-10 |
| COQUE_3D geknikt, gebogen | 3e-5 / 9e-5 | niet gedraaid |
| POU_D_E, POU_D_T, recht en frame | 2e-11 / 1e-11 | 2e-11 / 7e-12 (POU_D_E) |

| Niet-lineair, 12+ stappen met ontlasten | A, C | B | D |
|---|---|---|---|
| HEXA20 plastisch, p tot 3,3% | 2e-10 / 2e-11 | gelijk | 2e-10 / 2e-11 |
| Idem, `RESI_GLOB_RELA` 1e-6 | 2e-7 / 2e-8 | gelijk | niet gedraaid |
| TETRA10, HEXA8 plastisch | 5e-11 / 3e-11 | gelijk | niet gedraaid |
| GDEF_LOG, u 35 mm, som op x+u | 2e-9 / 4e-11 | gelijk | 2e-9 / 4e-11 |
| GDEF_LOG + volgdruk, u 97 mm, 39 stappen | 2e-8 / 2e-9 | gelijk | niet gedraaid |
| DKT plastisch | 1e-10 / 3e-12 | **faalt** | niet gedraaid |
| COQUE_3D GROT_GDEP, elastisch en plastisch | 2e-8 / 7e-9 | **faalt** | niet gedraaid |

Wandklok in seconden, HEXA20, 4 cpu's, machine niet exclusief. Op 20 736 elementen is de niet-lineaire D-route niet gedraaid.

| | 2 000 lineair | 20 736 lineair | 2 000 niet-lineair | 20 736 niet-lineair |
|---|---|---|---|---|
| Eerste run | 7,8 | 138 | 80 | 645 |
| Route B | 3,8 | 7,5 | 4,5 | 7,0 |
| **Route C** | 3,1 | 4,8 | 4,0 | 4,6 |
| Route D, selectie in Python | 0,05 | 0,38 | 0,13 | niet gedraaid |
| Base | 137 MB | 442 MB | 180 MB | 333 MB |
| `.rmed` | 3 MB | 33 MB | 42 MB | 192 MB |

Een lege base is al circa 125 MB. Route D kost 25 MB per stap op 20 736 HEXA20.

Waarom C en niet de rest:

- **B** is stil fout bij gewijzigde gegevens met alleen DEPL, faalt op niet-lineaire schalen doordat `SIEF_ELGA` daar niet
  terugkomt uit de `.rmed`, en vraagt de setup van de run opnieuw.
- **A** is nu al bruikbaar als recept (`e7_recipe.py`), maar een andere selectie vraagt een nieuwe volledige run.
- **D** is het snelst in gebruik maar de meeste eigen code, met twee API-paden, en is niet gedraaid op volgdruk en
  niet-lineaire schalen. Blijft mogelijke uitbreiding.

Gemeten aandachtspunten:

- **Grote verplaatsingen**: `POST_RELEVE_T` rekent op onvervormde coördinaten (eM 6-12%). Zelf sommeren op x+u.
- **Schaalrotaties**: DRX, DRY en DRZ moeten mee in de som; zonder is het moment 48% af.
- **`FORCE_NODALE` op een snedeknoop** wordt door `REAC_NODA` afgetrokken en telt dus aan de kant van de selectie. Dat is
  andersom dan bij M4L en is achteraf niet schoon terug te tellen, omdat het veld ook de verdeelde lasten bevat.
- **Oplegging op een snedeknoop**: de reactie zit in de snedekracht. Het model `l_supp` wijkt daardoor 80% af van de statica
  van de rest; het verschil is precies de oplegreactie (tot 1e-8 N). Dat is geen rekenfout maar een conventie (§6.2). Hetzelfde
  geldt voor koppelingen, contact en veren, die in Code-Aster geen lasten zijn. De kolom `rout` in `table.txt` (0,5-1,0
  bij schalen en balken) is een presentatiefout van `e7_table.py`; een aparte nacontrole gaf 1e-9 N restkracht.
- **Fictieve boorstijfheid**: op geknikte en gebogen schalen is de momentfout evenredig met `COEF_RIGI_DRZ` (9e-6, 9e-4 en
  4e-2 bij 1e-7, 1e-5 en 1e-3) en groeit met een fijnere mesh. Moment om de schaalnormaal aan de tip: ruw tot 20%. Dat
  geldt voor alle routes en is een modeleigenschap. Het paneel moet erbij waarschuwen.
- **`CREA_MAILLAGE`**: bij `LINE_QUAD` veranderen de knopen; bepaal de snedeknopen dus in Code-Aster, met `DEFI_GROUP`
  `INTERSEC`, en niet in Mecway. Geverifieerd: 121 tegen 45 snedeknopen.
- **Tie**: geen gedeelde knopen, dus geen snede. De onbalans (2690 N) wijst de plek aan.

Negatieve controles leverden zichtbare fouten op: verkeerd teken eF 2, geen `GROUP_MA` 100%, middenknopen vergeten 136%,
plastisch resultaat als elastisch gelezen tot 3300%. De metingen kunnen dus falen. A, B, C hebben hetzelfde codepad; de
controle is de statica, niet hun onderlinge gelijkheid.

### Vervolgrun en keten (E8, E9)

**Celnamen (E8).** In de base hebben cellen geen naam meer maar een positie: `M<eid>` in `DEFI_GROUP` wijst stil de verkeerde cel
aan. De positie in het meshbestand blijft wel gelijk, ook na `LINE_QUAD` en `QUAD8_9`/`TRIA6_7` (0 afwijkingen). Daarom bevat het
manifest de cellen in bestandsvolgorde. Groepen maken gaat met `M.setGroupOfCells(naam, [i-1 for i in posities])`, ingelezen uit
JSON: 0,009 s op 19 800 cellen.

**`EXCIT` is niet nodig (E8).** `REAC_NODA` in de vervolgrun vindt de lasten zelf, ook bij volgdruk, `FONC_MULT`, `AFFE_CHAR_MECA_F` en
elke tussenstap (slechtste fout 9e-9). Negatieve controles geven wel zichtbare fouten.

**Base (E8).** `R base <pad> D 0` laat de base ongemoeid; twee vervolgruns tegelijk werken. `memory_limit` hoeft niet gelijk aan de
eerste run: piek 490-510 MB, los van de limiet. Elke vervolgrun gebruikt tijdelijk circa 550 MB schijf bij een base van 442 MB.

**Hele keten door de echte bridge-code (E9).** `.liml` naar bridge met `keep_base`, Code-Aster, manifest, vervolgrun, som per snede, tegen
statica met twee sneden en een last op de selectie naast de snede. Mecway zelf is hier niet gebruikt.

| Model | Snedeknopen | Vervolgrun | eF | eM |
|---|---|---|---|---|
| HEXA20, lineair | 242 | 2,1 s | 8e-12 | 4e-12 |
| HEXA8 met `LINE_QUAD`, lineair | 242 | 2,1 s | 6e-12 | 2e-12 |
| HEXA20 plastisch, grote verplaatsingen, u 5,8 mm | 242 | 2,2 s | 7e-13 | 4e-14 |

**Vorm bij het sommeren (E9).** Lineair moet op de onvervormde vorm: op x+u is het moment 1e-3 af. Niet-lineair met grote verplaatsingen
moet op x+u: anders 6e-4 af. Het manifest noemt daarom de `deformation` van de run.

**Fingerprint (E9).** De hash via Mecway's API in IronPython is gelijk aan die in het manifest (3441 knopen).

**Weergave.** Een tweede veld over een getoond veld geeft geen nieuwe legenda, ook niet na wisselen tussen model en oplossing. Daarom krijgen
pijlen in Mecway een vaste schaal, met de echte getallen in het paneel. Op een oplossing die de bridge heeft teruggeschreven is
`set_variable` nog niet getest.

### Niet getest

**Code-Aster:** contact, veren, thermisch, orthotroop, composiet, gebogen volumehuid, oplegging in niet-lineair, balken
niet-lineair, plasticiteit op COQUE_3D aan de snede, oude base na een Code-Aster-update, de echte bridge.
**Mecway-solver:** samengestelde en orthotrope materialen, oriëntaties, line3, MPC, contact of tie over de snede, balk +
volume of schaal, gedeeltelijk geofsette modellen, offset op balken, tijdstappen, CalculiX voor schalen, modellen groter dan
enkele duizenden elementen.

## 6. Voorstel voor de aanpak

### 6.1 Werkwijze voor de gebruiker

1. Model is opgelost en opgeslagen. Selecteer elementen en start *Tools > MecwayFreebody*.
2. Het paneel bepaalt de snede en rekent automatisch (enkele seconden, met voortgang).
3. Elke snede toont N, Vy, Vz, T, My, Mz in N en N·m of kN·m, standaard om het neutrale punt, met
   tekenconventie en de evenwichtscontrole duidelijk in beeld.
4. Tekening van de doorsnede (uit MecwaySectionProps) met pijlen en getallen. Het punt is te verslepen, in te
   typen of te kiezen: zwaartepunt, knoop, schuifmiddelpunt.
5. Tabel kopiëren of opslaan als CSV.

**Wat een snede is.**

- **Krachten**: de snedeknopen zijn alle knopen die de selectie deelt met de rest. Dat is knoopgebaseerd, zodat
  ook elementen meedoen die alleen via een ribbe of hoekpunt aan de rest hangen.
- **Meetkunde**: vlakken waarvan de buur niet geselecteerd is, alleen voor oppervlak, zwaartepunt en tekening. Bij
  schalen is de snede een rij ribben (dikte x lengte), bij balken een knoop (doorsnedeoppervlak).
- **Groepen**: losse groepen snedeknopen zijn aparte sneden. Sneden die knopen delen, zoals een flens die uit een
  profiel is geselecteerd, zijn één snede, omdat de knoopkracht daar niet eenduidig te splitsen is.

**Neutraal punt en assen.** Standaard het zwaartepunt; bij meerdere materialen het met E gewogen zwaartepunt. Volumesneden in
de hoofdassen van de doorsnede, E-gewogen. Schalen in het lokale stelsel (normaal, ribbe, dikte) en balken in de balkassen; dat
is de natuurlijke uitwerking van de keuze voor doorsnedeassen. Het moment om de normaal van een DKT-schaal staat altijd als
onbetrouwbaar gemarkeerd. Bij een niet-vlakke snede geen ontbinding in N, V, T en M, maar globale componenten of een
gekozen assenstelsel, met een melding.

### 6.2 Rekenkern

De kern is een vaste lijst krachten per snedeknoop. Alles daarna is rekenwerk dat niet weet waar die lijst vandaan komt.

**Hoofdroute: Code-Aster, route C.**

- **Bridge**: optie om per run de base te bewaren (`R base` in de `.export`), met `med_export` of de eigen resultaatroute
  ongemoeid. Dit is een wijziging in MecwayAsterBridge en wordt daar apart gedaan.
- **Vervolgrun**: `POURSUITE` met `DEFI_GROUP` voor selectie, huidcellen en snedeknopen, dan `CALC_CHAMP` `REAC_NODA`
  met `GROUP_MA`, voor elke stap, en een klein Python-blok dat de waarden naar JSON schrijft.
- **Som**: in onze eigen code, inclusief rotaties, op x+u als het manifest een `deformation` anders dan PETIT noemt, anders op x.
- **Koppeling Mecway naar Code-Aster**: cel `M<eid>`, bij een gesplitste line3 ook `H<eid>`, omgezet naar een positie via het manifest.
  De selectie gaat als JSON mee, niet als namen in de `.comm`.
- **Manifest per run**, geschreven door de bridge na een goed afgelopen run: run-id, configuratie, analysetype, Code-Aster-versie,
  `deformation`, vingerafdruk van de mesh, conceptnamen, cellen in bestandsvolgorde, en voor elke huidcel `K<n>` het element en vlak. De bridge maakt alleen huidcellen op
  belaste vlakken, zonder koppeling naar het element; zonder manifest gaat de selectie van huidcellen fout bij een trapsnede.
- **Conventie op snedeknopen**: alles wat op een snedeknoop grijpt en niet uit de selectie komt, telt als de rest: opleggingen,
  koppelingen, contact, veren. Een knooplast op een snedeknoop telt aan de selectiezijde, met een waarschuwing. Het paneel toont
  welke snedeknopen dit raakt.
- **Lezen, niet schrijven**: `R base ... D 0` in de vervolgrun, zodat twee vervolgruns naast elkaar kunnen. Verplaatsingen voor x+u
  komen uit de base, niet uit Mecway's `solution`.
- **Blokkeren met een melding**: modaal, knik, harmonisch; HOMARD-adaptiviteit (mesh vervangen); offset-schalen, flexibele
  verbindingen en POI1 tot ze getest zijn; model gewijzigd sinds de run (vingerafdruk); andere Code-Aster-versie; geen base.
- **Opruimen**: base bewaren is een keuze per run, met "bewaar N bases", want het gaat om 125-450 MB per run.
- **Paneel**: de vervolgrun in een eigen thread, de interface blokkeert nooit. Laden van bridge-resultaten sluit een open paneel
  (`mw.open()`); daar moet het paneel tegen kunnen.

**Op verzoek: Mecway's solver en CalculiX, M4L.** Dit is het grootste en riskantste stuk code voor bijvangst: verborgen
Mecway, dialoogbewaking, kopiëren van materialen, oriëntaties en offsets, alleen lineair. Daarom niet in het hoofdplan; de metingen
blijven als bewijs dat het kan. Komt het er alsnog, dan met deze regels:

- Elk element van de selectie met een snedeknoop, alle knopen vast (rotaties mee), doorlopend genummerd, zelfde solver, materialen,
  oriëntaties en offsets. Mee: lasten op de laag en temperatuur met `thermalstress`. **Niet** mee: opleggingen, contact, veren.
- Dezelfde conventie op snedeknopen als hierboven, dus een knooplast op een snedeknoop gaat mee in het deelmodel.
- Bron: de modelkopie in `<solution>` van het opgeslagen bestand. Lineair; anders blokkeren.

**Algemeen.**

- **Opslaan**: alleen met toestemming van de gebruiker, nooit stil.
- **Punt verschuiven**: M_P = M_O + (O - P) x F, direct bij slepen.
- **Stap kiezen**: bij niet-lineair standaard de laatste stap, met keuze uit alle stappen.
- **Evenwichtscontrole**: som van alle sneden plus bekende lasten op de selectie moet nul zijn. Het verschil staat in het
  paneel. Zo vallen krachten op die het script niet ziet: tie, bonded contact, MPC, veren.
- **Waarschuwingen**: schaalmoment om de normaal bij geknikte en gebogen schalen; kracht op een snedeknoop; niet-vlakke snede.
- **Geen stille terugval** op een minder nauwkeurige methode.

### 6.3 Weergave

De proef is gedaan op een eigen blok, met schermopnames van alleen dat Mecway-venster. Die opnames zijn weer verwijderd.

| Optie | Uitkomst | Besluit |
|---|---|---|
| **A. Paneel met eigen tekening** | Zelfde techniek als MecwaySectionProps; pijlen, getallen, sleepbaar punt | **Basis.** Wens van de gebruiker voor later: 3D-beeld in het paneel met draaibare doorsnede en pijlen, ook nuttig voor niet-vlakke sneden |
| **B. Vectorveld in Mecway** | **Werkt, getest** (met Mecway's solver; met Code-Aster-resultaten nog na te gaan). Een lopend script vulde *external force* en *reaction moment*; de pijlen staan in de oplossingsweergave, per snedeknoop of als één pijl, en nieuwe groepen verschijnen vanzelf in de boom | **Tweede weergave**, met de beperkingen hieronder |
| **C. Hulpelementen** | Getest met line2: zichtbaar in de modelweergave, niet in de oplossingsweergave, component rood zonder materiaal | Afvallen: B is beter en vervuilt het model niet |
| **D. Overlay over Mecway** | Geen camera in de API | Afvallen |

Beperkingen van B, gezien in de proef:

- Pijlen kunnen alleen op knopen staan. De resultant op een punt dat geen knoop is, komt op de dichtstbijzijnde knoop
  terecht; het paneel moet die knoop noemen. De getallen blijven om het gekozen punt.
- De groep moet door de gebruiker in de boom aangeklikt worden; de API kan dat niet.
- Wordt een veld dat al getoond is overschreven, dan blijven legenda en pijlschaal oud: de pijl was daardoor veel te
  lang, ook na opnieuw aanklikken. Een nieuwe groep had een kloppende legenda en een redelijke pijl. Schaal bij een
  tweede selectie is dus nog een open punt.
- `set_variable` overschrijft bestaande velden. *external force* bestaat al bij CalculiX en *reaction moment* bij
  schalen en balken; dan weigeren we en blijft de weergave in het paneel. Velden komen ook in het bestand als de
  gebruiker opslaat.
- Getallen staan niet bij de pijl. Klikken op een knoop toont de waarde; verder alleen in het paneel.

### 6.4 Bestanden

```
Scripts/
  MecwayFreebody.py    ingang, IronPython
  fb_core.py           snedeknopen, meetkunde, resultanten, assen; Python 2/3, zonder Mecway
  fb_mecway.py         lezen uit mw/solution en .liml
  fb_aster.py          route C: vervolgrun schrijven, Code-Aster starten, resultaat lezen
  fb_gui.py            paneel en tekening
tests/                 draait zonder Mecway op fb_core; apart de Mecway-proeven
docs/                  gebruik, Engels en Nederlands
```

### 6.5 Fasen

1. **Bridge en proeven**: base bewaren als keuze per run, manifest en opruimregel in MecwayAsterBridge. Daarna op een echte bridge-run
   met eigen model: celnamen na `CREA_MAILLAGE` in de vervolgrun, `REAC_NODA` zonder expliciete `EXCIT` op een niet-lineair
   resultaat met volgdruk en `FONC_MULT`, pijlen bij Code-Aster-resultaten, schaal van pijlen bij een tweede selectie.
2. **Kern met Code-Aster**: snedeknopen, meetkunde, vervolgrun, som, evenwichtscontrole, tabel. Tests tegen statica, lineair en
   niet-lineair, volume-elementen eerst.
3. **Paneel** met tekening, sleepbaar punt, assen, stapkeuze en vectoren in Mecway.
4. **Breder**: schalen, balken, gemengde modellen, en wat op de blokkeerlijst staat waar dat zinvol is.

Op verzoek: 3D-beeld in het paneel, M4L voor Mecway's solver en CalculiX, modes, krachtlijn over een reeks sneden, koppeling met de
schuifmiddelpuntberekening. Route A wordt gedocumenteerd als recept (`e7_recipe.py`). Route D vervalt.

### 6.6 Testen

- **Zonder Mecway**, op `fb_core`: som van vormfuncties, volume, snedeknopen, groepen, momentverschuiving, assen.
- **Met Code-Aster**, tegen statica en altijd met twee sneden, via de echte bridge: de gevallen uit E7, `LINE_QUAD` en COQUE_3D,
  offset-schaal en line3, schaal + volume, thermisch. Oplegging, RBE2/RBE3, contact en veer op een snedeknoop. Een model met
  configuraties. Vervolgrun naast een bridge-run. De negatieve controles uit E7 als vaste test.
- **Moet weigeren**: gewijzigd model, andere Code-Aster-versie, ontbrekende base, modaal resultaat.
- **Weergave met Mecway**: pijlen op Code-Aster-resultaten, veld dat al bestaat, decimale komma.
- **Overig**: decimale komma in CSV en klembord, syntaxcontrole in Mecway's eigen IronPython.
- Alleen zelfgemaakte modellen in `tests/`.

## 7. Licenties en juridisch

Dit is een praktische inschatting en geen juridisch advies.

- **Eigen code**: alles zelf geschreven, of uit MecwaySectionProps en MecwayAsterBridge (eigen, MPL-2.0).
- **Geen GPL- of AGPL-code** in dit project. CalculiX, Code-Aster, PrePoMax en OpenAEC FEM dienen alleen als
  concept of los draaiend programma. Eigen gebruik in het bedrijf is onder die licenties sowieso toegestaan;
  het gaat erom dat een latere publicatie onder MPL-2.0 schoon blijft.
- **Mecway**: de EULA in de handleiding verbiedt reverse engineering en herdistributie van de meegeleverde Intel MKL
  en noemt geen beperking op scripts, automatisering of een tweede instantie. Dit project gebruikt alleen de openbare
  script-API en het eigen `.liml`-formaat. Geen tekst uit handleiding of
  API-referentie in de repo. Mecway blijft een commerciële eigen licentie van de gebruiker.
- **Closed-source pakketten**: alleen concepten, geen teksten, schermen of code.
- **Patent**: US 6,901,809 en US 7,516,673 (Battelle) gaan over het omzetten van knoopkrachten naar **structurele
  spanning** voor vermoeiing. Dit project berekent resultanten, een klassieke sommatie, en geen structurele spanning.
  Google Patents geeft beide als verlopen (2022); dat is Google's eigen berekening en alleen voor de VS. Een andere
  jurisdictie is **niet nagezocht**. Komt er later een vermoeiingsfunctie op deze manier, dan eerst opnieuw kijken.
- **Licentie van deze repo**: nog te kiezen. Voorstel MPL-2.0, gelijk aan de zustermappen. Keuze voor de gebruiker.

## 8. Risico's en open punten

| Punt | Status |
|---|---|
| Schijfruimte: 125-450 MB base per bewaarde run | Opruimregel in de bridge; instelbaar |
| Base gebonden aan de Code-Aster-versie | Manifest vergelijkt de versie en weigert |
| Niet-convergerende run: rc 0 met alleen een alarm, base bruikbaar tot de laatste stap | Bridge gooit de base weg als de `.mess` fouten meldt; of zo'n run zijn base moet houden, is nog te beslissen |
| `set_variable` op een oplossing die de bridge heeft teruggeschreven | Fase 3 |
| Selecties die de bridge anders opbouwt: offset-schalen, flexibele verbindingen, POI1 | Eerst geblokkeerd |
| Fictieve boorstijfheid bij geknikte en gebogen schalen | Geldt voor alle routes; waarschuwing in het paneel; advies voor `COEF_RIGI_DRZ` nog te bepalen |
| Afhankelijkheid van een wijziging in MecwayAsterBridge | Klein, maar in een andere repo; afstemmen met de gebruiker |

## 9. Keuzes van de gebruiker

Vastgelegd op 7 november 2026:

| Keuze | Besluit |
|---|---|
| Hoofddoel | De tools ontsluiten primair Code-Aster, met Mecway als voorkant. Extra Mecway-functionaliteit is bijvangst |
| Goedkeuring van het plan | Nog open |
| Selecteren | Elementen; het script vindt de sneden |
| Assen in de tabel | Hoofdassen van de doorsnede; globale assen met een schakelaar |
| Weergave | Paneel plus pijlen in Mecway's oplossingsbeeld. Wens voor later: 3D-beeld in het paneel met draaibare doorsnede en pijlen |
| Licentie | MPL-2.0 |
| Literatuur | Auteursnamen in citaties blijven staan |
| Rekenroute Code-Aster | Base bewaren en korte vervolgrun (route C) |

## 10. Bronnen

Open source en documentatie:
- [FreeCAD: FEM ConstraintSectionPrint](https://wiki.freecad.org/FEM_ConstraintSectionPrint)
- [FreeCAD tracker 2935, section forces](https://tracker.freecad.org/view.php?id=2935)
- [CalculiX forum: total force at a section](https://calculix.discourse.group/t/how-to-get-the-total-force-carried-at-a-section/368)
- [PrePoMax forum: free body diagram](https://prepomax.discourse.group/t/how-can-i-obtain-a-free-body-diagram/3477)
- [PrePoMax forum: forces in a bolt](https://prepomax.discourse.group/t/forces-in-a-bolt/2956)
- [Code-Aster: POST_RELEVE_T, keuze van het object](https://docaster-en-codeaster-doc-4113bb35b8213385c636b94f1536856d7f617.gitlab.io/manuals/man_u/u4/u4.81.21/Choix_de_l_objet_du_post-traitement.html)
- [pyNastran: grid point forces](https://pynastran-git.readthedocs.io/en/latest/reference/op2/tables/pyNastran.op2.tables.ogf_gridPointForces.html)
- [OpenAEC Foundation op GitHub](https://github.com/OpenAEC-Foundation), [Open FEM Studio Mechanics](https://github.com/OpenAEC-Foundation/open-fem-studio-mechanics), [OSArch over OpenAEC](https://osarch.org/2026/06/05/openaec-open-source-aec-ecosystem-roadmap/)
- [sectionproperties](https://sectionproperties.readthedocs.io/en/latest/)
- [MYSTRAN op GitHub](https://github.com/MYSTRANsolver/MYSTRAN)

Mecway:
- [Forum: Cross section forces](https://mecway.com/forum/discussion/comment/4316)
- [Forum: Internal forces calculations](https://mecway.com/forum/discussion/comment/3899)
- [Forum: shell element output](https://mecway.com/forum/discussion/comment/1676)
- [Forum: Shear and Moment Calculation](https://mecway.com/forum/discussion/comment/4091)

Concepten:
- [Abaqus: free body cuts](https://ceae-server.colorado.edu/v2016/books/usi/pt06ch67s01.html) (alleen via zoekresultaat gelezen; de MIT-kopie is offline)
- [Abaqus: Free Body toolset](https://abaqus-docs.mit.edu/2017/English/SIMACAECAERefMap/simacae-m-Fbd-sb.htm)
- [Altair: Free Body Diagram](https://help.altair.com/hwdesktop/hwx/topics/panels/fbd_r.htm)
- [Altair: free body section plot](https://help.altair.com/hwdesktop/hwx/topics/pre_processing/aerospace/free_body_section_plot_create.htm)
- [SAP2000: section cuts](https://docs.csiamerica.com/help-files/sap/Menus/Draw/Draw_Section_Cuts.htm)
- [ANSYS Innovation Space: FSUM](https://innovationspace.ansys.com/forum/?p=320494)

Literatuur:
- [Hughes e.a. (2000)](https://portal.mardi4nfdi.de/wiki/Publication:1592310)
- [Carey, Chow & Seager (1985)](https://portal.mardi4nfdi.de/wiki/Publication:798066)
- [Chow e.a. (1994)](https://portal.mardi4nfdi.de/wiki/Publication:1326417)
- [Mizukami (1986)](https://portal.mardi4nfdi.de/wiki/Publication:1072881)
- [Zhong, Gurnis & Hulbert (1993)](https://deepblue.lib.umich.edu/items/4922c002-c8ad-4252-b3b4-95fe83b721e8)
- [Dong (2001)](https://manuscript.isc.ac/Inventory/10/1160689.htm)
- [Zienkiewicz & Zhu (1992)](https://data.zhenzhi.com/details/1/1004595135)
- [US 6,901,809](https://patents.google.com/patent/US6901809B2/en), [US 7,516,673](https://patents.google.com/patent/US7516673B2/en)

## 11. Review door Fable

Eerste review, op de versie met Mecway's solver als hoofdroute. Oordeel: doorgaan met wijzigingen. De acht vereiste wijzigingen zijn verwerkt:

| Bevinding | Verwerking |
|---|---|
| Snedeknopen knoopgebaseerd, vlakken alleen voor meetkunde | §6.1 |
| Deelmodel: wel lasten en temperatuur, geen opleggingen, contact of veren | §6.2 |
| Lezen uit de modelkopie in `<solution>`; opslaan alleen met toestemming | §6.2 |
| Eén motor, M3 pas later als benadering | §1, §6.2, §6.5 |
| Snede definiëren voor schalen en balken | §6.1 |
| `e2` opnieuw draaien met log; ontbrekende rotatie is een fout | §5, §6.2 |
| Fase 1 met proef tweede instantie en `new_element` | §6.5; `new_element` en naast elkaar draaien zijn al deels beproefd |
| Fouten per component rapporteren | §1, §5 |

Eigen controle van de bevindingen: de componenten kloppen met de meetdata, maar de bewering dat vooral dwarskracht
fout is, geldt alleen voor hex20; bij tet10 is ook N 29% af. De auteursvolgorde is via Crossref bevestigd. De EULA is
nagelezen. De verklaring voor de M3-fout is overgenomen als waarschijnlijk, niet als bewezen. De metingen op de overige
elementen (§5) kwamen na de review en zijn zelf steekproefsgewijs nagerekend; hun meetplan had een eigen Fable-review.

Tweede review, op de versie met Code-Aster als hoofdroute. Oordeel: doorgaan met wijzigingen. De zeven vereiste wijzigingen zijn
verwerkt:

| Bevinding | Verwerking |
|---|---|
| Conventie voor opleggingen, koppelingen, veren en knooplasten op snedeknopen | §5, §6.2 |
| Manifest per run en base als keuze, naar fase 1 | §6.2, §6.5 |
| Proeven: celnamen na `CREA_MAILLAGE`, `REAC_NODA` zonder `EXCIT` | §6.5, §8 |
| Blokkeerlijst | §6.2 |
| M4L en route D uit het hoofdplan | §6.2, §6.5 |
| Lokale assen voor schalen en balken, normaalmoment onbetrouwbaar | §6.1 |
| Testplan aanvullen | §6.6 |

Eigen controle aan de bron: `M<eid>`/`H<eid>`, `K<n>` zonder ouderkoppeling, het ontbreken van `R base`, standaard `memory_limit`
2048 en de 80% bij `l_supp` kloppen. De reviewer rekende de ruwe resultaten na (1e-9 N restkracht). Het moment om de DKT-normaal
als onbetrouwbaar merken, ook op vlakke schalen, is overgenomen als voorzichtige keuze; het is alleen op de tip en op geknikte en
gebogen schalen gemeten.
