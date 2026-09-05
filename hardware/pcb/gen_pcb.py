"""Каркаси плат A (logic) і B (bus) для ЛУТ — з нетлиста схеми, через pcbnew KiCad 10.

Запуск ТІЛЬКИ пітоном з KiCad (у ньому є модуль pcbnew):
    cd hardware/pcb
    & "$env:LOCALAPPDATA\\Programs\\KiCad\\10.0\\bin\\python.exe" gen_pcb.py

Перед цим: python ../schematic/gen.py  і  kicad-cli sch export netlist --format kicadsexpr -o ../schematic/batman.net ../schematic/batman.kicad_sch

Що робить: один мідний шар (F.Cu; друк дзеркально), правила ЛУТ (доріжка ≥ 0,7, зазор ≥ 0,5), пади/отвори під конкретний
компонент за таблицею plan.md 2.2, контур, кріпильні отвори, стартове розміщення, ланцюги з нетлиста, заливка GND.
Трасування — вручну в pcbnew; повторний запуск ПЕРЕЗАПИСУЄ plate_A/plate_B.kicad_pcb (розведення втрачається) — тому
після початку трасування генератор більше не запускати, а зміни схеми вносити через «Update PCB from Schematic».
"""
import json
import os
import sys
from pathlib import Path

try:
    import pcbnew
except ImportError:
    sys.exit("Потрібен python з KiCad: %LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe gen_pcb.py")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "schematic"))
import gen  # noqa: E402  (парсер S-виразів)

FP_ROOT = Path(os.environ.get("KICAD_FOOTPRINTS", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/share/kicad/footprints"))
MY_LIB = HERE / "batman.pretty"
mm = pcbnew.FromMM
V = pcbnew.VECTOR2I

# ЛУТ: отвір / пад за типом компонента (plan.md 2.2)
PAD_RULES = [  # (фрагмент імені бібліотеки/футпринта, drill, pad)
    ("TerminalBlock", 1.5, 3.5),
    ("DO-41", 1.1, 2.4), ("DO-15", 1.1, 2.4),
    ("CP_Radial", 0.9, 2.4),
    ("MountingHole", None, None),
    ("", 0.8, 2.0),  # резистори, кераміка, гребінки, гнізда, TO-92
]
TRACK_MIN, CLEARANCE, TRACK_SIGNAL, TRACK_POWER = 0.7, 0.5, 1.0, 3.0
DEVKIT_ROW_PITCH = 25.4  # DevKitC 38 (ширина 28 мм) — перевірити на своєму екземплярі: вузькі клони мають 22,86

# ------------------------------------------------------------------ розміщення
# Кожен рядок: ("row", y_top, x_left, rot, [refs])  — вкладає зліва направо, габарит береться з футпринта;
#               ("col", x_left, y_top, rot, [refs])  — зверху вниз;  ("at", x, y, rot, [ref]) — лівий верхній кут габариту в (x, y).
# Від'ємне x/y — від правого/нижнього краю (правий або нижній край габариту там). GAP — проміжок між габаритами.
GAP = 1.5
LAYOUT_A = [  # плата A: DevKitC зліва (USB до низу), гребінки датчиків зверху, клемники справа, решта гребінок знизу
    ("at", 8, 9, 0, ["mMCU"]),
    ("row", 2, 40, 90, ["J3", "J4", "J5", "J8"]),
    ("col", -2, 15, 90, ["X1", "X2", "X3", "X5"]),
    ("at", 8, -2, 0, ["X4"]),
    ("row", -2, 26, 90, ["J6", "J7", "J9", "J10", "J11", "J12"]),
    ("col", 40, 15, 0, ["mADC"]),
    ("row", 15, 46, 0, ["R7", "C7", "C8"]),
    ("row", 20, 46, 0, ["R8", "R9", "C9"]),
    ("row", 25, 46, 0, ["R1", "R2", "C3"]),
    ("row", 30, 46, 0, ["R3", "R4", "C4"]),
    ("row", 35, 46, 0, ["R5", "R6", "C5"]),
    ("row", 40, 46, 0, ["R10", "R11", "C6"]),
    ("row", 45, 46, 0, ["R12", "R13", "Q3"]),
    ("row", 52, 46, 0, ["R14", "R15", "Q1"]),
    ("row", 59, 46, 0, ["R16", "R17", "Q2"]),
    ("row", 66, 40, 0, ["R18", "VD1", "VD2"]),
]
LAYOUT_B = [
    ("row", 1, 14.7, 0, ["XLP"]),
    ("row", -1, 9.7, 0, ["XGND"]),
    ("row", 11, 8, 0, ["C1", "C2", "D3"]),
]
SIZE = {"A": (100, 80), "B": (46, 30)}
HOLES = {"A": [(4, 4), (96, 4), (4, 76), (96, 76)], "B": [(4, 4), (42, 26)]}
FP_OVERRIDE = {"Package_TO_SOT_THT:TO-92_Inline": "Package_TO_SOT_THT:TO-92_Inline_Wide"}  # крок 2,54 — інакше пади 2 мм зливаються


def bbox_mm(fp):
    b = fp.GetBoundingBox(False)
    return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))


