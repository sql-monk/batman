from collections import defaultdict
import csv
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pcbnew
import sexpdata
from sexpdata import Symbol as Token

from pcb import ROOT, Router, add_assembly_guides, add_jumper, build, position
from circuit import circuit
from schematic import generate as generate_schematic
from cad_common import set_lut_rules, track


REPORTS = ROOT / "reports"


def form(name, *values):
    return [Token(name), *values]


def prepare(board=None, routing_rules=None):
    board = board if board is not None else build(route=False)
    REPORTS.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(REPORTS / "unrouted.kicad_pcb"), board)
    shutil.copy2(ROOT / "batman.kicad_pro", REPORTS / "unrouted.kicad_pro")
    shutil.copy2(ROOT / "batman.kicad_dru", REPORTS / "unrouted.kicad_dru")
    layers = ["F.Cu", "B.Cu"]
    bounds = board.GetBoardEdgesBoundingBox()
    structure = form("structure", *[form("layer", layer, form("type", Token("signal"))) for layer in layers],
                     form("boundary", form("rect", Token("pcb"), round(bounds.GetX()/1000),
                          -round((bounds.GetY()+bounds.GetHeight())/1000),
                          round((bounds.GetX()+bounds.GetWidth())/1000), -round(bounds.GetY()/1000))),
                     form("via", "WireHole"), form("rule", form("width", 700), form("clearance", 500)))
    if routing_rules:
        structure[-1].extend([
            form("clearance", 650, form("type", Token("wire_wire"))),
            form("clearance", 650, form("type", Token("wire_pin"))),
            form("clearance", 650, form("type", Token("wire_smd"))),
        ])
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            bounds = zone.Outline().BBox()
            for layer in layers:
                structure.append(form("keepout", zone.GetZoneName(), form("rect", layer,
                    round(bounds.GetX() / 1000), round(-(bounds.GetY() + bounds.GetHeight()) / 1000),
                    round((bounds.GetX() + bounds.GetWidth()) / 1000), round(-bounds.GetY() / 1000))))
    placement = form("placement")
    library = form("library")
    nets = defaultdict(list)
    for item in sorted(board.GetFootprints(), key=lambda footprint: footprint.GetReference()):
        ref = item.GetReference()
        if ref.startswith("W"):
            continue
        origin_x, origin_y = position(item)
        image = form("image", ref)
        placement.append(form("component", ref, form("place", ref, round(origin_x * 1000), round(-origin_y * 1000), Token("front"), 0)))
        groups = defaultdict(list)
        for pad in sorted(item.Pads(), key=lambda contact: (contact.GetNumber(), contact.GetAttribute())):
            groups[pad.GetNumber()].append(pad)
        for index, pads in enumerate(groups.values()):
            pad = next((contact for contact in pads if contact.GetAttribute() == pcbnew.PAD_ATTRIB_PTH), pads[0])
            if ref == "NT1" and pad.GetNumber() == "1":
                continue
            pad_x, pad_y = position(pad)
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                for layer in layers:
                    structure.append(form("keepout", ref, form("circle", layer, 3400, round(pad_x * 1000), round(-pad_y * 1000))))
                continue
            pin = f"p{index}"
            padstack = form("padstack", ref + pin)
            for layer in layers:
                contacts = [contact for contact in pads if contact.GetLayerSet().Contains(pcbnew.F_Cu if layer == "F.Cu" else pcbnew.B_Cu)]
                if not contacts:
                    continue
                rectangles = []
                for contact in contacts:
                    size_x, size_y = contact.GetSize().x / 1000, contact.GetSize().y / 1000
                    if abs(contact.GetOrientationDegrees() % 180 - 90) < 0.01:
                        size_x, size_y = size_y, size_x
                    contact_x, contact_y = position(contact)
                    offset_x, offset_y = (contact_x - pad_x) * 1000, (pad_y - contact_y) * 1000
                    rectangles.append((offset_x - size_x / 2, offset_y - size_y / 2, offset_x + size_x / 2, offset_y + size_y / 2))
                shape = form("rect", layer, min(rect[0] for rect in rectangles), min(rect[1] for rect in rectangles),
                             max(rect[2] for rect in rectangles), max(rect[3] for rect in rectangles))
                if len(contacts) == 1 and pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                    shape = form("circle", layer, size_x)
                padstack.append(form("shape", shape))
            padstack.append(form("attach", Token("off")))
            library.append(padstack)
            image.append(form("pin", ref + pin, pin, round((pad_x - origin_x) * 1000), round((origin_y - pad_y) * 1000)))
            if pad.GetNetname() and not pad.GetNetname().startswith("unconnected-"):
                nets[pad.GetNetname()].append(Token(ref + "-" + pin))
        library.append(image)
    library.append(form("padstack", "WireHole", *[form("shape", form("circle", layer, 2400)) for layer in layers], form("attach", Token("off"))))
    classes = defaultdict(list)
    for net in nets:
        classes[(routing_rules or {}).get(net, (700, 500))].append(net)
    network = form("network", *[form("net", net, form("pins", *pins)) for net, pins in nets.items()],
                   *[form("class", f"width{width}_gap{clearance}", *names,
                          form("circuit", form("use_via", "WireHole")),
                         form("rule", form("width", width),
                             *([form("clearance", clearance)] if clearance > 650 or not routing_rules else [])))
                     for (width, clearance), names in classes.items()])
    design = form("pcb", "batman", form("resolution", Token("um"), 10), form("unit", Token("um")),
                  structure, placement, library, network, form("wiring"))
    (REPORTS / "routing.dsn").write_text(sexpdata.dumps(design), encoding="utf-8")
    print(f"Exported {len(nets)} nets, {len(list(board.GetFootprints()))} footprints")


