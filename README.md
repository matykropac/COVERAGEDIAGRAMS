# ELDIS · Radar Coverage

Desktopová a webová aplikace pro terénní analýzu geometrického radarového krytí.
PSR (RL-2000), PAR (PAR-NG) a obecný SSR model s integrovanými diagramy. PAR: azimut osy ±20°,
dosah 40 km. Web a desktop sdílejí stejné modely a předvolby.

## Nasazení přes web (bez Gitu v počítači)

1. Rozbal `COVERAGEDIAGRAMS_Streamlit.zip`.
2. V repozitáři `matykropac/COVERAGEDIAGRAMS` zvol **Add file → Upload files**.
3. Nahraj **obsah** rozbalené složky, ne samotný ZIP ani nadřazenou složku.
   V kořeni repozitáře musí být `streamlit_app.py`, `radar_core.py`,
   `web_support.py` a `requirements.txt`. Přidej také složku `.streamlit`.
4. Potvrď **Commit changes**. Původní `COVERAGEDIAGRAMS.py` zůstává desktopovou verzí.
5. Na https://share.streamlit.io zvol **Create app → Yup, I have an app**.
6. Vyplň:
   - Repository: `matykropac/COVERAGEDIAGRAMS`
   - Branch: `main`
   - Main file path: `streamlit_app.py`
7. V **Advanced settings** zvol **Python 3.12**. Klikni **Deploy**.

Oficiální postup: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## Lokální spuštění webové verze

