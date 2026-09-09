from pathlib import Path
import json
import uuid

from circuit import circuit, validate


ROOT = Path(__file__).resolve().parent / "batman"
SHEETS = ["power", "charge", "sense", "logic", "supply3", "supply5"]


def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "batman/" + name))


def quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def effects(size=1.0, extra=""):
    return f"(effects (font (size {size} {size})) {extra})"


def line(points):
    coordinates = " ".join(f"(xy {x} {y})" for x, y in points)
    return f"(polyline (pts {coordinates}) (stroke (width 0.254) (type default)) (fill (type none)))"


def geometry(part):
    if part.kind == "flag":
        return [("1", "pwr", part.pins[0][2], "power_out", 0, 0, 90)], 5.08, 5.08
    if len(part.pins) == 2 and part.kind in ["R", "C", "CP", "C_bus", "D", "TVS", "diode_module", "fuse", "switch"]:
        return [(*part.pins[0], -7.62, 0, 0), (*part.pins[1], 7.62, 0, 180)], 2.54, 2.54
    if part.kind in ["NPN", "PNP"]:
        return [(*part.pins[0], 7.62, 5.08, 180), (*part.pins[1], -7.62, 0, 0),
                (*part.pins[2], 7.62, -5.08, 180)], 3.81, 7.62
    count = (len(part.pins) + 1) // 2
    half_height = max(5.08, (count + 1) * 1.27)
    output = []
    for index, pin in enumerate(part.pins):
        right = index >= count
        row = index - count if right else index
        output.append((*pin, 22.86 if right else -22.86, (count - 1) * 1.27 - row * 2.54, 180 if right else 0))
    return output, 17.78, half_height


def symbol(part, embedded=False):
    pins, half_width, half_height = geometry(part)
    name = part.ref.replace("#", "_")
    graphics = []
    if part.kind == "R":
        graphics.append('(rectangle (start -2.54 -1.016) (end 2.54 1.016) (stroke (width 0.254) (type default)) (fill (type none)))')
        graphics.extend([line([(-5.08, 0), (-2.54, 0)]), line([(2.54, 0), (5.08, 0)])])
    elif part.kind in ["C", "CP", "C_bus"]:
        graphics.extend([line([(-0.762, -2.54), (-0.762, 2.54)]), line([(0.762, -2.54), (0.762, 2.54)]),
                         line([(-5.08, 0), (-0.762, 0)]), line([(0.762, 0), (5.08, 0)])])
        if part.kind == "CP":
            graphics.append(f'(text "+" (at -2.54 2.54 0) {effects()})')
    elif part.kind in ["D", "TVS", "diode_module"]:
        graphics.extend([line([(-1.27, -2.54), (-1.27, 2.54)]),
                         line([(-1.27, 0), (2.54, 2.54), (2.54, -2.54), (-1.27, 0)]),
                         line([(-5.08, 0), (-1.27, 0)]), line([(2.54, 0), (5.08, 0)])])
    elif part.kind in ["NPN", "PNP"]:
        graphics.extend([line([(-5.08, 0), (-1.27, 0)]), line([(-1.27, -3.81), (-1.27, 3.81)]),
                         line([(-1.27, 1.27), (3.81, 5.08), (5.08, 5.08)]),
                         line([(-1.27, -1.27), (3.81, -5.08), (5.08, -5.08)])])
        graphics.append(line([(0.5, -3.9), (3.0, -4.5), (2.0, -2.0)]) if part.kind == "NPN"
                        else line([(0.5, -3.9), (-0.4, -1.9), (2.0, -2.0)]))
    elif part.kind == "flag":
        graphics.append(line([(0, 0), (0, 2.54), (-1.27, 3.81), (0, 5.08), (1.27, 3.81), (0, 2.54)]))
    elif part.kind == "switch":
        graphics.append(line([(-5.08, 0), (-2.54, 0), (3.81, 2.54)]))
        graphics.append(line([(3.81, 0), (5.08, 0)]))
    else:
        graphics.append(f'(rectangle (start {-half_width} {-half_height}) (end {half_width} {half_height}) (stroke (width 0.254) (type default)) (fill (type background)))')
        if part.kind == "fuse":
            graphics.append(line([(-5.08, 0), (5.08, 0)]))
    pin_strings = []
    for number, pin_name, _, pin_type, x, y, angle in pins:
        length = 0 if part.kind == "flag" else 5.08 if half_width == 17.78 else 2.54
        pin_strings.append(f'(pin {pin_type} line (at {x} {y} {angle}) (length {length}) '
                           f'(name {quote(pin_name)} {effects(0.9)}) (number {quote(number)} {effects(0.9)}))')
    lib_name = "Batman:" + name if embedded else name
    hidden = "(hide yes)" if part.kind in ["R", "C", "CP", "C_bus", "D", "TVS", "diode_module", "fuse", "switch", "flag"] else ""
    return (f'(symbol {quote(lib_name)} (pin_names (offset 0.508) {hidden}) '
            f'(in_bom {"no" if part.kind == "flag" else "yes"}) (on_board {"yes" if part.board else "no"}) '
            f'(property "Reference" {quote(part.ref)} (at 0 {half_height + 2.54} 0) {effects()}) '
            f'(property "Value" {quote(part.value)} (at 0 {-half_height - 2.54} 0) {effects()}) '
            f'(symbol {quote(name + "_0_1")} {" ".join(graphics)}) '
            f'(symbol {quote(name + "_1_1")} {" ".join(pin_strings)}))')