def children(node, name):
    return [child for child in node if isinstance(child, list) and child and str(child[0]) == name]


def copper_groups(board):
    board.BuildConnectivity()
    connectivity = board.GetConnectivity()
    items = [pad for item in board.GetFootprints() for pad in item.Pads()] + list(board.GetTracks())
    by_id = {item.m_Uuid.AsString(): item for item in items}
    parent = {key: key for key in by_id}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(first, second):
        parent[root(first)] = root(second)

    for key, item in by_id.items():
        for other in connectivity.GetConnectedItems(item):
            other_key = other.m_Uuid.AsString()
            if other_key in by_id:
                join(key, other_key)
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            continue
        polygons = zone.GetFilledPolysList(pcbnew.B_Cu)
        anchors = {}
        for key, item in by_id.items():
            if item.GetNetCode() != zone.GetNetCode():
                continue
            points = [item.GetPosition()] if isinstance(item, pcbnew.PAD) else [item.GetStart(), item.GetEnd()]
            for index in range(polygons.OutlineCount()):
                if any(polygons.Contains(point, index) for point in points):
                    if index in anchors:
                        join(key, anchors[index])
                    anchors[index] = key
    groups = defaultdict(lambda: defaultdict(list))
    for key, item in by_id.items():
        if isinstance(item, pcbnew.PAD) and item.GetNetCode() and not item.GetNetname().startswith("unconnected-"):
            groups[item.GetNetname()][root(key)].append(item)
    return {net: list(clusters.values()) for net, clusters in groups.items()}


