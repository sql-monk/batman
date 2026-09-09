from collections import Counter
from pathlib import Path
import csv
import json
import subprocess
import sys

import pcbnew

from circuit import circuit, validate
from pcb import ROOT, ORIGINS, position
from modular import LAYOUT, CABLES


OUTPUT = ROOT / "output"
REPORTS = ROOT / "reports"
CLI = Path(sys.executable).with_name("kicad-cli.exe")


def run(*arguments):
    subprocess.run([str(CLI), *map(str, arguments)], check=True)


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def check_board(board, parts):
    by_ref = {item.GetReference(): item for item in board.GetFootprints()}
    assert (ROOT / "batman.kicad_pro").is_file()
    project = json.loads((ROOT / "batman.kicad_pro").read_text(encoding="utf-8"))
    rules = project["board"]["design_settings"]["rules"]
    assert rules["min_clearance"] >= 0.5 and rules["min_track_width"] >= 0.7
    expected = {part.ref for part in parts if part.board}
    assert expected <= by_ref.keys()
    routes = list(board.GetTracks())
    assert all(not isinstance(item, pcbnew.PCB_VIA) for item in routes)
    assert all(item.GetLayer() == pcbnew.B_Cu for item in routes)
    assert all(pcbnew.ToMM(item.GetWidth()) >= 0.7 for item in routes)
    refined = "Room around tracks" in (ROOT / "batman.kicad_dru").read_text(encoding="utf-8")
    non_45_degree_segments = 0
    for item in routes:
        delta_x = abs(item.GetEnd().x - item.GetStart().x)
        delta_y = abs(item.GetEnd().y - item.GetStart().y)
        non_45_degree_segments += min(delta_x, delta_y, abs(delta_x - delta_y)) > 2
    if refined:
        assert all(item.GetLength() >= pcbnew.FromMM(1) for item in routes), "Track segment shorter than 1 mm"
        assert not non_45_degree_segments, "Track direction is not a multiple of 45 degrees"
    assert not ({"C1", "C2", "D3", "XLP1", "XGND1"} & by_ref.keys())
    for part in parts:
        if not part.board:
            continue
        footprint = by_ref[part.ref]
        expected_nets = {number: net or f"unconnected-({part.ref}-{name}-Pad{number})"
                         for number, name, net, _ in part.pins}
        assert {pad.GetNumber() for pad in footprint.Pads()} == expected_nets.keys(), part.ref
        for pad in footprint.Pads():
            assert pad.GetNetname() == expected_nets[pad.GetNumber()], (part.ref, pad.GetNumber())
            layers = pad.GetLayerSet()
            assert not any(layers.Contains(layer) for layer in [pcbnew.F_Mask, pcbnew.B_Mask, pcbnew.F_Paste, pcbnew.B_Paste])
        if part.kind == "R":
            assert len(list(footprint.Pads())) == 2
            for pad in footprint.Pads():
                assert pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                assert (pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y)) == (2.0, 1.6)
        if part.kind in ["C", "C_bus"]:
            assert len(list(footprint.Pads())) == 4, part.ref
    assert by_ref["NT1"].GetNetTiePadGroups()
    assert {pad.GetNetname() for pad in by_ref["J8"].Pads()} >= {"+5V_RELAY_VCC", "+5V_RELAY_COIL"}
    assert all(len(list(by_ref[ref].Pads())) == 3 for ref in ["J3", "J4", "J5"])
    assert not any(pad.GetNetname() == "FAULT" for item in board.GetFootprints() for pad in item.Pads())
    outlines = [item for item in board.GetDrawings() if item.GetLayer() == pcbnew.Edge_Cuts]
    assert len(outlines) == 4 * len(LAYOUT)
    sizes = []
    for key, settings in LAYOUT.items():
        origin, size = settings["origin"], tuple(settings["size"])
        points = []
        for item in outlines:
            for vector in [item.GetStart(), item.GetEnd()]:
                x, y = pcbnew.ToMM(vector.x), pcbnew.ToMM(vector.y)
                if origin[0] <= x <= origin[0] + size[0] and origin[1] <= y <= origin[1] + size[1]:
                    points.append((x, y))
        measured = max(x for x, _ in points) - min(x for x, _ in points), max(y for _, y in points) - min(y for _, y in points)
        assert measured == size
        sizes.append({"board": key, "size": measured})
    for segment in routes:
        coordinates = [(pcbnew.ToMM(vector.x), pcbnew.ToMM(vector.y)) for vector in [segment.GetStart(), segment.GetEnd()]]
        assert any(all(settings["origin"][0] <= x <= settings["origin"][0]+settings["size"][0]
                       and settings["origin"][1] <= y <= settings["origin"][1]+settings["size"][1] for x, y in coordinates)
                   for settings in LAYOUT.values()), "Copper track crosses between PCBs"
    assert not ({"J2", "J13", "C6", "C10"} & by_ref.keys())
    assert all(ref in by_ref for ref in ["J20", "J21", "J32", "J33"])
    assert any(zone.GetIsRuleArea() and zone.GetZoneName() == "ESP32_ANTENNA_NO_COPPER" for zone in board.Zones())
    assert any(not zone.GetIsRuleArea() and zone.GetNetname() == "GND" and zone.IsFilled()
               and zone.GetLayer() == pcbnew.B_Cu for zone in board.Zones())
    assert not any(ref.startswith("WH") for ref in by_ref)
    for ref in [reference for reference in by_ref if reference.startswith("W")]:
        assert by_ref[ref].GetDuplicatePadNumbersAreJumpers()
        assert len(list(by_ref[ref].Pads())) == 2
    return {"board_sizes_mm": sizes, "tracks": len(routes), "footprints": len(by_ref),
            "local_wire_jumpers": len([ref for ref in by_ref if ref.startswith("W") and not ref.startswith("WC")]),
            "interboard_cables": len(CABLES), "interboard_conductors": len([ref for ref in by_ref if ref.startswith("WC")]),
            "adc_addresses": ["0x48", "0x49"], "adc_location": "external modules",
            "adc_harnesses": 4, "adc_harness_conductors": 16, "copper_layers_routed": ["B.Cu"], "vias": 0,
            "signal_min_width_mm": min(pcbnew.ToMM(item.GetWidth()) for item in routes),
            "clearance_mm": 0.5, "track_clearance_mm": 0.65 if refined else 0.5,
            "raw_voltage_clearance_mm": 1.0 if refined else 0.5,
            "minimum_segment_length_mm": min(pcbnew.ToMM(item.GetLength()) for item in routes),
            "segments_below_1mm": sum(item.GetLength() < pcbnew.FromMM(1) for item in routes),
            "non_45_degree_segments": non_45_degree_segments,
            "bus_buffer": "external wiring"}


