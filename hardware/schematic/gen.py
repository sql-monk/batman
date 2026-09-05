"""Генерує KiCad-проєкт схеми batman з docs/connections.md.

    python gen.py            # пише batman.kicad_pro, *.kicad_sch, lib/batman.kicad_sym
    kicad-cli sch erc --severity-all -o erc.rpt batman.kicad_sch

Чотири аркуші (power, charge, sense, logic), усі ланцюги — глобальними мітками:
вузли (B1, B2, LOAD+, CHG, GND, +5V, +3V3, …) і номери проводів (P02, P05, … з connections.md)
для двоточкових з'єднань. Стандартні символи вбудовуються з бібліотек KiCad, модулі — з lib/batman.kicad_sym.
"""
from __future__ import annotations
import os
import re
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
KICAD_SYMBOLS = Path(os.environ.get("KICAD_SYMBOLS", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/share/kicad/symbols"))
PROJECT = "batman"
G = 2.54  # крок сітки


# ---------------------------------------------------------------- S-вирази
def tokenize(s: str):
    tok = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')
    return tok.findall(s)


def parse(tokens, i=0):
    out = []
    while i < len(tokens):
        t = tokens[i]
        if t == "(":
            sub, i = parse(tokens, i + 1)
            out.append(sub)
        elif t == ")":
            return out, i + 1
        else:
            out.append(t)
            i += 1
    return out, i


def sx(node, ind=0) -> str:
    """Серіалізація списку назад у текст із відступами."""
    if isinstance(node, str):
        return node
    if not any(isinstance(c, list) for c in node):
        return "(" + " ".join(node) + ")"
    head = [c for c in node if isinstance(c, str)]
    kids = [c for c in node if isinstance(c, list)]
    pad = "  " * (ind + 1)
    return "(" + " ".join(head) + "\n" + "\n".join(pad + sx(k, ind + 1) for k in kids) + "\n" + "  " * ind + ")"


def q(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- бібліотечні символи
_lib_cache: dict[str, dict[str, list]] = {}


def lib_symbols(libname: str) -> dict[str, list]:
    if libname not in _lib_cache:
        text = (KICAD_SYMBOLS / f"{libname}.kicad_sym").read_text(encoding="utf-8")
        tree, _ = parse(tokenize(text))
        syms = {}
        for node in tree[0]:
            if isinstance(node, list) and node and node[0] == "symbol":
                syms[node[1].strip('"')] = node
        _lib_cache[libname] = syms
    return _lib_cache[libname]


def _deep(node):
    return [c if isinstance(c, str) else _deep(c) for c in node]


def std_symbol(lib_id: str) -> list[list]:
    """Один сплощений символ для lib_symbols: ім'я "Lib:Name", юніти "Name_0_1", без extends (батьківська графіка вкладена)."""
    lib, name = lib_id.split(":")
    src = _deep(lib_symbols(lib)[name])
    parent_name = next((c[1].strip('"') for c in src if isinstance(c, list) and c and c[0] == "extends"), None)
    if parent_name:
        parent = _deep(lib_symbols(lib)[parent_name])
        child_props = {c[1]: c for c in src if isinstance(c, list) and c[0] == "property"}
        merged = ["symbol"]
        for c in parent[1:]:
            if isinstance(c, list) and c[0] == "property" and c[1] in child_props:
                merged.append(child_props.pop(c[1]))
            else:
                merged.append(c)
        merged += list(child_props.values())
        src = merged
        for c in src:
            if isinstance(c, list) and c[0] == "symbol":
                c[1] = q(c[1].strip('"').replace(parent_name, name, 1))
    src[1] = q(lib_id)
    return [src]


def symbol_pins(sym: list) -> dict[str, tuple[float, float, int]]:
    """{номер: (x, y, кут)} у координатах символу (y вгору)."""
    pins = {}

    def walk(node):
        if not isinstance(node, list):
            return
        if node and node[0] == "pin":
            at = next(c for c in node if isinstance(c, list) and c[0] == "at")
            num = next(c for c in node if isinstance(c, list) and c[0] == "number")[1].strip('"')
            pins[num] = (float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0)
        for c in node:
            walk(c)

    walk(sym)
    return pins


def resolved_pins(lib_id: str, embedded: list[list]) -> dict[str, tuple[float, float, int]]:
    me = next(s for s in embedded if s[1].strip('"') == lib_id)
    return symbol_pins(me)


# ---------------------------------------------------------------- власні символи модулів
def module_symbol(name: str, value: str, left: list[tuple[str, str]], right: list[tuple[str, str]], desc: str, footprint: str = "") -> list:
    """Прямокутник з пінами: left/right — [(ім'я, тип)]. Номери пінів — наскрізні."""
    rows = max(len(left), len(right))
    h = (rows + 1) * G / 2
    w = 12.7
    body = ["symbol", q(f"{name}_0_1"),
            ["rectangle", ["start", f"{-w}", f"{h}"], ["end", f"{w}", f"{-h}"],
             ["stroke", ["width", "0.254"], ["type", "default"]], ["fill", ["type", "background"]]]]
    pins = ["symbol", q(f"{name}_1_1")]
    n = 1
    L = 5.08

    def pin(pname, ptype, x, y, ang):
        nonlocal n
        p = ["pin", ptype, "line", ["at", f"{x}", f"{y}", f"{ang}"], ["length", f"{L}"],
             ["name", q(pname), ["effects", ["font", ["size", "1.27", "1.27"]]]],
             ["number", q(str(n)), ["effects", ["font", ["size", "1.27", "1.27"]]]]]
        n += 1
        return p

    for i, (pn, pt) in enumerate(left):
        pins.append(pin(pn, pt, -w - L, h - G * (i + 1), 0))
    for i, (pn, pt) in enumerate(right):
        pins.append(pin(pn, pt, w + L, h - G * (i + 1), 180))
    return ["symbol", q(f"batman:{name}"), ["pin_names", ["offset", "1.016"]], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            prop("Reference", "U", 0, h + 1.27, hide=False), prop("Value", value, 0, -h - 1.27, hide=False),
            prop("Footprint", footprint, 0, 0), prop("Datasheet", "", 0, 0), prop("Description", desc, 0, 0),
            body, pins]


def prop(key, val, x, y, hide=True, rot=0, justify=None):
    eff = ["effects", ["font", ["size", "1.27", "1.27"]]]
    if justify:
        eff.append(["justify", justify])
    if hide:
        eff.append(["hide", "yes"])
    return ["property", q(key), q(val), ["at", f"{x}", f"{y}", f"{rot}"], eff]


PI, PO, PP, BI, IN, OUT, OC = "power_in", "power_out", "passive", "bidirectional", "input", "output", "open_collector"

MODULES = {
    "ACS711EX": module_symbol("ACS711EX", "ACS711EX ±15.5A",
                              [("IP+", PP), ("IP-", PP)],
                              [("VCC", PI), ("GND", PI), ("VIOUT", OUT), ("FAULT", OC)],
                              "Pololu ACS711EX датчик струму, 90 мВ/А при 3,3 В; на панельці гілки, до плати A дюпонами"),
    "POLOLU_2815": module_symbol("POLOLU_2815", "Pololu #2815",
                                 [("VIN", PP), ("GND", PP), ("CTRL", PP)],
                                 [("VOUT", PP), ("ON", IN), ("CTRL", PP)],
                                 "Big MOSFET Slide Switch HP: повзунок задає стан без контролера, ON — від GPIO 3,3 В"),
    "XL74610": module_symbol("XL74610", "XL74610",
                             [("A", PP)], [("K", PP)],
                             "Ідеальний діод LM74610 + MOSFET; дроти напаяні на площадки"),
    "RELAY2": module_symbol("RELAY2", "FL-3FF-S-Z ×2",
                            [("VCC", PI), ("GND", PI), ("IN1", IN), ("IN2", IN), ("JD-VCC", PI)],
                            [("COM1", PP), ("NO1", PP), ("NC1", PP), ("COM2", PP), ("NO2", PP), ("NC2", PP)],
                            "Модуль реле 2-кан., тригер за низьким рівнем, оптрони; перемичка VCC–JD-VCC знята"),
    "DPS5015": module_symbol("DPS5015", "DPS5015 (силова плата)",
                             [("IN+", PI), ("IN-", PI), ("OUT+", PP), ("OUT-", PP)],
                             [("V", PO), ("R", IN), ("T", OUT), ("G", PP)],
                             "RuiDeng DPS5015 без дисплея; Modbus RTU 9600 8N1 адреса 1 на порту V R T G"),
    "ADS1115": module_symbol("ADS1115", "ADS1115 module",
                             [("VDD", PI), ("GND", PI), ("SCL", IN), ("SDA", BI), ("ADDR", IN)],
                             [("ALRT", OUT), ("A0", IN), ("A1", IN), ("A2", IN), ("A3", IN)],
                             "16-бітний I2C АЦП, 0x48 (ADDR→GND); сидить у гнізді J2 на платі A",
                             "Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical"),
    "LM2596": module_symbol("LM2596", "LM2596 HW-411",
                            [("IN+", PI), ("IN-", PI)], [("OUT+", PO), ("OUT-", PI)],
                            "DC-DC 27–29 В → 5,0 В для логіки й обмоток реле"),
    "OLED_SSD1306": module_symbol("OLED_SSD1306", "OLED 0.96\" I2C",
                                  [("GND", PI), ("VDD", PI)], [("SCK", IN), ("SDA", BI)],
                                  "SSD1306 128×64, 0x3C; порядок пінів — за екземпляром (див. components.md)"),
    "ESP32_DEVKITC": module_symbol(
        "ESP32_DEVKITC", "ESP32 DevKitC 38",
        [("3V3", PO), ("EN", IN), ("VP/36", IN), ("VN/39", IN), ("34", IN), ("35", IN), ("32", BI), ("33", BI), ("25", BI), ("26", BI),
         ("27", BI), ("14", BI), ("12", BI), ("GND", PI), ("13", BI), ("D2/9", BI), ("D3/10", BI), ("CMD/11", BI), ("5V", PI)],
        [("GND", PI), ("23", BI), ("22", BI), ("TX0/1", BI), ("RX0/3", BI), ("21", BI), ("GND", PI), ("19", BI), ("18", BI), ("5", BI),
         ("17", BI), ("16", BI), ("4", BI), ("0", BI), ("2", BI), ("15", BI), ("D1/8", BI), ("D0/7", BI), ("CLK/6", BI)],
        "ESP32-DevKitC 38 пін; піни 1–19 ліва гребінка зверху вниз, 20–38 права; сидить у гніздах J1",
        "batman:ESP32_DevKitC_38_Socket"),
}


def module_pin_number(name: str, pin_name: str, occurrence: int = 0) -> str:
    sym = MODULES[name]
    k = 0
    for sub in sym:
        if isinstance(sub, list) and sub[0] == "symbol":
            for p in sub:
                if isinstance(p, list) and p[0] == "pin":
                    pn = next(c for c in p if isinstance(c, list) and c[0] == "name")[1].strip('"')
                    if pn == pin_name:
                        if k == occurrence:
                            return next(c for c in p if isinstance(c, list) and c[0] == "number")[1].strip('"')
                        k += 1
    raise KeyError(f"{name}.{pin_name}")


def module_footprint(name: str) -> str:
    for c in MODULES[name]:
        if isinstance(c, list) and c[0] == "property" and c[1] == '"Footprint"':
            return c[2].strip('"')
    return ""


# ---------------------------------------------------------------- аркуш
def snap(v: float) -> float:
    return round(round(v / 1.27) * 1.27, 2)


class Part:
    def __init__(self, ref, lib_id, value, x, y, nets: dict, footprint="", on_board=True, rot=0):
        self.ref, self.lib_id, self.value, self.x, self.y, self.nets, self.fp, self.on_board, self.rot = ref, lib_id, value, snap(x), snap(y), nets, footprint, on_board, rot
        self.uuid = uid()


class Sheet:
    def __init__(self, name: str, title: str, paper="A3"):
        self.name, self.title, self.paper = name, title, paper
        self.uuid = uid()        # uuid символу аркуша в корені (йде в path)
        self.file_uuid = uid()   # uuid самого файла
        self.parts: list[Part] = []
        self.texts: list[tuple[str, float, float]] = []

    def add(self, *parts: Part):
        self.parts += parts

    def text(self, s, x, y):
        self.texts.append((s, x, y))

    def render(self, root_uuid: str, page: int, root: bool = False, sheets: list["Sheet"] | None = None) -> str:
        embedded: dict[str, list] = {}
        for p in self.parts:
            if p.lib_id.startswith("batman:"):
                embedded[p.lib_id] = MODULES[p.lib_id.split(":")[1]]
            else:
                for s in std_symbol(p.lib_id):
                    embedded[s[1].strip('"')] = s
        emb_list = list(embedded.values())
        items: list[list] = []
        used_labels: dict[str, int] = {}
        path = f"/{root_uuid}" if root else f"/{root_uuid}/{self.uuid}"

        for p in self.parts:
            pins = resolved_pins(p.lib_id, emb_list)
            if p.lib_id.startswith("batman:"):
                half = max(abs(py) for _, py, _ in pins.values()) + G  # половина висоти тіла
                ref_at, val_at, just = (p.x, p.y - half - 1.27), (p.x, p.y + half + 1.27), None
            else:
                ref_at, val_at, just = (p.x + 1.27, p.y - 2.54), (p.x + 1.27, p.y), "left"
            sym = ["symbol", ["lib_id", q(p.lib_id)], ["at", f"{p.x}", f"{p.y}", f"{p.rot}"], ["unit", "1"],
                   ["exclude_from_sim", "no"], ["in_bom", "yes" if not p.ref.startswith("#") else "no"], ["on_board", "yes" if p.on_board else "no"], ["dnp", "no"],
                   ["uuid", q(p.uuid)],
                   prop("Reference", p.ref, *ref_at, hide=p.ref.startswith("#"), justify=just),
                   prop("Value", p.value, *val_at, hide=False, justify=just),
                   prop("Footprint", p.fp, p.x, p.y), prop("Datasheet", "", p.x, p.y), prop("Description", "", p.x, p.y)]
            for num in pins:
                sym.append(["pin", q(num), ["uuid", q(uid())]])
            sym.append(["instances", ["project", q(PROJECT), ["path", q(path), ["reference", q(p.ref)], ["unit", "1"]]]])
            items.append(sym)
            for num, (px, py, ang) in pins.items():
                net = p.nets.get(num)
                if net is None:
                    raise KeyError(f"{p.ref} ({p.lib_id}): пін {num} не описаний")
                # позиція піна в аркуші (y символу вгору → в аркуші вниз)
                if p.rot == 0:
                    X, Y, A = p.x + px, p.y - py, ang
                elif p.rot == 90:
                    X, Y, A = p.x + py, p.y + px, (ang + 90) % 360
                elif p.rot == 180:
                    X, Y, A = p.x - px, p.y + py, (ang + 180) % 360
                else:
                    X, Y, A = p.x - py, p.y - px, (ang + 270) % 360
                X, Y = round(X, 2), round(Y, 2)
                if net == "NC":
                    items.append(["no_connect", ["at", f"{X}", f"{Y}"], ["uuid", q(uid())]])
                    continue
                dx, dy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[A]
                stub = 5.08
                EX, EY = round(X + dx * stub, 2), round(Y + dy * stub, 2)
                items.append(["wire", ["pts", ["xy", f"{X}", f"{Y}"], ["xy", f"{EX}", f"{EY}"]],
                              ["stroke", ["width", "0"], ["type", "default"]], ["uuid", q(uid())]])
                lab_ang = {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}[(dx, dy)]
                just = "right" if lab_ang in (180, 270) else "left"
                items.append(["global_label", q(net), ["shape", "passive"], ["at", f"{EX}", f"{EY}", f"{lab_ang}"],
                              ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just]], ["uuid", q(uid())],
                              ["property", q("Intersheetrefs"), q("${INTERSHEET_REFS}"), ["at", f"{EX}", f"{EY}", "0"],
                               ["effects", ["font", ["size", "1.27", "1.27"]], ["hide", "yes"]]]])
                used_labels[net] = used_labels.get(net, 0) + 1

        for s, x, y in self.texts:
            items.append(["text", q(s), ["exclude_from_sim", "no"], ["at", f"{x}", f"{y}", "0"],
                          ["effects", ["font", ["size", "1.6", "1.6"]], ["justify", "left", "top"]], ["uuid", q(uid())]])

        if root and sheets:
            for i, sh in enumerate(sheets):
                x, y = 30.48 + i * 60.96, 60.96
                items.append(["sheet", ["at", f"{x}", f"{y}"], ["size", "45.72", "20.32"], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                              ["stroke", ["width", "0.1524"], ["type", "solid"]], ["fill", ["color", "0", "0", "0", "0.0000"]],
                              ["uuid", q(sh.uuid)],
                              ["property", q("Sheetname"), q(sh.name), ["at", f"{x}", f"{y - 0.7}", "0"], ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "bottom"]]],
                              ["property", q("Sheetfile"), q(f"{sh.name}.kicad_sch"), ["at", f"{x}", f"{y + 20.9}", "0"], ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "top"]]],
                              ["instances", ["project", q(PROJECT), ["path", q(f"/{root_uuid}"), ["page", q(str(i + 2))]]]]])

        doc = ["kicad_sch", ["version", "20251024"], ["generator", q("batman_gen")], ["generator_version", q("1.0")],
               ["uuid", q(root_uuid if root else self.file_uuid)], ["paper", q(self.paper)],
               ["title_block", ["title", q(self.title)], ["rev", q("A")], ["company", q("batman")]],
               ["lib_symbols", *emb_list], *items]
        if root:
            doc.append(["sheet_instances", ["path", q("/"), ["page", q("1")]]])
        self.labels = used_labels
        return sx(doc) + "\n"