def finish_copper(board, routing_rules=None):
    added = 0
    while True:
        candidates = []
        for net, clusters in copper_groups(board).items():
            for index, first in enumerate(clusters):
                for second in clusters[index + 1:]:
                    pairs = sorted((math.dist(position(left), position(right)), position(left), position(right))
                                   for left in first for right in second)
                    candidates.extend((distance, net, start, end) for distance, start, end in pairs[:4])
        success = False
        for _, net, start, end in sorted(candidates):
            width, clearance = (routing_rules or {}).get(net, (700, 500))
            router = Router(board, width / 1000, clearance / 1000)
            for segment in board.GetTracks():
                first = pcbnew.ToMM(segment.GetStart().x) - 30, pcbnew.ToMM(segment.GetStart().y) - 30
                second = pcbnew.ToMM(segment.GetEnd().x) - 30, pcbnew.ToMM(segment.GetEnd().y) - 30
                other_clearance = (routing_rules or {}).get(segment.GetNetname(), (700, 500))[1]
                margin = pcbnew.ToMM(segment.GetWidth()) / 2 + width / 2000 + max(clearance, other_clearance) / 1000 + 0.075
                steps = max(1, math.ceil(math.dist(first, second) / 0.1))
                for index in range(steps + 1):
                    fraction = index / steps
                    router.paint(first[0] + (second[0] - first[0]) * fraction,
                                 first[1] + (second[1] - first[1]) * fraction,
                                 margin, margin, segment.GetNetCode())
            first = start[0] - 30, start[1] - 30
            second = end[0] - 30, end[1] - 30
            route = router.find(first, second, board.FindNet(net).GetNetCode())
            if route:
                router.commit(route, first, second, board.FindNet(net).GetNetCode())
                added += 1
                success = True
                break
        if not success:
            break
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print(f"Additional copper connections: {added}; remaining groups: "
          f"{sum(len(groups) - 1 for groups in copper_groups(board).values())}")


def finish_wires(board, prefix="W"):
    wires = []
    for net, clusters in sorted(copper_groups(board).items()):
        parents = list(range(len(clusters)))

        def root(index):
            while parents[index] != index:
                index = parents[index]
            return index

        edges = []
        for index, first in enumerate(clusters):
            for other_index in range(index + 1, len(clusters)):
                options = []
                for left in first:
                    for right in clusters[other_index]:
                        length = math.dist(position(left), position(right))
                        cost = length + sum(8 for pad in [left, right] if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD)
                        options.append((cost, position(left), position(right), length))
                cost, start, end, length = min(options)
                edges.append((cost, index, other_index, start, end, length))
        for _, first_index, second_index, start, end, length in sorted(edges):
            if root(first_index) == root(second_index):
                continue
            parents[root(first_index)] = root(second_index)
            ref = f"{prefix}{len(wires) + 1}"
            add_jumper(board, ref, net, start, end, (True, True))
            wires.append([ref, net, round(start[0] - 30, 4), round(start[1] - 30, 4),
                          round(end[0] - 30, 4), round(end[1] - 30, 4), round(length, 2),
                          "existing pad", "existing pad"])
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print(f"Added {len(wires)} physical insulated wires")
    return wires


def save_candidate(board, wires, publish=False):
    set_lut_rules(board)
    add_assembly_guides(board)
    parts = circuit()
    by_ref = {part.ref: part for part in parts}
    for item in board.GetFootprints():
        if item.GetReference() in by_ref:
            item.SetValue(by_ref[item.GetReference()].value)
    directory = ROOT if publish else REPORTS
    name = "batman" if publish else "candidate"
    library = directory / "Batman.pretty"
    library.mkdir(exist_ok=True)
    plugin = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    for item in board.GetFootprints():
        plugin.FootprintSave(str(library), item)
    (directory / "fp-lib-table").write_text('(fp_lib_table (version 7) (lib (name "Batman") (type "KiCad") (uri "${KIPRJMOD}/Batman.pretty") (options "") (descr "Local single-sided LUT footprints")))\n', encoding="utf-8")
    pcbnew.SaveBoard(str(directory / (name + ".kicad_pcb")), board)
    if not publish:
        shutil.copy2(ROOT / "batman.kicad_pro", directory / (name + ".kicad_pro"))
        shutil.copy2(ROOT / "batman.kicad_dru", directory / (name + ".kicad_dru"))
    if wires is not None:
        with (directory / "jumpers.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Ref", "Net", "A_X1_mm", "A_Y1_mm", "X2_mm", "Y2_mm", "Wire_cut_min_mm", "End1", "End2"])
            writer.writerows(wires)
    if publish:
        for part in parts:
            if part.board:
                part.footprint = "Batman:LUT_" + part.ref
        generate_schematic(parts)