def tables(board, parts):
    destinations = {"J3": "mACS1", "J4": "mACS2", "J5": "mACS3", "J6": "mSW1", "J7": "mSW2",
                    "J8": "mREL2", "J9": "mDPS1", "J10": "mOLED1", "J11": "SW1", "X4": "T1"}
    by_ref = {part.ref: part for part in parts}
    cable_rows = []
    for ref, target in destinations.items():
        for number, _, net, _ in by_ref[ref].pins:
            target_pins = [name for _, name, target_net, _ in by_ref[target].pins if target_net == net]
            if ref == "J9" and net == "GND":
                target_pins = ["G_UART"]
            assert target_pins, (ref, number, target, net)
            cable_rows.append([ref, number, net, target if ref != "X4" else "T1;T2", ";".join(target_pins)])
    for ref, target, names in [("J20", "J2", ["VDD", "GND", "SCL", "SDA"]),
                                ("J21", "J13", ["VDD", "GND", "SCL", "SDA"]),
                                ("J32", "J2", ["A0", "A1", "A2", "A3", "GND"]),
                                ("J33", "J13", ["A0", "A1", "GND"])]:
        target_pins = {name: net for _, name, net, _ in by_ref[target].pins}
        assert len(names) == len(by_ref[ref].pins)
        for (number, _, net, _), name in zip(by_ref[ref].pins, names):
            assert net == target_pins[name], (ref, number, target, name)
            cable_rows.append([ref, number, net, target, name])
    write_csv(OUTPUT / "ads-configuration.csv", ["Module", "Address", "ADDR", "ALRT", "A2_A3", "Local_100n_VDD_GND"],
              [["J2", "0x48", "GND", "NC", "U_B1;U_B2", "C6"],
               ["J13", "0x49", "VDD_3V3_REMOVE_GND_STRAP", "NC", "GND;GND", "C10"]])
    write_csv(OUTPUT / "cable-map.csv", ["PCB_connector", "PCB_pin", "Net", "External_module", "Module_pin_name"], cable_rows)
    write_csv(OUTPUT / "bom.csv", ["Reference", "Documentation_alias", "Value", "Quantity", "Location", "Populate"],
              [[part.ref, part.alias, part.value, 1, part.board or "external", "DNP" if part.ref == "D3" else "copper only" if part.ref == "NT1" else "yes"]
               for part in parts if part.kind != "flag"])
    write_csv(OUTPUT / "pinout.csv", ["Reference", "Pin", "Pin_name", "Net", "Board", "Local_x_mm", "Local_y_mm"],
              [[item.GetReference(), pad.GetNumber(), next((name for part in parts if part.ref == item.GetReference()
                for number, name, _, _ in part.pins if number == pad.GetNumber()), ""), pad.GetNetname(),
                by_ref[item.GetReference()].board,
                round(position(pad)[0] - LAYOUT[by_ref[item.GetReference()].board]["origin"][0], 4),
                round(position(pad)[1] - LAYOUT[by_ref[item.GetReference()].board]["origin"][1], 4)]
               for item in board.GetFootprints() if not item.GetReference().startswith(("W", "H"))
               for pad in item.Pads()])
    holes = {}
    for item in board.GetFootprints():
        for pad in item.Pads():
            drill = round(pcbnew.ToMM(pad.GetDrillSize().x), 3)
            if not drill:
                continue
            x, y = position(pad)
            side = next(key for key, settings in LAYOUT.items()
                        if settings["origin"][0] <= x <= settings["origin"][0]+settings["size"][0]
                        and settings["origin"][1] <= y <= settings["origin"][1]+settings["size"][1])
            key = (side, round(x - LAYOUT[side]["origin"][0], 4), round(y - LAYOUT[side]["origin"][1], 4), drill)
            holes.setdefault(key, []).append(item.GetReference() + "." + pad.GetNumber())
    write_csv(OUTPUT / "drill-list.csv", ["Board", "X_mm", "Y_mm", "Drill_mm", "References"],
              [[*key, ";".join(refs)] for key, refs in sorted(holes.items())])
    write_csv(OUTPUT / "drill-summary.csv", ["Board", "Drill_mm", "Count"],
              [[*key, count] for key, count in sorted(Counter((key[0], key[3]) for key in holes).items())])
    with (ROOT / "module-jumpers.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        wire_fields = reader.fieldnames
        wires = list(reader)
    contacts = []
    for row in wires:
        endpoint_names = []
        for index, (x_name, y_name) in enumerate([("X1_mm", "Y1_mm"), ("X2_mm", "Y2_mm")]):
            origin = LAYOUT[row["Board"]]["origin"]
            endpoint = float(row[x_name]) + origin[0], float(row[y_name]) + origin[1]
            found = [item.GetReference() + "." + pad.GetNumber() for item in board.GetFootprints()
                     if not item.GetReference().startswith("W") for pad in item.Pads()
                     if abs(position(pad)[0] - endpoint[0]) < 0.01 and abs(position(pad)[1] - endpoint[1]) < 0.01]
            endpoint_names.append("/".join(dict.fromkeys(found)) or row["Ref"] + " new hole")
        contacts.append([*row.values(), *endpoint_names])
    write_csv(OUTPUT / "jumpers.csv", [*wire_fields, "End1_contact", "End2_contact"], contacts)
    with (ROOT / "interboard-cables.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        write_csv(OUTPUT / "interboard-cables.csv", header, list(reader))
    return len(holes)


def main():
    OUTPUT.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    parts = circuit()
    validate(parts)
    board_path = ROOT / "batman.kicad_pcb"
    board = pcbnew.LoadBoard(str(board_path))
    summary = check_board(board, parts)
    run("sch", "erc", "--exit-code-violations", "-o", REPORTS / "erc.txt", ROOT / "batman.kicad_sch")
    run("pcb", "drc", "--exit-code-violations", "--schematic-parity", "--format", "json", "-o", REPORTS / "drc.json", board_path)
    summary["drilled_holes"] = tables(board, parts)
    run("sch", "export", "pdf", "-o", OUTPUT / "schematic.pdf", ROOT / "batman.kicad_sch")
    run("sch", "export", "netlist", "--format", "kicadxml", "-o", OUTPUT / "netlist.xml", ROOT / "batman.kicad_sch")
    for name, layers, mirror in [("copper-mirrored", "B.Cu,Edge.Cuts", True),
                                  ("copper-top-view", "B.Cu,Edge.Cuts", False),
                                  ("assembly", "F.Fab,F.SilkS,Edge.Cuts", False),
                                  ("wiring", "Dwgs.User,Edge.Cuts", False),
                                  ("component-labels", "F.SilkS,Edge.Cuts", False)]:
        options = ["pcb", "export", "pdf", "--layers", layers, "--mode-single", "--scale", "1", "--black-and-white", "--drill-shape-opt", "2"]
        if mirror:
            options.append("--mirror")
        run(*options, "-o", OUTPUT / (name + ".pdf"), board_path)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm", "--generate-map", "--map-format", "pdf",
        "--generate-report", "--report-path", OUTPUT / "drill-report.txt", "-o", OUTPUT / "drill", board_path)
    run("pcb", "export", "gerbers", "--layers", "B.Cu,Edge.Cuts,F.SilkS", "-o", OUTPUT / "gerbers", board_path)
    summary["modules"] = {}
    for key, settings in LAYOUT.items():
        source = REPORTS / key / "candidate.kicad_pcb"
        destination = OUTPUT / key
        destination.mkdir(exist_ok=True)
        run("pcb", "drc", "--exit-code-violations", "--format", "json", "-o", REPORTS / key / "drc.json", source)
        for name, layers, mirror in [("copper-mirrored", "B.Cu,Edge.Cuts", True),
                                      ("copper-top-view", "B.Cu,Edge.Cuts", False),
                                      ("assembly", "F.Fab,F.SilkS,Edge.Cuts", False),
                                      ("wiring", "Dwgs.User,Edge.Cuts", False)]:
            options = ["pcb", "export", "pdf", "--layers", layers, "--mode-single", "--scale", "1", "--black-and-white", "--drill-shape-opt", "2"]
            if mirror:
                options.append("--mirror")
            run(*options, "-o", destination / (name+".pdf"), source)
        run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm", "--generate-map", "--map-format", "pdf",
            "-o", destination / "drill", source)
        run("pcb", "export", "gerbers", "--layers", "B.Cu,Edge.Cuts,F.SilkS", "-o", destination / "gerbers", source)
        local = pcbnew.LoadBoard(str(source))
        summary["modules"][key] = {"name": settings["name"], "size_mm": settings["size"],
                                  "jumpers": len([item for item in local.GetFootprints() if item.GetReference().startswith("W")]),
                                  "drc_violations": 0, "unconnected": 0}
    summary["erc_violations"] = 0
    summary["drc_violations"] = 0
    summary["unconnected"] = 0
    summary["schematic_parity_issues"] = 0
    summary["release_status"] = "PROTOTYPE - physical fit and bench safety gates not verified"
    (REPORTS / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for obsolete in ["erc.txt", "drc.json", "schematic.pdf", "copper-mirrored.pdf"]:
        (ROOT / obsolete).unlink(missing_ok=True)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()