# ---------------------------------------------------------------- вміст аркушів (connections.md)
def M(name):
    return f"batman:{name}"


def mod(ref, name, value, x, y, conns: dict[str, str], on_board=False, fp=""):
    """Модуль: з'єднання за іменами пінів; однойменні (GND, CTRL) — списком за порядком."""
    nets = {}
    seen: dict[str, int] = {}
    for pname, net in conns.items():
        base, _, idx = pname.partition("#")
        nets[module_pin_number(name, base, int(idx) if idx else 0)] = net
    return Part(ref, M(name), value, x, y, nets, fp or module_footprint(name), on_board)


def std(ref, lib_id, value, x, y, nets: dict[str, str], fp="", on_board=True):
    return Part(ref, lib_id, value, x, y, nets, fp, on_board)


FP_R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
FP_C = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
FP_CP = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
FP_D = "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"
FP_TVS = "Diode_THT:D_DO-15_P10.16mm_Horizontal"
FP_TO92 = "Package_TO_SOT_THT:TO-92_Inline"
FP_FUSE = "Fuse:Fuseholder_Blade_ATO_Littelfuse_Pudenz_2_Pin"
FP_SCREW = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-{n:02d}P_1x{n:02d}_P5.00mm"
FP_HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"
FP_SW = "Button_Switch_THT:SW_PUSH_6mm"


