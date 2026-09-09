import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pcbnew

import freeroute
import modular
import schematic
from pcb import position


ROOT = Path(__file__).resolve().parent / "batman"
WORK = ROOT / "reports" / "refinement"
RULES = '''(version 1)
(rule "LUT copper clearance"
    (constraint clearance (min 0.5mm)))
(rule "LUT track width"
    (constraint track_width (min 0.8mm)))
(rule "LUT copper edge"
    (constraint edge_clearance (min 0.5mm)))
(rule "Room around tracks"
    (condition "A.Type == 'Track' || B.Type == 'Track'")
    (constraint clearance (min 0.65mm)))
(rule "Low voltage supply width"
    (condition "A.NetName == 'GND' || A.NetName == '+3V3' || A.NetName == '+3V3_SENS' || A.NetName == '+5V' || A.NetName == '+5V_RELAY_VCC' || A.NetName == '+5V_RELAY_COIL'")
    (constraint track_width (min 1.0mm)))
(rule "Battery and raw voltage clearance"
    (condition "A.NetName == 'B1' || A.NetName == 'B2' || A.NetName == 'LOAD+' || A.NetName == 'VIN_DC' || B.NetName == 'B1' || B.NetName == 'B2' || B.NetName == 'LOAD+' || B.NetName == 'VIN_DC'")
    (constraint clearance (min 1.0mm)))
(rule "Battery and raw voltage width"
    (condition "A.NetName == 'B1' || A.NetName == 'B2' || A.NetName == 'LOAD+' || A.NetName == 'VIN_DC'")
    (constraint track_width (min 1.2mm)))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", choices=list(modular.LAYOUT), default="A")
    parser.add_argument("--finish-only", action="store_true")
    parser.add_argument("--assemble", action="store_true")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    source = ROOT / "batman.kicad_pcb"
    snapshot = WORK / "saved-input.kicad_pcb"
    if not snapshot.exists():
        shutil.copy2(source, snapshot)
        for suffix in [".kicad_pro", ".kicad_dru"]:
            shutil.copy2(source.with_suffix(suffix), snapshot.with_suffix(suffix))
    board = pcbnew.LoadBoard(str(snapshot))
    footprints = {item.GetReference(): item for item in board.GetFootprints()}
    for key, settings in modular.LAYOUT.items():
        for reference in settings["parts"]:
            item = footprints[reference]
            local_x, local_y = position(item)
            settings["parts"][reference] = [round(local_x - settings["origin"][0], 6),
                                            round(local_y - settings["origin"][1], 6),
                                            item.GetOrientationDegrees()]
    modular.LAYOUT["A"]["parts"]["J22"] = [18, 39.94, 0]
    modular.LAYOUT["A"]["parts"].update({
        "J20": [64, 12, -90], "J21": [72, 12, -90],
        "R16": [64, 26, 90], "R17": [72, 26, 90],
    })
    modular.LAYOUT["B"]["parts"]["C4"] = [46, 21, 0]
    modular.LAYOUT["B"]["parts"]["C3"] = [42, 32, 0]
    modular.LAYOUT["D"]["parts"]["J8"] = [48, 32, 90]
    modular.LAYOUT["D"]["parts"].update({
        "J27": [34, 21, 0], "J31": [34, 27, 0], "C13": [35, 14, 0],
        "J29": [38, 34, 180],
    })
    for key, size in {"A": [78, 78], "B": [86, 68], "C": [43, 33], "D": [63, 40]}.items():
        modular.LAYOUT[key]["size"] = size
    (WORK / "layout.json").write_text(json.dumps(modular.LAYOUT, indent=2) + "\n", encoding="utf-8")
    if args.assemble or args.export:
        stage = WORK / "staged"
        stage.mkdir(exist_ok=True)
        if args.assemble:
            for key in modular.LAYOUT:
                shutil.copytree(WORK / key, stage / "reports" / key, dirs_exist_ok=True)
            shutil.copy2(ROOT / "batman.kicad_pro", stage / "batman.kicad_pro")
            (stage / "batman.kicad_dru").write_text(RULES, encoding="utf-8")
            modular.ROOT = freeroute.ROOT = schematic.ROOT = stage
            modular.merge_modules()
            cli = Path(sys.executable).with_name("kicad-cli.exe")
            for path in [stage / "batman.kicad_pcb", *[stage / "reports" / key / "candidate.kicad_pcb" for key in modular.LAYOUT]]:
                path.with_suffix(".kicad_dru").write_text(RULES, encoding="utf-8")
                subprocess.run([str(cli), "pcb", "drc", "--refill-zones", "--save-board", "--exit-code-violations",
                                "--format", "json", "--output", str(path.parent / "assembly-drc.json"), str(path)], check=True)
        if args.export:
            import export
            export.ROOT = stage
            export.OUTPUT = stage / "output"
            export.REPORTS = stage / "reports"
            export.main()
        return
    freeroute.REPORTS = WORK / args.board
    sys.argv.extend(["--wire", "--finish-copper"])
    candidate = modular.build_module(args.board)
    routing_rules = {}
    for net in candidate.GetNetsByNetcode().values():
        name = net.GetNetname()
        if name in {"B1", "B2", "LOAD+", "VIN_DC"}:
            routing_rules[name] = (1200, 1000)
        elif name.startswith("+") or name == "GND":
            routing_rules[name] = (1000, 650)
        else:
            routing_rules[name] = (800, 650)
    if args.finish_only:
        result = freeroute.import_session("W" + args.board, routing_rules)
    else:
        result = freeroute.reroute(candidate, "W" + args.board, routing_rules)
    (freeroute.REPORTS / "candidate.kicad_dru").write_text(RULES, encoding="utf-8")
    tracks = list(result.GetTracks())
    print(json.dumps({"board": args.board, "tracks": len(tracks),
                      "short_segments": sum(item.GetLength() < pcbnew.FromMM(1) for item in tracks)}))


if __name__ == "__main__":
    main()