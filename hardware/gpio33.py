import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pcbnew
import sexpdata

import freeroute
import modular
import schematic
from pcb import position


ROOT = Path(__file__).resolve().parent / "batman"
WORK = ROOT / "reports" / "gpio33"
CLI = Path(sys.executable).with_name("kicad-cli.exe")


def drc(path):
    subprocess.run([str(CLI), "pcb", "drc", "--refill-zones", "--save-board", "--exit-code-violations",
                    "--format", "json", "--output", str(path.parent / "drc.json"), str(path)], check=True)


def check_j22(path):
    import polish
    data = sexpdata.loads(path.read_text(encoding="utf-8"))
    data[:] = [item for item in data if not (isinstance(item, list) and item and str(item[0]) == "footprint"
               and any(prop[1] == "Reference" and str(prop[2]).startswith("W")
                       for prop in polish.children(item, "property")))]
    copper_only = path.with_name("copper-only.kicad_pcb")
    for suffix in [".kicad_pro", ".kicad_dru"]:
        shutil.copy2(path.with_suffix(suffix), copper_only.with_suffix(suffix))
    copper_only.write_text(sexpdata.dumps(data), encoding="utf-8")
    subprocess.run([str(CLI), "pcb", "drc", "--refill-zones", "--save-board", "--format", "json",
                    "--output", str(path.parent / "copper-only-drc.json"), str(copper_only)], check=True)
    board = pcbnew.LoadBoard(str(copper_only))
    groups = freeroute.copper_groups(board)
    for net in ["+3V3", "GND", "SENS_PWR"]:
        assert any({"J1", "J22"} <= {pad.GetParentFootprint().GetReference() for pad in cluster}
                   for cluster in groups[net]), f"J22 {net} depends on a jumper"
    (path.parent / "j22-copper-check.json").write_text(json.dumps({
        "jumper_models_removed": True, "J22_to_J1_copper": ["+3V3", "GND", "SENS_PWR"]}, indent=2) + "\n", encoding="utf-8")
    print("All three J22 nets connect to J1 through copper without jumper models")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assemble", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--check-j22", action="store_true")
    args = parser.parse_args()
    if args.check_j22:
        check_j22(WORK / "A" / "candidate.kicad_pcb")
        return
    WORK.mkdir(exist_ok=True)
    snapshot = WORK / "saved-input.kicad_pcb"
    if not snapshot.exists():
        for suffix in [".kicad_pcb", ".kicad_pro", ".kicad_dru"]:
            shutil.copy2(ROOT / ("batman" + suffix), snapshot.with_suffix(suffix))
    board = pcbnew.LoadBoard(str(snapshot))
    footprints = {item.GetReference(): item for item in board.GetFootprints()}
    for settings in modular.LAYOUT.values():
        for reference in settings["parts"]:
            item = footprints[reference]
            location = position(item)
            settings["parts"][reference] = [round(location[0] - settings["origin"][0], 6),
                                            round(location[1] - settings["origin"][1], 6),
                                            item.GetOrientationDegrees()]
    modular.LAYOUT["A"]["parts"]["J22"] = [22, 24.7, -90]
    modular.LAYOUT["A"]["parts"]["J11"] = [10, 39, 0]
    (WORK / "layout.json").write_text(json.dumps(modular.LAYOUT, indent=2) + "\n", encoding="utf-8")
    if args.assemble or args.export:
        stage = WORK / "staged"
        stage.mkdir(exist_ok=True)
        if args.assemble:
            for key in modular.LAYOUT:
                source = WORK / "A" if key == "A" else ROOT / "reports" / key
                shutil.copytree(source, stage / "reports" / key, dirs_exist_ok=True)
            for suffix in [".kicad_pro", ".kicad_dru"]:
                shutil.copy2(ROOT / ("batman" + suffix), stage / ("batman" + suffix))
            modular.ROOT = freeroute.ROOT = schematic.ROOT = stage
            modular.merge_modules()
            for path in [stage / "batman.kicad_pcb", *[stage / "reports" / key / "candidate.kicad_pcb" for key in modular.LAYOUT]]:
                drc(path)
        if args.export:
            import export
            export.ROOT = stage
            export.OUTPUT = stage / "output"
            export.REPORTS = stage / "reports"
            export.main()
        return
    freeroute.REPORTS = WORK / "A"
    sys.argv.extend(["--wire", "--finish-copper"])
    freeroute.reroute(modular.build_module("A"), "WA")
    drc(WORK / "A" / "candidate.kicad_pcb")
    print((WORK / "A" / "jumpers.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()