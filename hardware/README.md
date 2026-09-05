# hardware — схема й плати

Правила й склад — [docs/plan.md](../docs/plan.md) розділ 2; джерело істини для з'єднань — [docs/connections.md](../docs/connections.md). KiCad 10.

**Усе разом:** `.\build.ps1` (схема → ERC → нетліст → PDF → DRC плат), `.\build.ps1 -pcb` — ще й перегенерувати каркаси плат (затирає розведення!).

| Тека | Що |
|---|---|
| `schematic/` | `gen.py` → `batman.kicad_pro`, корінь + power/charge/sense/logic, `lib/batman.kicad_sym` (модулі) |
| `bom/bom.md` | комплектувальний список, генерується разом із схемою |
| `pcb/` | `gen_pcb.py` (пітон з KiCad) → `plate_A.kicad_pcb`, `plate_B.kicad_pcb`, `batman.pretty/` (гніздо DevKitC); `parts.json` — вхід зі схеми |

## schematic/

Схема **генерується** з `gen.py` (Python 3, без залежностей; читає стандартні символи з інсталяції KiCad 10):

```powershell
cd hardware/schematic
python gen.py                                  # batman.kicad_sch + power/charge/sense/logic.kicad_sch + lib/batman.kicad_sym
& "$env:LOCALAPPDATA\Programs\KiCad\10.0\bin\kicad-cli.exe" sch erc --severity-all -o erc.rpt batman.kicad_sch
& "$env:LOCALAPPDATA\Programs\KiCad\10.0\bin\kicad-cli.exe" sch export pdf -o batman.pdf batman.kicad_sch
```

Аркуші: **power** (гілки, ключі mSW, діоди mDIO, шина — плата B), **charge** (DPS5015, mDIO3, реле K1/K2), **sense** (RC-фільтри, дільники, ADS1115, SENS_PWR — плата A), **logic** (DevKitC, NPN-ключі реле, роз'єми, живлення, DS18B20 — плата A).

Усі з'єднання — глобальними мітками: вузли (`B1`, `B2`, `LOAD+`, `CHG`, `GND`, `+5V`, `+3V3`, `+3V3_SENS`, `VIN_DC`) і номери проводів `P##` для двоточкових силових з'єднань з connections.md. Модулі (mACS, mSW, mDIO, mDPS, mREL2, mDC5, mOLED) — власні символи в `lib/batman.kicad_sym`, `on_board = no` (вони не на платі, підключаються дюпонами/дротами до гребінок J* і клемників X*).

Змінювати з'єднання — у `gen.py` (і в connections.md), потім перегенерувати; правки вручну в KiCad затираються. Коли схема стабілізується перед розведенням плати A — генератор можна «відпустити» і далі вести файли в KiCad.

## pcb/

Плата A (logic, 100 × 80) і плата B (bus, 46 × 30) — однобічний ЛУТ за правилами plan.md 2.2. `gen_pcb.py` бере `parts.json` + `schematic/batman.net` і робить: один мідний шар F.Cu (друкувати **дзеркально**), правила (доріжка ≥ 0,7, зазор ≥ 0,5, клас `power` 3 мм для B1/B2/LOAD+/GND/VIN_DC/+5V), пади й отвори під компонент (0,8/2,0 — R, C, гребінки, TO-92 з розведеними ногами 2,54; 1,1/2,4 — діоди; 1,5/3,5 — клемники), контур, отвори M3, розміщення за `LAYOUT_A/B` (рядки/колонки з автовідступами за габаритами), ланцюги на падах, заливка GND. Трасування — руками в pcbnew.

Гніздо DevKitC (`batman.pretty/ESP32_DevKitC_38_Socket`) — два ряди 1×19 на відстані **25,4 мм** (плата 28 мм шириною); у вузьких клонів 25,4 мм ширини ряди на 22,86 — перевірити на своєму екземплярі й при потребі змінити `DEVKIT_ROW_PITCH`.

Коли розведено: `kicad-cli pcb export pdf --layers F.Cu,Edge_Cuts --mirror -o plate_A_mirror.pdf plate_A.kicad_pcb` (масштаб 1:1) і `kicad-cli pcb export drill` для списку свердлінь.