def move_bbox_to(fp, left, top):
    l, t, _, _ = bbox_mm(fp)
    p = fp.GetPosition()
    fp.SetPosition(V(p.x + mm(left - l), p.y + mm(top - t)))


def place_all(layout, fps: dict, size):
    """Розкладає футпринти за LAYOUT; повертає список нерозміщених."""
    W, H = size
    placed = set()
    for kind, a, b, rot, refs in layout:
        items = [fps[r] for r in refs if r in fps]
        for fp in items:
            fp.SetOrientationDegrees(rot)
        if kind == "at":
            x, y = a, b
            for fp in items:
                l, t, r, bt = bbox_mm(fp)
                move_bbox_to(fp, x if x >= 0 else W + x - (r - l), y if y >= 0 else H + y - (bt - t))
        elif kind == "row":
            y_top, x = a, b
            for fp in items:
                l, t, r, bt = bbox_mm(fp)
                w, h = r - l, bt - t
                move_bbox_to(fp, x, y_top if y_top >= 0 else H + y_top - h)
                x += w + GAP
        else:  # col
            x_left, y = a, b
            for fp in items:
                l, t, r, bt = bbox_mm(fp)
                w, h = r - l, bt - t
                move_bbox_to(fp, x_left if x_left >= 0 else W + x_left - w, y)
                y += h + GAP
        placed.update(r for r in refs if r in fps)
    return [r for r in fps if r not in placed]


def report_overlaps(board, size):
    W, H = size
    fps = list(board.Footprints())
    boxes = {f.GetReference(): bbox_mm(f) for f in fps}
    for ref, (l, t, r, b) in boxes.items():
        if l < 0.5 or t < 0.5 or r > W - 0.5 or b > H - 0.5:
            print(f"  за межами плати: {ref} ({l:.1f},{t:.1f})–({r:.1f},{b:.1f})")
    refs = list(boxes)
    for i, a in enumerate(refs):
        for c in refs[i + 1:]:
            l1, t1, r1, b1 = boxes[a]
            l2, t2, r2, b2 = boxes[c]
            if l1 < r2 and l2 < r1 and t1 < b2 and t2 < b1:
                print(f"  перетин: {a} × {c}")


def load_fp(lib_id: str):
    lib_id = FP_OVERRIDE.get(lib_id, lib_id)
    lib, name = lib_id.split(":")
    if lib == "batman":
        return pcbnew.FootprintLoad(str(MY_LIB), name)
    return pcbnew.FootprintLoad(str(FP_ROOT / f"{lib}.pretty"), name)


def devkit_socket_footprint():
    """Два ряди по 19 гнізд на відстані DEVKIT_ROW_PITCH; нумерація як у символі: 1–19 лівий ряд, 20–38 правий."""
    fp = pcbnew.FOOTPRINT(pcbnew.BOARD())
    fp.SetFPID(pcbnew.LIB_ID("batman", "ESP32_DevKitC_38_Socket"))
    fp.SetReference("J1")
    fp.SetValue("DevKitC socket")
    for col in range(2):
        for row in range(19):
            pad = pcbnew.PAD(fp)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetSize(V(mm(2.0), mm(2.0)))
            pad.SetDrillSize(V(mm(0.8), mm(0.8)))
            pad.SetLayerSet(pcbnew.PAD.PTHMask())
            pad.SetNumber(str(col * 19 + row + 1))
            pad.SetPosition(V(mm(col * DEVKIT_ROW_PITCH), mm(row * 2.54)))
            fp.Add(pad)
    for ly, w in ((pcbnew.F_SilkS, 0.15), (pcbnew.F_CrtYd, 0.05)):
        r = pcbnew.PCB_SHAPE(fp)
        r.SetShape(pcbnew.SHAPE_T_RECT)
        r.SetLayer(ly)
        r.SetWidth(mm(w))
        r.SetStart(V(mm(-(28 - DEVKIT_ROW_PITCH) / 2), mm(-3)))
        r.SetEnd(V(mm(DEVKIT_ROW_PITCH + (28 - DEVKIT_ROW_PITCH) / 2), mm(18 * 2.54 + 3)))
        fp.Add(r)
    fp.Reference().SetPosition(V(mm(DEVKIT_ROW_PITCH / 2), mm(-4.5)))
    fp.Value().SetPosition(V(mm(DEVKIT_ROW_PITCH / 2), mm(18 * 2.54 + 4.5)))
    MY_LIB.mkdir(exist_ok=True)
    pcbnew.PCB_IO_KICAD_SEXPR().FootprintSave(str(MY_LIB), fp)
    return fp


def read_netlist(path: Path) -> dict[str, dict[str, str]]:
    """{ref: {pin: net}}"""
    tree, _ = gen.parse(gen.tokenize(path.read_text(encoding="utf-8")))
    out: dict[str, dict[str, str]] = {}
    nets = next(c for c in tree[0] if isinstance(c, list) and c[0] == "nets")
    for net in nets[1:]:
        name = next(c for c in net if isinstance(c, list) and c[0] == "name")[1].strip('"')
        if name.startswith("unconnected-"):
            continue
        for node in net:
            if isinstance(node, list) and node[0] == "node":
                ref = next(c for c in node if isinstance(c, list) and c[0] == "ref")[1].strip('"')
                pin = next(c for c in node if isinstance(c, list) and c[0] == "pin")[1].strip('"')
                out.setdefault(ref, {})[pin] = name
    return out