def build():
    power = Sheet("power", "batman — power: гілки, ключі, діоди, шина (плата B)")
    charge = Sheet("charge", "batman — charge: DPS5015, mDIO3, реле K1/K2")
    sense = Sheet("sense", "batman — sense: датчики, дільники, ADS1115 (плата A)")
    logic = Sheet("logic", "batman — logic: ESP32, живлення, реле-ключі, роз'єми (плата A)")

    # ---- power
    power.text("Гілка Bat1: P01 BAT1+ → F1 → P02 → mACS1 IP− … IP+ → B1 → mSW1 → P05 → mDIO1 → LOAD+", 20, 20)
    power.text("Гілка Bat2: P07 BAT2+ → F2 → P08 → mACS2 → B2 → mSW2 → P11 → mDIO2 → LOAD+;  вихід: LOAD+ → mACS3 → P14 → Fout → LOAD_OUT+", 20, 24)
    power.text("Плата B: клема LOAD+ (P06, P12, P13), мінус-шина (P24–P28), C1 100 мкФ + C2 100 нФ, D3 TVS 33 В", 20, 28)
    y1, y2, y3 = 60, 120, 180
    power.add(
        std("XB1", "Connector:Screw_Terminal_01x02", "BAT1", 30, y1, {"1": "BAT1+", "2": "GND"}, "", on_board=False),
        std("F1", "Device:Fuse", "ATO 15A", 60, y1 - 5.08, {"1": "BAT1+", "2": "P02"}, FP_FUSE, on_board=False),
        mod("mACS1", "ACS711EX", "ACS711EX", 100, y1, {"IP-": "P02", "IP+": "B1", "VCC": "+3V3_SENS", "GND": "GND", "VIOUT": "I_B1_RAW", "FAULT": "FAULT"}),
        mod("mSW1", "POLOLU_2815", "Pololu #2815", 160, y1, {"VIN": "B1", "GND": "GND", "CTRL#0": "NC", "VOUT": "P05", "ON": "SW1_ON", "CTRL#1": "NC"}),
        mod("mDIO1", "XL74610", "XL74610", 220, y1, {"A": "P05", "K": "LOAD+"}),

        std("XB2", "Connector:Screw_Terminal_01x02", "BAT2", 30, y2, {"1": "BAT2+", "2": "GND"}, "", on_board=False),
        std("F2", "Device:Fuse", "ATO 15A", 60, y2 - 5.08, {"1": "BAT2+", "2": "P08"}, FP_FUSE, on_board=False),
        mod("mACS2", "ACS711EX", "ACS711EX", 100, y2, {"IP-": "P08", "IP+": "B2", "VCC": "+3V3_SENS", "GND": "GND", "VIOUT": "I_B2_RAW", "FAULT": "FAULT"}),
        mod("mSW2", "POLOLU_2815", "Pololu #2815", 160, y2, {"VIN": "B2", "GND": "GND", "CTRL#0": "NC", "VOUT": "P11", "ON": "SW2_ON", "CTRL#1": "NC"}),
        mod("mDIO2", "XL74610", "XL74610", 220, y2, {"A": "P11", "K": "LOAD+"}),

        mod("mACS3", "ACS711EX", "ACS711EX", 100, y3, {"IP-": "LOAD+", "IP+": "P14", "VCC": "+3V3_SENS", "GND": "GND", "VIOUT": "I_LOAD_RAW", "FAULT": "FAULT"}),
        std("Fout", "Device:Fuse", "ATO 15A", 160, y3 - 5.08, {"1": "P14", "2": "LOAD_OUT+"}, FP_FUSE, on_board=False),
        std("XLOAD", "Connector:Screw_Terminal_01x02", "LOAD", 220, y3, {"1": "LOAD_OUT+", "2": "GND"}, "", on_board=False),

        std("C1", "Device:C_Polarized", "100µ 50V", 290, y1, {"1": "LOAD+", "2": "GND"}, FP_CP),
        std("C2", "Device:C", "100n", 320, y1, {"1": "LOAD+", "2": "GND"}, FP_C),
        std("D3", "Device:D_TVS", "SMBJ33A / 1.5KE33", 350, y1, {"1": "GND", "2": "LOAD+"}, FP_TVS),
        std("XLP", "Connector:Screw_Terminal_01x03", "LOAD+ (P06 P12 P13)", 290, y2, {"1": "LOAD+", "2": "LOAD+", "3": "LOAD+"}, FP_SCREW.format(n=3)),
        std("XGND", "Connector:Screw_Terminal_01x05", "GND-шина (P24–P28)", 340, y2, {"1": "GND", "2": "GND", "3": "GND", "4": "GND", "5": "GND"}, FP_SCREW.format(n=5)),
        std("#FLG1", "power:PWR_FLAG", "PWR_FLAG", 290, y3, {"1": "BAT1+"}),
        std("#FLG2", "power:PWR_FLAG", "PWR_FLAG", 320, y3, {"1": "BAT2+"}),
        std("#FLG3", "power:PWR_FLAG", "PWR_FLAG", 350, y3, {"1": "GND"}),
    )

    # ---- charge
    charge.text("P22/P23 БЖ 33 В → DPS IN;  P16 DPS OUT+ → Fchg → P17 → mDIO3 → CHG (= COM1 = COM2, P18/P19);  NO1 → B1 (P20), NO2 → B2 (P21)", 20, 20)
    charge.text("UART: DPS R ← DPS_TX (GPIO17), DPS T → DPS_RX (GPIO16), G → GND через J9 плати A. Реле комутують лише при ONOFF = 0 і IOUT = 0.", 20, 24)
    charge.add(
        std("XPSU", "Connector:Screw_Terminal_01x02", "БЖ 33V 10A", 30, 70, {"1": "PSU+", "2": "GND"}, "", on_board=False),
        mod("mDPS", "DPS5015", "DPS5015", 100, 70, {"IN+": "PSU+", "IN-": "GND", "OUT+": "P16", "OUT-": "GND", "V": "NC", "R": "DPS_TX", "T": "DPS_RX", "G": "GND"}),
        std("Fchg", "Device:Fuse", "ATO 15A", 160, 64.92, {"1": "P16", "2": "P17"}, FP_FUSE, on_board=False),
        mod("mDIO3", "XL74610", "XL74610", 210, 70, {"A": "P17", "K": "CHG"}),
        mod("mREL2", "RELAY2", "реле 2-кан.", 300, 70, {"VCC": "+5V", "GND": "GND", "IN1": "K1_IN", "IN2": "K2_IN", "JD-VCC": "+5V",
                                                          "COM1": "CHG", "NO1": "B1", "NC1": "NC", "COM2": "CHG", "NO2": "B2", "NC2": "NC"}),
        std("#FLG4", "power:PWR_FLAG", "PWR_FLAG", 30, 130, {"1": "PSU+"}),
    )

    # ---- sense (плата A)
    sense.text("RC 1 кОм + 1 мкФ на кожному VIOUT (зріз ≈ 160 Гц). Дільники: U_B1/U_B2 100k/10k → ADS1115 (1:11), U_LOAD 100k/4,7k → GPIO34 (1:22).", 20, 20)
    sense.text("ADS1115 0x48: A0 I_B1, A1 I_B2, A2 U_B1, A3 U_B2; ADDR → GND. SENS_PWR (GPIO14, активний низький) через Q3 живить датчики (+3V3_SENS) — скидання засувки FAULT.", 20, 24)
    yh = 60
    for i, (ref, net) in enumerate((("J3", "I_B1_RAW"), ("J4", "I_B2_RAW"), ("J5", "I_LOAD_RAW"))):
        sense.add(std(ref, "Connector_Generic:Conn_01x04", f"mACS{i + 1} VCC GND VIOUT FAULT", 30, yh + i * 40,
                      {"1": "+3V3_SENS", "2": "GND", "3": net, "4": "FAULT"}, FP_HDR.format(n=4)))
    for i, (r, c, raw, out) in enumerate((("R7", "C7", "I_B1_RAW", "I_B1"), ("R8", "C8", "I_B2_RAW", "I_B2"), ("R9", "C9", "I_LOAD_RAW", "I_LOAD"))):
        y = yh + i * 40
        sense.add(std(r, "Device:R", "1k", 90, y, {"1": raw, "2": out}, FP_R),
                  std(c, "Device:C", "1µ", 120, y, {"1": out, "2": "GND"}, FP_C))
    for i, (rt, rb, c, src, out, vb) in enumerate((("R1", "R2", "C3", "B1", "U_B1", "10k"), ("R3", "R4", "C4", "B2", "U_B2", "10k"), ("R5", "R6", "C5", "LOAD+", "U_LOAD", "4.7k"))):
        y = yh + 130 + i * 40
        sense.add(std(rt, "Device:R", "100k 1%", 90, y, {"1": src, "2": out}, FP_R),
                  std(rb, "Device:R", f"{vb} 1%", 120, y, {"1": out, "2": "GND"}, FP_R),
                  std(c, "Device:C", "100n", 150, y, {"1": out, "2": "GND"}, FP_C))
    sense.add(
        std("X5", "Connector:Screw_Terminal_01x01", "U_LOAD_SENSE ← LOAD+ (плата B)", 30, yh + 130 + 80, {"1": "LOAD+"}, FP_SCREW.format(n=2)),
        mod("mADC", "ADS1115", "ADS1115", 240, 80, {"VDD": "+3V3", "GND": "GND", "SCL": "SCL", "SDA": "SDA", "ADDR": "GND",
                                                   "ALRT": "NC", "A0": "I_B1", "A1": "I_B2", "A2": "U_B1", "A3": "U_B2"}, on_board=True),
        std("C6", "Device:C", "100n", 240, 130, {"1": "+3V3", "2": "GND"}, FP_C),
        std("Q3", "Transistor_BJT:BC557", "BC557", 320, 80, {"1": "+3V3_SENS", "2": "Q3_B", "3": "+3V3"}, FP_TO92),
        std("R10", "Device:R", "4.7k", 280, 90, {"1": "SENS_PWR", "2": "Q3_B"}, FP_R),
        std("R11", "Device:R", "10k", 320, 50, {"1": "+3V3", "2": "Q3_B"}, FP_R),
        std("#FLG5", "power:PWR_FLAG", "PWR_FLAG", 320, 140, {"1": "+3V3_SENS"}),
    )

    # ---- logic (плата A)
    logic.text("GPIO: 25 SW1_ON, 26 SW2_ON, 27 K1, 13 K2, 14 SENS_PWR, 21 SDA, 22 SCL, 17 DPS_TX, 16 DPS_RX, 4 OW, 33 FAULT, 32 BTN, 34 U_LOAD, 39 I_LOAD; 18/19/23/5 — резерв SPI (J12).", 20, 20)
    logic.text("Живлення: B1/B2 → VD1/VD2 → VIN_DC → mDC5 → +5V → DevKitC 5V і mREL2 VCC/JD-VCC (окремими проводами L07/L08); +3V3 зі стабілізатора DevKitC.", 20, 24)
    logic.add(
        mod("mMCU", "ESP32_DEVKITC", "ESP32 DevKitC", 90, 90, {
            "3V3": "+3V3", "EN": "NC", "VP/36": "NC", "VN/39": "I_LOAD", "34": "U_LOAD", "35": "NC", "32": "BTN", "33": "FAULT",
            "25": "SW1_ON", "26": "SW2_ON", "27": "K1", "14": "SENS_PWR", "12": "NC", "GND#0": "GND", "13": "K2", "D2/9": "NC", "D3/10": "NC", "CMD/11": "NC", "5V": "+5V",
            "GND#1": "GND", "23": "MOSI", "22": "SCL", "TX0/1": "NC", "RX0/3": "NC", "21": "SDA", "GND#2": "GND", "19": "MISO", "18": "SCK", "5": "CS",
            "17": "DPS_TX", "16": "DPS_RX", "4": "OW", "0": "NC", "2": "NC", "15": "NC", "D1/8": "NC", "D0/7": "NC", "CLK/6": "NC"}, on_board=True),
        # реле-ключі
        std("Q1", "Transistor_BJT:BC547", "BC547", 190, 60, {"1": "K1_IN", "2": "Q1_B", "3": "GND"}, FP_TO92),
        std("R12", "Device:R", "1k", 160, 60, {"1": "K1", "2": "Q1_B"}, FP_R),
        std("R13", "Device:R", "10k", 190, 90, {"1": "Q1_B", "2": "GND"}, FP_R),
        std("Q2", "Transistor_BJT:BC547", "BC547", 190, 130, {"1": "K2_IN", "2": "Q2_B", "3": "GND"}, FP_TO92),
        std("R14", "Device:R", "1k", 160, 130, {"1": "K2", "2": "Q2_B"}, FP_R),
        std("R15", "Device:R", "10k", 190, 160, {"1": "Q2_B", "2": "GND"}, FP_R),
        std("J8", "Connector_Generic:Conn_01x05", "mREL2 GND IN1 IN2 VCC JD-VCC", 240, 60, {"1": "GND", "2": "K1_IN", "3": "K2_IN", "4": "+5V", "5": "+5V"}, FP_HDR.format(n=5)),
        # ключі, DPS, OLED, кнопка, SPI
        std("J6", "Connector_Generic:Conn_01x02", "mSW1 GND ON", 240, 100, {"1": "GND", "2": "SW1_ON"}, FP_HDR.format(n=2)),
        std("J7", "Connector_Generic:Conn_01x02", "mSW2 GND ON", 240, 120, {"1": "GND", "2": "SW2_ON"}, FP_HDR.format(n=2)),
        std("J9", "Connector_Generic:Conn_01x03", "DPS GND TX RX", 240, 145, {"1": "GND", "2": "DPS_TX", "3": "DPS_RX"}, FP_HDR.format(n=3)),
        std("J10", "Connector_Generic:Conn_01x04", "OLED GND VDD SCK SDA", 240, 175, {"1": "GND", "2": "+3V3", "3": "SCL", "4": "SDA"}, FP_HDR.format(n=4)),
        mod("mOLED", "OLED_SSD1306", "OLED 0.96\"", 300, 175, {"GND": "GND", "VDD": "+3V3", "SCK": "SCL", "SDA": "SDA"}),
        std("J11", "Connector_Generic:Conn_01x02", "BTN", 240, 205, {"1": "BTN", "2": "GND"}, FP_HDR.format(n=2)),
        std("SW1", "Switch:SW_Push", "кнопка панелі", 300, 205, {"1": "BTN", "2": "GND"}, FP_SW, on_board=False),
        std("J12", "Connector_Generic:Conn_01x06", "SPI резерв 3V3 GND SCK MISO MOSI CS", 240, 240, {"1": "+3V3", "2": "GND", "3": "SCK", "4": "MISO", "5": "MOSI", "6": "CS"}, FP_HDR.format(n=6)),
        # підтяжки
        std("R16", "Device:R", "4.7k", 160, 200, {"1": "+3V3", "2": "SDA"}, FP_R),
        std("R17", "Device:R", "4.7k", 175, 200, {"1": "+3V3", "2": "SCL"}, FP_R),
        std("R18", "Device:R", "4.7k", 190, 200, {"1": "+3V3", "2": "OW"}, FP_R),
        # живлення
        std("X1", "Connector:Screw_Terminal_01x03", "B1 B2 GND (L01 L02 P28)", 340, 60, {"1": "B1", "2": "B2", "3": "GND"}, FP_SCREW.format(n=3)),
        std("VD1", "Device:D_Schottky", "SS34 / 1N5819", 380, 55, {"1": "VIN_DC", "2": "B1"}, FP_D),
        std("VD2", "Device:D_Schottky", "SS34 / 1N5819", 380, 65, {"1": "VIN_DC", "2": "B2"}, FP_D),
        std("X2", "Connector:Screw_Terminal_01x02", "VIN_DC GND → mDC5 IN (L03 L04)", 340, 95, {"1": "VIN_DC", "2": "GND"}, FP_SCREW.format(n=2)),
        mod("mDC5", "LM2596", "LM2596 → 5.0 V", 380, 110, {"IN+": "VIN_DC", "IN-": "GND", "OUT+": "+5V", "OUT-": "GND"}),
        std("X3", "Connector:Screw_Terminal_01x02", "+5V GND ← mDC5 OUT (L05 L06)", 340, 130, {"1": "+5V", "2": "GND"}, FP_SCREW.format(n=2)),
        std("#FLG6", "power:PWR_FLAG", "PWR_FLAG", 420, 80, {"1": "VIN_DC"}),
        # температура
        std("X4", "Connector:Screw_Terminal_01x03", "DS18B20 ×2: 3V3 DATA GND", 340, 175, {"1": "+3V3", "2": "OW", "3": "GND"}, FP_SCREW.format(n=3)),
        std("T1", "Sensor_Temperature:DS18B20", "DS18B20 Bat1", 380, 200, {"1": "GND", "2": "OW", "3": "+3V3"}, "", on_board=False),
        std("T2", "Sensor_Temperature:DS18B20", "DS18B20 Bat2", 380, 240, {"1": "GND", "2": "OW", "3": "+3V3"}, "", on_board=False),
    )
    return [power, charge, sense, logic]