```sh
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Ověřeno s Pythonem 3.12; requirements obsahují konkrétní testované verze.
Webová verze nevyžaduje Tkinter ani keyring. Pro desktopovou verzi je navíc
potřeba systémový Tkinter a `python -m pip install customtkinter keyring`.

## Použití

- **NASTAVENÍ:** radar, souřadnice, síť, elevace, cíl a zdroj terénu. Volba
  radaru automaticky zvolí vestavěný diagram; žádný soubor diagramu se nenahrává.
- **Syntetické demo** ověřuje ovládání, nepředstavuje skutečný terén.
- **Nahrát DEM:** jeden georeferencovaný GeoTIFF/DTED/SRTM do 200 MB.
- **OpenTopography:** vlastní API klíč v heslovém poli. Klíč zůstává v relaci,
  nepatří do repozitáře. Stažené DEM se cachují na serveru v
  `~/.cache/RadarCoverage/dem` (na Windows pod LOCALAPPDATA).
  Serverová cache nemusí přežít restart/nové nasazení. Může ji sdílet více relací.
- **MAPA / ANALÝZA:** volná navigace a fullscreen, OSM/OpenTopoMap/Esri imagery,
  hladiny a samostatné opacity, náhled pod kurzorem, kliknutí a radiální profil.
  Hover používá přibližnou sférickou vzdálenost pro výběr nejbližšího vzorku;
  kliknutí používá přesnou geodetickou transformaci WGS84. Hodnoty jsou ze
  vzorkované sítě. Hover stav krytí se vztahuje k nastavenému cíli; detail po
  kliknutí uvádí kryté vybrané hladiny. Síť webové verze má limit 250 000 bodů.
- **DATA / EXPORTY:** metadata aktuálního výsledku, RAW profil, celý výpočet NPZ,
  vektorový GPKG (polygony a hranice), GeoTIFF, CSV, JSON a PNG 300/600 DPI.
  PNG je vědecký graf bez online podkladu. GPKG obsahuje křivky ze skutečné
  polární sítě, bez rastrového omezení rozlišení a bez kosmetického vyhlazování.
- Výsledky jsou oddělené pro každou relaci. Změna parametrů neprovádí nový
  výpočet sama; aplikace upozorní, že zobrazuje předchozí úspěšný výsledek.
  Po obnově/ztrátě relace je nutné znovu počítat; potřebné výstupy si stáhni.

## Fyzikální meze modelu

Jde o geometrickou viditelnost nad efektivní kulovou Zemí; SSR navíc používá
orientační výkonovou bilanci. Nejde o simulaci Pd/Pfa.
PAR-NG využívá ideální azimutální rozmítání a vertikální řez v ose diagramu;
nepočítá elevační skenování, čas osvitu ani ztráty při vychýlení svazku.
Výšková reference je datum zdrojového DEM, bez převodu geoidu.
Vyšší DPI nemění přesnost DEM ani výpočetní sítě.

## Údržba a ověření

`radar_core.py` je automaticky vytažený výpočetní a exportní kód z desktopového
souboru. Po změně desktopového jádra ho obnov:

```sh
python tools/extract_core.py
python -m pip install pytest
python -m pytest -q
python COVERAGEDIAGRAMS.py --self-test
```

Poslední příkaz potřebuje desktopové závislosti. Testy webu ověřují shodu
extrahovaných funkcí s originálem, headless import, PAR přes sever, neznámá data,
exporty a Streamlit ovládání. Reálné stažení DEM vyžaduje vlastní API klíč;
externí mapové dlaždice a jejich dostupnost nejsou součástí automatických testů.

## PSR / PAR / SSR

Výběr **PSR / PAR / SSR** je společný pro desktop i web:

| Volba | Vestavěný model | Dosah |
|---|---|---|
| PSR | RL-2000, původní LOW / HIGH | 60, 80 nebo 100 NM (výchozí 100 NM) |
| PAR | PAR-NG, původní 3D diagram | 40 km, sektor ±20° |
| SSR | Obecný orientační model | pevně 256 NM = 474,112 km, 360° |

1 NM = 1,852 km. Předvolba určuje povrchový výřez mapy i maximální
referenční **šikmý** dosah; tyto vzdálenosti nejsou totožné. U PSR je
referenční dosah omezen původním normalizovaným anténním diagramem.
Minimální elevace a tilt mají výchozí hodnotu −1,0°. Web má výchozí radiální
krok 500 m pro PSR, 250 m pro PAR a 1000 m pro SSR, aby se běžný výpočet
vešel do limitu 250 000 bodů. Jemnější krok lze zvolit s odpovídajícím
krokem azimutu. Pro SSR nabízí OpenTopography 90m modely COP90 (výchozí)
a SRTMGL3, protože oblast 256 NM překračuje limit 30m datasetů. Výběr radaru sám nespouští výpočet; klikni na Vypočítat krytí.

### Obecný SSR model a Blakeův diagram

SSR používá **dva jednosměrné Friisovy spoje**, nikoli monostatickou
radarovou rovnici pro odraz od RCS. Pro každou elevaci se samostatně určí
dosah dotazu (1030 MHz) a odpovědi (1090 MHz):

```
R_link [m] = wavelength / (4*pi) * 10^((P_tx + G_ground + G_air - L - M - P_min)/20)
R_max(elevation) = min(R_uplink, R_downlink, 256 NM)
```

Výkony a prahy jsou v dBm, zisky v dBi, ztráty a rezerva v dB. `G_ground`
zahrnuje následující normalizovaný idealizovaný vertikální diagram:
`G_rel(e) = max(-80, -12*((e - tilt - 8)/20)^2)` dB.

**Všechny číselné parametry níže jsou ilustrační předpoklady tohoto modelu,
nikoli požadavky ICAO ani specifikace MSSR-1 nebo jiného výrobku.**

| Parametr | Předpoklad |
|---|---|
| Výkon dotazovače / transpondéru | 60 / 51 dBm (1 kW / přibližně 126 W) |
| Špičkový zisk pozemní / palubní antény | 27 / 0 dBi |
| Práh příjmu transpondéru / pozemního přijímače | −74 / −82 dBm |
| Ztráty v každém spoji | 3 dB |
| Rezerva v každém spoji | 6 dB |
| Maximum vertikálního diagramu před tiltem | 8° |
| Vertikální šířka při −3 dB | 20° |

Anténní obálka se převádí na vzdálenost/výšku s efektivním poloměrem Země
(výchozí k = 4/3). Náhled **Blakeova diagramu** přidává čáry konstantní
počáteční elevace; náhled bez terénu před výpočtem používá orientační výšku
stanoviště 200 m AMSL. Výsledná mapa a radiální profil používají skutečné
vzorky DEM, výšku antény a terénní horizont. Chybějící DEM zůstává neznámé,
nikoli automaticky viditelné. 256 NM je horní limit, nikoli záruka krytí.

Model nepočítá multipath, difrakci, proměnlivou atmosféru, rušení/FRUIT,
garbling, SLS, palubní stínění ani pravděpodobnost detekce. Nenahrazuje
validaci konkrétního radaru a stanoviště. Parametry a omezení jsou uloženy
v metadatech JSON, NPZ a vektorového GPKG.

Metodické zdroje (číselné předpoklady výše jsou naše volba):
- [MathWorks: Blake chart – range/angle/height geometry](https://www.mathworks.com/help/radar/ref/blakechart.html)
- [MSSR Coverage—Determinant Factors: uplink/downlink and antenna coverage](https://www.mdpi.com/1424-8220/21/12/4198)

Ověření změny: `python -m pytest -q` (navíc nainstaluj pytest) a
`python COVERAGEDIAGRAMS.py --self-test` (vyžaduje desktopové závislosti).