def lut_pads(fp, fp_name: str):
    for frag, drill, pad_d in PAD_RULES:
        if frag in fp_name:
            if drill is None:
                return
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
                    pad.SetDrillSize(V(mm(drill), mm(drill)))
                    pad.SetSize(V(mm(pad_d), mm(pad_d)))
            return


def setup_rules(board):
    board.SetCopperLayerCount(1)
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = mm(TRACK_MIN)
    ds.m_MinClearance = mm(CLEARANCE)
    ds.m_MinThroughDrill = mm(0.8)
    ds.m_ViasMinSize = mm(2.0)
    ds.m_CopperEdgeClearance = mm(1.0)
    try:
        ns = ds.m_NetSettings
        dflt = ns.GetDefaultNetclass()
        dflt.SetClearance(mm(CLEARANCE))
        dflt.SetTrackWidth(mm(TRACK_SIGNAL))
        power = pcbnew.NETCLASS("power")
        power.SetClearance(mm(CLEARANCE))
        power.SetTrackWidth(mm(TRACK_POWER))
        ns.SetNetclass("power", power)
        for pat in ("B1", "B2", "LOAD+", "GND", "VIN_DC", "+5V"):
            ns.SetNetclassPatternAssignment(pat, "power")
    except Exception as e:  # API класів ланцюгів міняється між версіями — правила все одно задані вище
        print("netclass:", e)


def build_board(which: str, layout: list, parts: list[dict], nets: dict[str, dict[str, str]]):
    board = pcbnew.BOARD()
    setup_rules(board)
    w, h = SIZE[which]
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(mm(0.1))
    edge.SetStart(V(0, 0))
    edge.SetEnd(V(mm(w), mm(h)))
    board.Add(edge)

    netinfo: dict[str, pcbnew.NETINFO_ITEM] = {}

    def net(name):
        if name not in netinfo:
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
            netinfo[name] = ni
        return netinfo[name]

    for i, (x, y) in enumerate(HOLES[which], 1):
        fp = load_fp("MountingHole:MountingHole_3.2mm_M3")
        fp.SetReference(f"H{i}")
        fp.SetPosition(V(mm(x), mm(y)))
        board.Add(fp)

    fps: dict[str, pcbnew.FOOTPRINT] = {}
    for p in parts:
        fp = load_fp(p["footprint"])
        if fp is None:
            sys.exit(f"немає футпринта {p['footprint']} для {p['ref']}")
        fp.SetReference(p["ref"])
        fp.SetValue(p["value"])
        lut_pads(fp, p["footprint"])
        board.Add(fp)
        fps[p["ref"]] = fp
        pins = nets.get(p["ref"], {})
        for pad in fp.Pads():
            n = pins.get(pad.GetNumber())
            if n:
                pad.SetNet(net(n))
    missing = place_all(layout, fps, (w, h))
    if missing:
        print(f"плата {which}: не розміщені (додай у LAYOUT_{which}):", ", ".join(missing))
    report_overlaps(board, (w, h))

    if "GND" in netinfo:
        zone = pcbnew.ZONE(board)
        zone.SetLayer(pcbnew.F_Cu)
        zone.SetNet(netinfo["GND"])
        zone.SetLocalClearance(mm(CLEARANCE))
        zone.SetMinThickness(mm(TRACK_MIN))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        o = zone.Outline()
        o.NewOutline()
        for px, py in ((1, 1), (w - 1, 1), (w - 1, h - 1), (1, h - 1)):
            o.Append(mm(px), mm(py))
        board.Add(zone)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    for t, y, size in ((f"batman плата {which} — ЛУТ, 1 шар, друк дзеркально", h + 3, 1.2),):
        txt = pcbnew.PCB_TEXT(board)
        txt.SetText(t)
        txt.SetLayer(pcbnew.Cmts_User)
        txt.SetPosition(V(mm(2), mm(y)))
        txt.SetTextSize(V(mm(size), mm(size)))
        txt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        board.Add(txt)

    out = HERE / f"plate_{which}.kicad_pcb"
    pcbnew.SaveBoard(str(out), board)
    print(f"OK: {out.name} — {len(parts) - len(missing)} компонентів, {len(netinfo)} ланцюгів")


def main():
    parts = json.loads((HERE / "parts.json").read_text(encoding="utf-8"))
    netfile = HERE.parent / "schematic" / "batman.net"
    if not netfile.exists():
        sys.exit("немає schematic/batman.net — експортуй нетліст kicad-cli (див. заголовок файлу)")
    nets = read_netlist(netfile)
    devkit_socket_footprint()
    build_board("A", LAYOUT_A, [p for p in parts if p["board"] == "A"], nets)
    build_board("B", LAYOUT_B, [p for p in parts if p["board"] == "B"], nets)


if __name__ == "__main__":
    main()