def write_project(sheets: list[Sheet]):
    root_uuid = uid()
    root = Sheet("batman", "batman — менеджер двох акумуляторів (LiFePO₄ 8S + Pb 24 В)", paper="A4")
    root.text("Схема з docs/connections.md; генерується hardware/schematic/gen.py. Аркуші: power, charge, sense, logic.", 20, 30)
    root.text("Імена ланцюгів: вузли (B1, B2, LOAD+, CHG, GND, +5V, +3V3, +3V3_SENS) і номери проводів P##/L## для двоточкових з'єднань.", 20, 34)
    (HERE / f"{PROJECT}.kicad_sch").write_text(root.render(root_uuid, 1, root=True, sheets=sheets), encoding="utf-8")
    all_labels: dict[str, int] = {}
    for i, sh in enumerate(sheets):
        (HERE / f"{sh.name}.kicad_sch").write_text(sh.render(root_uuid, i + 2), encoding="utf-8")
        for k, v in sh.labels.items():
            all_labels[k] = all_labels.get(k, 0) + v
    single = sorted(k for k, v in all_labels.items() if v < 2)
    if single:
        print("УВАГА: мітки з одним входженням:", ", ".join(single))

    lib = ["kicad_symbol_lib", ["version", "20251024"], ["generator", q("batman_gen")], ["generator_version", q("1.0")]]
    for name, sym in MODULES.items():
        s = [c for c in sym]
        s[1] = q(name)
        lib.append(s)
    (HERE / "lib").mkdir(exist_ok=True)
    (HERE / "lib" / "batman.kicad_sym").write_text(sx(lib) + "\n", encoding="utf-8")
    (HERE / "sym-lib-table").write_text('(sym_lib_table\n  (version 7)\n  (lib (name "batman")(type "KiCad")(uri "${KIPRJMOD}/lib/batman.kicad_sym")(options "")(descr "модулі batman"))\n)\n', encoding="utf-8")
    (HERE / "fp-lib-table").write_text('(fp_lib_table\n  (version 7)\n  (lib (name "batman")(type "KiCad")(uri "${KIPRJMOD}/../pcb/batman.pretty")(options "")(descr "футпринти batman"))\n)\n', encoding="utf-8")
    pro = HERE / f"{PROJECT}.kicad_pro"
    if not pro.exists():
        pro.write_text('{\n  "meta": { "filename": "batman.kicad_pro", "version": 1 },\n  "schematic": { "legacy_lib_dir": "", "legacy_lib_list": [] },\n  "sheets": [],\n  "text_variables": {}\n}\n', encoding="utf-8")
    print("OK:", ", ".join(f"{sh.name}.kicad_sch" for sh in sheets), "+ batman.kicad_sch, lib/batman.kicad_sym")
    write_bom(sheets)