def import_session(wire_prefix="W", routing_rules=None):
    board = pcbnew.LoadBoard(str(REPORTS / "unrouted.kicad_pcb"))
    session = sexpdata.loads((REPORTS / "routing.ses").read_text(encoding="utf-8"))
    routes = children(session, "routes")[0]
    resolution = children(routes, "resolution")[0]
    assert str(resolution[1]) == "um", resolution
    scale = 1000 * resolution[2]
    network = children(routes, "network_out")[0]
    count = 0
    for net in children(network, "net"):
        for wire in children(net, "wire"):
            path = children(wire, "path")[0]
            assert str(path[1]) == "B.Cu", path[1]
            points = [(path[index] / scale, -path[index + 1] / scale) for index in range(3, len(path), 2)]
            for start, end in zip(points, points[1:]):
                track(board, str(net[1]), start, end, path[2] / scale)
                count += 1
        assert not children(net, "via"), str(net[1])
    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.B_Cu)
    zone.SetNet(board.FindNet("GND"))
    zone.SetZoneName("GND_BOTTOM")
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zone.SetLocalClearance(pcbnew.FromMM(0.5))
    zone.SetThermalReliefGap(pcbnew.FromMM(0.5))
    zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.7))
    zone.SetMinThickness(pcbnew.FromMM(0.7))
    polygon = zone.Outline()
    polygon.NewOutline()
    bounds = board.GetBoardEdgesBoundingBox()
    left, top = pcbnew.ToMM(bounds.GetX()) + 0.6, pcbnew.ToMM(bounds.GetY()) + 0.6
    right = pcbnew.ToMM(bounds.GetX() + bounds.GetWidth()) - 0.6
    bottom = pcbnew.ToMM(bounds.GetY() + bounds.GetHeight()) - 0.6
    for x, y in [(left, top), (right, top), (right, bottom), (left, bottom)]:
        polygon.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(zone)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    if "--finish-copper" in sys.argv:
        finish_copper(board, routing_rules)
    wires = finish_wires(board, wire_prefix) if "--wire" in sys.argv else None
    save_candidate(board, wires, "--publish" in sys.argv)
    print(f"Imported {count} bottom-layer segments and filled GND")
    return board


def reroute(board=None, wire_prefix="W", routing_rules=None, optimize=False):
    if routing_rules is None and "Room around tracks" in (ROOT / "batman.kicad_dru").read_text(encoding="utf-8"):
        routing_rules = {net: (1200, 1000) if net in {"B1", "B2", "LOAD+", "VIN_DC"}
                         else (1000, 650) if net.startswith("+") or net == "GND" else (800, 650)
                         for part in circuit() for _, _, net, _ in part.pins if net}
    temporary = Path(os.environ["TEMP"])
    java = Path(os.environ.get("FREEROUTING_JAVA", str(temporary / "batman-jre25" / "jdk-25.0.4.1+1-jre" / "bin" / "java.exe")))
    jar = Path(os.environ.get("FREEROUTING_JAR", str(temporary / "freerouting-2.4.1.jar")))
    if not java.is_file() or not jar.is_file():
        raise FileNotFoundError("Set FREEROUTING_JAVA and FREEROUTING_JAR to Java 25 and Freerouting 2.4.1")
    prepare(board, routing_rules)
    with (REPORTS / "routing.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(java), "-jar", str(jar), "-de", str(REPORTS / "routing.dsn"),
            "-do", str(REPORTS / "routing.ses"), "--gui.enabled=false", "--api_server.enabled=false", "-da",
            "--user_data_path=" + str(temporary / "batman-freerouting"), "-mp", "20", "-mt", "1",
            "--router.fanout.enabled=false", "--router.copper_to_edge_clearance_um=600",
            "--router.hole_clearance_um=0", "--router.layers.routable=false,true",
            "--router.scoring.preferred_direction_trace_cost=1,1", "--router.scoring.undesired_direction_trace_cost=1,1",
            "--router.job_timeout=00:02:00", f"--router.optimizer.enabled={str(optimize).lower()}"], stdout=log, stderr=subprocess.STDOUT, check=True)
    print("\n".join((REPORTS / "routing.log").read_text(encoding="utf-8").splitlines()[-5:]))
    return import_session(wire_prefix, routing_rules)


if __name__ == "__main__":
    raise SystemExit("Use hardware/modular.py for the four-board design; this module provides routing helpers")