import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pcbnew
import sexpdata

import freeroute
from circuit import circuit
from modular import LAYOUT
from polish import children, field, segments, length, without_fills


ROOT = Path(__file__).resolve().parent / "batman"
WORK = ROOT / "reports" / "clean-routing"
CLI = Path(sys.executable).with_name("kicad-cli.exe")


def reference(item):
    return next(prop[2] for prop in children(item, "property") if prop[1] == "Reference")


def setup():
    WORK.mkdir(exist_ok=True)
    source = WORK / "saved-input.kicad_pcb"
    if not source.exists():
        shutil.copy2(ROOT / "batman.kicad_pcb", source)
    return sexpdata.loads(source.read_text(encoding="utf-8"))


def support(directory, stem):
    directory.mkdir(parents=True, exist_ok=True)
    for suffix in [".kicad_pro", ".kicad_dru"]:
        shutil.copy2(ROOT / ("batman" + suffix), directory / (stem + suffix))
    shutil.copy2(ROOT / "fp-lib-table", directory / "fp-lib-table")
    shutil.copytree(ROOT / "Batman.pretty", directory / "Batman.pretty", dirs_exist_ok=True)


def validate(path):
    subprocess.run([str(CLI), "pcb", "drc", "--refill-zones", "--save-board",
                    "--format", "json", "--output", str(path.with_suffix(".drc.json")), str(path)], check=True)
    report = json.loads(path.with_suffix(".drc.json").read_text(encoding="utf-8"))
    data = sexpdata.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({"board": str(path), "segments": len(segments(data)),
                      "under_1mm": sum(length(item) < 0.99999 for item in segments(data)),
                      "violations": len(report["violations"]),
                      "unconnected": len(report["unconnected_items"])}), flush=True)
    return report


def route(key, original):
    directory = WORK / key
    support(directory, "candidate")
    refs = {part.ref for part in circuit() if part.board == key}
    origin_x, origin_y = LAYOUT[key]["origin"]
    width, height = LAYOUT[key]["size"]
    board = pcbnew.LoadBoard(str(WORK / "saved-input.kicad_pcb"))
    local_ids = set()
    for item in [*board.GetDrawings(), *board.Zones()]:
        bounds = item.GetBoundingBox()
        center = bounds.GetCenter()
        center_x, center_y = pcbnew.ToMM(center.x), pcbnew.ToMM(center.y)
        if origin_x - 0.1 <= center_x <= origin_x + width + 0.1 and origin_y - 0.1 <= center_y <= origin_y + height + 0.1:
            local_ids.add(item.m_Uuid.AsString())
    data = []
    for item in without_fills(deepcopy(original)):
        if not isinstance(item, list) or not item:
            data.append(item)
            continue
        kind = str(item[0])
        if kind in {"segment", "via"}:
            continue
        if kind == "footprint":
            ref = reference(item)
            if ref not in refs and not ref.startswith("H" + key) and not (key == "A" and ref.startswith("WA")):
                continue
        if kind == "zone" or kind.startswith("gr_"):
            uuid = field(item, "uuid")
            if uuid is None or uuid[1] not in local_ids:
                continue
            if kind == "zone" and not children(item, "keepout"):
                continue
        data.append(item)
    path = directory / "input.kicad_pcb"
    path.write_text(sexpdata.dumps(data), encoding="utf-8")
    board = pcbnew.LoadBoard(str(path))
    assert not list(board.GetTracks())
    freeroute.REPORTS = directory
    freeroute.reroute(board, optimize=True)
    validate(directory / "candidate.kicad_pcb")


def assemble(original):
    stage = WORK / "staged"
    support(stage, "batman")
    for source in ROOT.glob("*.kicad_sch"):
        shutil.copy2(source, stage / source.name)
    for name in ["sym-lib-table", "Batman.kicad_sym"]:
        shutil.copy2(ROOT / name, stage / name)
    data = [item for item in without_fills(deepcopy(original))
            if not (isinstance(item, list) and item and
                    (str(item[0]) in {"segment", "via"} or
                     str(item[0]) == "zone" and not children(item, "keepout")))]
    for key in LAYOUT:
        module = sexpdata.loads((WORK / key / "candidate.kicad_pcb").read_text(encoding="utf-8"))
        data.extend(segments(module))
        data.extend(zone for zone in children(module, "zone") if not children(zone, "keepout"))
    assert children(data, "footprint") == children(original, "footprint")
    path = stage / "batman.kicad_pcb"
    path.write_text(sexpdata.dumps(data), encoding="utf-8")
    report = validate(path)
    assert not report["violations"] and not report["unconnected_items"]
    final = pcbnew.LoadBoard(str(path))
    before = pcbnew.LoadBoard(str(WORK / "saved-input.kicad_pcb"))
    def placements(board):
        return sorted((item.GetReference(), item.GetPosition().x, item.GetPosition().y,
                       item.GetOrientationDegrees(),
                       sorted((pad.GetNumber(), pad.GetPosition().x, pad.GetPosition().y, pad.GetNetname())
                              for pad in item.Pads())) for item in board.GetFootprints())
    assert placements(final) == placements(before)
    print("All component positions, rotations and pad nets unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", choices=list(LAYOUT))
    parser.add_argument("--assemble", action="store_true")
    args = parser.parse_args()
    original = setup()
    if args.board:
        route(args.board, original)
    if args.assemble:
        assemble(original)