PLATE_B = {"C1", "C2", "D3", "XLP", "XGND"}

BOM_WHAT = {  # lib_id → що це (для стандартних символів); модулі беруть Description з MODULES
    "Device:R": "резистор 0,25 Вт (1206 або вивідний — суміщене місце)",
    "Device:C": "керамічний конденсатор",
    "Device:C_Polarized": "електроліт 50 В, буфер шини LOAD+",
    "Device:D_Schottky": "Шотткі «АБО» живлення логіки з B1/B2",
    "Device:D_TVS": "TVS 33 В на шині LOAD+ (опція, місце передбачене)",
    "Device:Fuse": "запобіжник ATO 15 А в тримачі (задня панель)",
    "Transistor_BJT:BC547": "NPN — ключ входу реле (будь-який малопотужний NPN)",
    "Transistor_BJT:BC557": "PNP — ключ живлення датчиків (SENS_PWR)",
    "Connector:Screw_Terminal_01x01": "клемник 5 мм",
    "Connector:Screw_Terminal_01x02": "клемник 5 мм / силова клема панелі",
    "Connector:Screw_Terminal_01x03": "клемник 5 мм",
    "Connector:Screw_Terminal_01x05": "клемник 5 мм (мінус-шина)",
    "Connector_Generic:Conn_01x02": "гребінка 2,54 (пряма або кутова за місцем)",
    "Connector_Generic:Conn_01x03": "гребінка 2,54",
    "Connector_Generic:Conn_01x04": "гребінка 2,54",
    "Connector_Generic:Conn_01x05": "гребінка 2,54",
    "Connector_Generic:Conn_01x06": "гребінка 2,54 (резерв SPI)",
    "Switch:SW_Push": "кнопка 12 мм на передній панелі",
    "Sensor_Temperature:DS18B20": "DS18B20 у гільзі з кабелем",
    "power:PWR_FLAG": None,
}


