# Concept Part Report

Status: layout study, NOT released for manufacturing.

Assembly: 220 x 220 x 216 mm. Units: mm; Blender scale_length = 0.001.

Carrier plates: 2 mm; grooves: 2.4 mm; nominal vertical play: 0.4 mm.

Every modelled part fits a 226 mm bounding cube. This is not a slicer or bed-contact check.

Original Blender Scene is preserved. BATMAN - assembly is dimensionally authoritative; BATMAN - open and BATMAN - levels are inspection scenes.

## Unresolved Before Printing

- C1 D12 x 22 mm and C2 6 x 4 x 7 mm are placeholders, not measured values. Confirm quantity, sizes and terminal clearance before choosing lower-level height.
- Module envelopes are simplified; mounting heights and connectors need physical measurements.
- Adjustable supports need final retaining clips/strap slots and fastener attachment. They are not complete holders yet.
- Rear terminal/fuse/DS18B20 openings, OLED bracket and USB alignment remain to be measured. Rear panel is an interface blank.
- Corner posts currently illustrate pilot holes, not final heat-set insert pockets or validated screw depths.
- Frame print orientation, support-free geometry and >=70% bed contact are not verified. Slice and redesign joints before STL release.
- No detailed harness routing or thermal verification. Preserve >=20 mm separation of signal and power harnesses, short ADS cables and ESP antenna clearance.
- The capacitor buffer must remain next to LOAD terminals; the nominal placeholders do not approve long leads.
- Rear carriers require removal of front carriers in the same lane; disconnect harnesses first.
- Final linked per-subassembly files and STL exports are intentionally withheld pending these fit checks.

## Part Geometry

Volume is model geometry only, not filament consumption. Print orientation, bed contact and slicer time: TBD for all parts.