def text(content, x, y, size=1.27):
    return f'(text {quote(content)} (at {x} {y} 0) {effects(size, "(justify left)")} (uuid {uid(content + str(x) + str(y))}))'


def instance(part, x, y):
    pins, _, half_height = geometry(part)
    ref = part.ref
    identifier = uid("symbol/" + ref)
    path = f'/{uid("root")}/{uid("sheet/" + part.sheet)}'
    name = ref.replace("#", "_")
    content = [f'(symbol (lib_id "Batman:{name}") (at {x} {y} 0) (unit 1) '
               f'(in_bom {"no" if part.kind == "flag" else "yes"}) (on_board {"yes" if part.board else "no"}) '
               f'(dnp {"yes" if ref == "D3" else "no"}) (uuid {identifier}) '
               f'(property "Reference" {quote(ref)} (at {x} {y - half_height - 4} 0) {effects(1.0)}) '
               f'(property "Value" {quote(part.value)} (at {x} {y - half_height - 1.5} 0) {effects(0.9)}) '
               f'(property "Footprint" {quote(part.footprint)} (at {x} {y} 0) {effects(1, "(hide yes)")}) '
               f'(property "Board" {quote(part.board or "EXTERNAL")} (at {x} {y} 0) {effects(1, "(hide yes)")}) '
               f'(property "Alias" {quote(part.alias)} (at {x} {y + half_height + 2} 0) {effects(0.9, "" if part.alias else "(hide yes)")}) '
               + " ".join(f'(pin {quote(number)} (uuid {uid(ref + "/pin/" + number)}))' for number, *_ in pins)
               + f'(instances (project "batman" (path "{path}" (reference {quote(ref)}) (unit 1)))))']
    for number, _, net, _, dx, dy, angle in pins:
        px, py = round(x + dx, 4), round(y - dy, 4)
        if net is None:
            content.append(f'(no_connect (at {px} {py}) (uuid {uid(ref + "/nc/" + number)}))')
            continue
        if part.kind == "flag":
            endpoint = px + 5.08
            label_angle = 180
        else:
            endpoint = round(px + (5.08 if angle == 180 else -5.08), 4)
            label_angle = angle
        content.append(f'(wire (pts (xy {px} {py}) (xy {endpoint} {py})) (stroke (width 0) (type default)) (uuid {uid(ref + "/wire/" + number)}))')
        content.append(f'(global_label {quote(net)} (shape bidirectional) (at {endpoint} {py} {label_angle}) '
                       f'{effects(0.9, "(justify left)" if label_angle == 180 else "(justify right)")} '
                       f'(uuid {uid(ref + "/label/" + number)}))')
    return "\n".join(content)