def part_place(p: Part) -> str:
    if p.ref.startswith("#"):
        return ""
    if p.lib_id.startswith("batman:"):
        return "плата A (у гнізді)" if p.on_board else "модуль, дюпони/дроти"
    if p.ref in PLATE_B:
        return "плата B"
    return "плата A" if p.on_board else "панель / корпус"


def write_bom(sheets: list[Sheet]):
    import json
    parts = [p for sh in sheets for p in sh.parts if not p.ref.startswith("#")]
    groups: dict[tuple, list[Part]] = {}
    for p in parts:
        groups.setdefault((part_place(p), p.lib_id, p.value), []).append(p)
    order = {"плата A": 0, "плата A (у гнізді)": 1, "плата B": 2, "модуль, дюпони/дроти": 3, "панель / корпус": 4}
    rows = []
    for (place, lib_id, value), ps in sorted(groups.items(), key=lambda kv: (order[kv[0][0]], kv[0][1], kv[0][2])):
        if lib_id.startswith("batman:"):
            what = next(c[2].strip('"') for c in MODULES[lib_id.split(":")[1]] if isinstance(c, list) and c[0] == "property" and c[1] == '"Description"')
        else:
            what = BOM_WHAT.get(lib_id, lib_id)
        def refkey(r):
            m = re.search(r"(\d+)$", r)
            return (r[: m.start()] if m else r, int(m.group(1)) if m else 0)
        refs = ", ".join(sorted((p.ref for p in ps), key=refkey))
        rows.append(f"| {refs} | {value} — {what} | {len(ps)} | {place} | є |")
    out = ["# BOM — комплектувальний список", "",
           "Генерується `hardware/schematic/gen.py` зі схеми; характеристики й наявність модулів — [docs/components.md](../../docs/components.md). Усе в наявності (за словами власника); колонка «Статус» міняється на «купити» вручну, якщо шухляда не підтвердила.", "",
           "| Позначення | Що це | К-сть | Де | Статус |", "|---|---|---|---|---|", *rows, "",
           "Поза схемою: дріт 2,5 мм² (червоний/помаранчевий/чорний/жовтий, ~3 м разом), дріт 0,5 мм² (~1 м), дюпони прямі мама–мама (~30 шт.), термозбіжна трубка, гвинти M3 і вставки (корпус)."]
    (HERE.parent / "bom").mkdir(exist_ok=True)
    (HERE.parent / "bom" / "bom.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    # список для pcb/gen_pcb.py: тільки те, що сидить на платах A/B
    pcb = [{"ref": p.ref, "value": p.value, "footprint": p.fp, "board": "B" if p.ref in PLATE_B else "A",
            "lib_id": p.lib_id} for p in parts if p.on_board and p.fp]
    (HERE.parent / "pcb").mkdir(exist_ok=True)
    (HERE.parent / "pcb" / "parts.json").write_text(json.dumps(pcb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BOM: {len(rows)} рядків -> bom/bom.md; {len(pcb)} компонентів -> pcb/parts.json")


if __name__ == "__main__":
    if not KICAD_SYMBOLS.exists():
        sys.exit(f"Не знайдено бібліотек KiCad: {KICAD_SYMBOLS} (задайте KICAD_SYMBOLS)")
    write_project(build())