| Part | Bounding box, mm | Volume, cm3 | Closed manifold |
|---|---|---:|---|
| base | 220.0 x 220.0 x 3.0 | 145.091 | True |
| corner post | 9.0 x 9.0 x 210.0 | 14.12 | True |
| corner post.001 | 9.0 x 9.0 x 210.0 | 14.12 | True |
| corner post.002 | 9.0 x 9.0 x 210.0 | 14.12 | True |
| corner post.003 | 9.0 x 9.0 x 210.0 | 14.12 | True |
| L1 logic frame grooved frame | 211.0 x 212.0 x 8.4 | 40.418 | True |
| L1 logic frame removable retainer | 211.0 x 4.0 x 8.4 | 6.779 | True |
| L2 power frame grooved frame | 211.0 x 212.0 x 20.0 | 40.418 | True |
| L2 power frame removable retainer | 211.0 x 4.0 x 8.4 | 6.779 | True |
| L1 carrier A plate | 92.0 x 102.0 x 2.0 | 18.696 | True |
| L1 carrier A pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| A M3 spacer | 8.0 x 8.0 x 5.0 | 0.205 | True |
| A M3 spacer.001 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| A M3 spacer.002 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| A M3 spacer.003 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| L1 carrier B plate | 92.0 x 94.0 x 2.0 | 17.224 | True |
| L1 carrier B pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| B M3 spacer | 8.0 x 8.0 x 5.0 | 0.205 | True |
| B M3 spacer.001 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| B M3 spacer.002 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| B M3 spacer.003 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| L1 carrier C plate | 92.0 x 62.0 x 2.0 | 11.336 | True |
| L1 carrier C pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| C M3 spacer | 8.0 x 8.0 x 5.0 | 0.205 | True |
| C M3 spacer.001 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| C M3 spacer.002 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| C M3 spacer.003 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| L1 carrier D plate | 92.0 x 62.0 x 2.0 | 11.336 | True |
| L1 carrier D pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| D M3 spacer | 8.0 x 8.0 x 5.0 | 0.205 | True |
| D M3 spacer.001 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| D M3 spacer.002 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| D M3 spacer.003 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| L1 carrier ADS pair plate | 92.0 x 32.0 x 2.0 | 5.888 | True |
| L1 carrier ADS pair pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| ADS 0x48 edge support | 28.0 x 3.0 x 5.0 | 0.42 | True |
| ADS 0x48 edge support.001 | 28.0 x 3.0 x 5.0 | 0.42 | True |
| ADS 0x48 adjustable edge saddle | 32.0 x 3.0 x 5.0 | 0.48 | True |
| ADS 0x48 adjustable edge saddle.001 | 32.0 x 3.0 x 5.0 | 0.48 | True |
| ADS 0x49 edge support | 28.0 x 3.0 x 5.0 | 0.42 | True |
| ADS 0x49 edge support.001 | 28.0 x 3.0 x 5.0 | 0.42 | True |
| ADS 0x49 adjustable edge saddle | 32.0 x 3.0 x 5.0 | 0.48 | True |
| ADS 0x49 adjustable edge saddle.001 | 32.0 x 3.0 x 5.0 | 0.48 | True |
| L2 carrier DPS plate | 92.0 x 104.0 x 2.0 | 19.064 | True |
| L2 carrier DPS pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| DPS M3 spacer | 8.0 x 8.0 x 5.0 | 0.205 | True |
| DPS M3 spacer.001 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| DPS M3 spacer.002 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| DPS M3 spacer.003 | 8.0 x 8.0 x 5.0 | 0.205 | True |
| L2 carrier relay supply plate | 92.0 x 93.0 x 2.0 | 17.112 | True |
| L2 carrier relay supply pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| module edge support | 50.0 x 3.0 x 5.0 | 0.75 | True |
| module edge support.001 | 50.0 x 3.0 x 5.0 | 0.75 | True |
| adjustable module edge saddle | 54.0 x 3.0 x 5.0 | 0.81 | True |
| adjustable module edge saddle.001 | 54.0 x 3.0 x 5.0 | 0.81 | True |
| module edge support.002 | 44.0 x 3.0 x 5.0 | 0.66 | True |
| module edge support.003 | 44.0 x 3.0 x 5.0 | 0.66 | True |
| adjustable module edge saddle.002 | 48.0 x 3.0 x 5.0 | 0.72 | True |
| adjustable module edge saddle.003 | 48.0 x 3.0 x 5.0 | 0.72 | True |
| L2 carrier branch 1 plate | 92.0 x 58.0 x 2.0 | 10.672 | True |
| L2 carrier branch 1 pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| module edge support.004 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.005 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.001 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.006 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.007 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.002 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.003 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.008 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.009 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.004 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.005 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| L2 carrier branch 2 plate | 92.0 x 58.0 x 2.0 | 10.672 | True |
| L2 carrier branch 2 pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| module edge support.010 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.011 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.006 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.007 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.012 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.013 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.008 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.009 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.014 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.015 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.010 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.011 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| L2 carrier branch 3 plate | 92.0 x 58.0 x 2.0 | 10.672 | True |
| L2 carrier branch 3 pull lip | 24.0 x 3.0 x 7.0 | 0.504 | True |
| module edge support.016 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.017 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.012 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.013 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.018 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.019 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.014 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.015 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| module edge support.020 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| module edge support.021 | 3.0 x 8.0 x 5.0 | 0.12 | True |
| provisional adjustable saddle.016 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| provisional adjustable saddle.017 | 3.0 x 23.0 x 5.0 | 0.345 | True |
| C1 C2 adjustable cradle | 62.0 x 32.0 x 3.0 | 5.585 | True |
| capacitor strap guide | 3.0 x 26.0 x 4.0 | 0.312 | True |
| capacitor strap guide.001 | 3.0 x 26.0 x 4.0 | 0.312 | True |
| wall left | 3.0 x 220.0 x 210.0 | 130.489 | True |
| wall right | 3.0 x 220.0 x 210.0 | 135.437 | True |
| panel back - interface blanks | 214.0 x 3.0 x 210.0 | 134.657 | True |
| panel front | 214.0 x 3.0 x 210.0 | 130.179 | True |
| lid ventilated | 220.0 x 220.0 x 3.0 | 100.163 | True |