def generate(parts):
    ROOT.mkdir(parents=True, exist_ok=True)
    project_file = ROOT / "batman.kicad_pro"
    if not project_file.exists():
        settings = {"meta": {"filename": "batman.kicad_pro", "version": 1},
                    "board": {"design_settings": {"rules": {"min_clearance": 0.5,
                               "min_track_width": 0.7, "min_hole_clearance": 0.25,
                               "min_copper_edge_clearance": 0.5}}},
                    "net_settings": {"classes": [{"name": "Default", "clearance": 0.5,
                                      "track_width": 0.7}], "meta": {"version": 3}}}
        project_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    library = '(kicad_symbol_lib (version 20241209) (generator "kicad_symbol_editor")\n'
    library += "\n".join(symbol(part) for part in parts) + ")\n"
    (ROOT / "Batman.kicad_sym").write_text(library, encoding="utf-8")
    (ROOT / "sym-lib-table").write_text('(sym_lib_table (version 7) (lib (name "Batman") (type "KiCad") (uri "${KIPRJMOD}/Batman.kicad_sym") (options "") (descr "Batman modules and components")))\n', encoding="utf-8")
    notes = {
        "power": "P01-P28: external power wiring 2.5 mm2; P28 logic ground 0.75 mm2.\nB1/B2 are AFTER sensors, BEFORE switches. IP- faces battery / source.\nLOAD+/GND: external terminals, C1/C2 wired directly, no buffer PCB. D3 DNP; not a 35 V clamp.",
        "charge": "REMOVE relay VCC-JD_VCC jumper. Route VCC / JD_VCC separately from X3.\nDPS: GND TX RX -> G R T; leave V unconnected. Set mDC5 to 5.0 V BEFORE plugging J1.\nNever close K1 and K2 together. Switch relays only at verified zero current. Hardware rating: 10 A maximum.",
        "sense": "PCB B: analog filters ONLY. J32 -> external J2 A0-A3/GND; J33 -> external J13 A0/A1/GND.\nJ2 ADDR=GND (0x48); J13 ADDR=VDD (0x49), A2/A3=GND; both ALRT NC. C6/C10 at modules.\nADCs powered from A, NOT B. J25: GND/3V3_SENS from C. No SDA/SCL on B. Verify sensor model.",
        "logic": "PCB A: J20 -> external ADS J2; J21 -> external ADS J13. Both: 3V3/GND/SCL/SDA.\nShared GPIO21=SDA/GPIO22=SCL; one pull-up pair R16/R17. GPIO34/39 NC.\nJ22 -> C, J26 receives 5 V from D; J28 relay control to D. Cable map: output/cable-map.csv.",
        "supply3": "PCB C: DISTRIBUTION ONLY, no regulator. J23 receives 3V3/GND/SENS_PWR from ESP PCB A.\nJ24 supplies PCB B sensors: GND/3V3_SENS. J30 is a spare 3V3/GND output.\nQ3 switches sensor supply only. Do NOT connect another regulator to this 3V3 rail.",
        "supply5": "PCB D: DISTRIBUTION ONLY. X3 receives regulated 5.0 V from external LM2596.\nX1 battery taps feed diode OR -> X2 LM2596 input; X6 -> X8 on ADC PCB B (sense only).\nNT1 star: separate relay VCC/JD-VCC. REMOVE relay jumper. J27 -> ESP; J31 spare 5 V."
    }
    for sheet in SHEETS:
        selected = [part for part in parts if part.sheet == sheet]
        content = [f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {uid("sheet/" + sheet)}) (paper "A3")',
                   f'(title_block (title "BATMAN - {sheet.upper()}") (date "2026-09-09") (rev "A-prototype"))',
                   '(lib_symbols ' + "\n".join(symbol(part, True) for part in selected) + ")",
                   text("BATMAN / " + sheet.upper(), 15, 16, 2), text(notes[sheet], 15, 23, 1.1)]
        heights = [45.72] * 4
        for part in selected:
            column = min(range(4), key=lambda index: heights[index])
            _, _, half_height = geometry(part)
            center_y = round(heights[column] + half_height, 4)
            content.append(instance(part, 50.8 + column * 99.06, center_y))
            heights[column] = center_y + half_height + 19.05
        assert max(heights) < 271, (sheet, heights)
        content.append(")")
        (ROOT / f"{sheet}.kicad_sch").write_text("\n".join(content), encoding="utf-8")
    root = [f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {uid("root")}) (paper "A4")',
            '(title_block (title "BATMAN - dual battery manager") (date "2026-09-09") (rev "A-prototype"))',
            '(lib_symbols)', text("BATMAN / LiFePO4 8S + lead-acid 24 V", 25, 25, 2.54),
            text("Four PCBs: A ESP + two I2C ports, B analog filters, C 3V3 distribution, D 5V distribution.\nTwo external ADS1115: analog from B, power/I2C from A. B.Cu only; WC = external cables.\nLOAD bus C1/C2 stay externally wired. Prototype: verify sensor model, fit and current budgets.", 25, 40, 1.27)]
    for index, name in enumerate(SHEETS):
        x = 30 + (index % 2) * 125
        y = 65 + (index // 2) * 42
        root.append(f'(sheet (at {x} {y}) (size 90 30) (stroke (width 0.254) (type default)) (fill (color 0 0 0 0)) '
                    f'(uuid {uid("sheet/" + name)}) (property "Sheetname" {quote(name)} (at {x} {y - 1} 0) {effects(1.27, "(justify left bottom)")}) '
                    f'(property "Sheetfile" "{name}.kicad_sch" (at {x} {y + 31} 0) {effects(1.27, "(justify left top)")}) '
                    f'(instances (project "batman" (path "/{uid("root")}" (page "{index + 2}")))))')
    root.append('(sheet_instances (path "/" (page "1"))))')
    (ROOT / "batman.kicad_sch").write_text("\n".join(root), encoding="utf-8")
    print(f"Generated root and {len(SHEETS)} KiCad schematic sheets")


if __name__ == "__main__":
    design = circuit()
    validate(design)
    generate(design)