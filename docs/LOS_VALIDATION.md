# LOS VALIDACE 01 — nezávislá geometrická kontrola

Tato záložka je dostupná v hlavní liště jako **✓ TEST / VALIDACE**.

## Použití
1. Načti CDPROJ s DEM nebo vypočítej krytí.
2. Otevři **TEST**; mapa přejde do režimu výběru kontrolního bodu.
3. Klikni do mapy. V pravém kontextovém panelu se zobrazí kontrolní
   radiál, vzdálenost, azimut, vybraná výška v ft AMSL/AGL a profil.
4. Volitelně změň index azimutu/vzdálenosti. Exportuj profil do CSV.

## Metoda

Hlavní engine vypočítává horizont kumulativním maximem úhlů k DEM
(`maximum.accumulate`) a z něj odvozuje spodní mez krytí.

Validátor používá **jinou rovnicovou konstrukci**: radar a cíl mají
polohové vektory na efektivní kulové Zemi o poloměru
`R_eff = k · 6,371,008.8 m`; jejich spojnice je tětiva. Na každém
polárním vzorku se vypočítá vzdálenost průsečíku tětivy s radiálním
paprskem a z ní výška LOS nad DEM.

Pro úhel `theta = s/R_eff`, `Theta = D/R_eff`, `r0 = R_eff + hA`
a `rt = R_eff + hT`:

```
r_LOS(s) = r0 · rt · sin(Theta) /
           [rt · sin(Theta - theta) + r0 · sin(theta)]
h_LOS(s) = r_LOS(s) - R_eff
C(s)     = h_LOS(s) - h_DEM(s)
```

**Minimální clearance** je minimum hodnot `C(s)`. Kontrola zvlášť
posuzuje rozsah min/max elevace a sektor PAR. Geometrický výsledek
je potom porovnán se spodní/horní hranicí hlavního enginu; výsledný
RF status je zobrazen odděleně. Tím se neoznačuje slabé SNR za chybu
geometrického LOS.

## Omezení

- Oba algoritmy vycházejí ze **stejné již vzorkované mřížky DEM**;
  nezávislost je matematická, nikoliv nezávislý zdroj terénních dat.
- Ručně vložené překážky může hlavní engine započítat, ale
  nezávislá DEM-only geometrie je **nezahrnuje**. Projekt s ručními
  překážkami proto dostane stav `OBSTACLES_NOT_CHECKED` místo
  zavádějícího `MISMATCH`.
- Chybějící výška terénu na trase znamená `UNKNOWN`, nikoliv PASS.
- Výsledek nepokrývá difrakci, Fresnelovu zónu, meteorologii,
  absolutní RF budget, Pd a polohové chyby DEM.
- Kliknutý bod je pro porovnání přiřazen nejbližšímu výpočetnímu
  radiálu/vzdálenosti; přesné souřadnice nejsou nově vzorkovány z DEM.
- Samotný průběh je ukázkou reprodukovatelnosti výpočtu, ne
  certifikací provozního radarového krytí.

## Budoucí VALIDACE 02

Nezávislý geodetický profil stažený z jiného DEM, kontrola lokálního
nadvzorkování horizontu, porovnání vlivu k-factoru, test konvergence
pro 500/250/100 m a mapová vrstva odchylek. Tyto kroky **nejsou**
součástí první implementace.
