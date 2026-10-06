# ELDIS · Radar Coverage

Desktopová a webová aplikace pro terénní analýzu geometrického radarového krytí.
RL-2000 a PAR-NG s integrovanými vyzařovacími diagramy. PAR-NG: azimut osy ±20°,
dosah 40 km. Parametry a výpočetní model odpovídají původní desktopové verzi.

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

Jde o geometrickou viditelnost nad efektivní kulovou Zemí, nikoli simulaci Pd/Pfa.
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
