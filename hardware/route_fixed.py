import argparse
from pathlib import Path
import shutil

import pcbnew
import sexpdata

import freeroute
from polish import children, endpoint, field, segments, without_fills
from reroute_clean import validate


def route(path, names):
    directory = path.parent / "fixed"
    directory.mkdir(exist_ok=True)
    source = without_fills(sexpdata.loads(path.read_text(encoding="utf-8")))
    source[:] = [item for item in source if item not in segments(source) or field(item, "net")[1] not in names]
    source[:] = [item for item in source if item not in children(source, "zone") or children(item, "keepout")]
    input_path = directory / "input.kicad_pcb"
    input_path.write_text(sexpdata.dumps(source), encoding="utf-8")
    original_prepare = freeroute.prepare
    def prepare(board, routing_rules):
        original_prepare(board, routing_rules)
        design_path = directory / "routing.dsn"
        design = sexpdata.loads(design_path.read_text(encoding="utf-8"))
        wiring = children(design, "wiring")[0]
        for item in segments(source):
            start, end = endpoint(item, "start"), endpoint(item, "end")
            wiring.append(freeroute.form("wire", freeroute.form("path", "B.Cu", round(field(item, "width")[1] * 1000),
                           round(start[0] * 1000), round(-start[1] * 1000), round(end[0] * 1000), round(-end[1] * 1000)),
                           freeroute.form("net", field(item, "net")[1]), freeroute.form("type", sexpdata.Symbol("protect"))))
        design_path.write_text(sexpdata.dumps(design), encoding="utf-8")
    freeroute.prepare = prepare
    freeroute.REPORTS = directory
    freeroute.reroute(pcbnew.LoadBoard(str(input_path)), optimize=True)
    candidate = directory / "candidate.kicad_pcb"
    data = sexpdata.loads(candidate.read_text(encoding="utf-8"))
    seen = set()
    for item in list(segments(data)):
        key = field(item, "net")[1], field(item, "width")[1], tuple(sorted([endpoint(item, "start"), endpoint(item, "end")]))
        if key in seen:
            data.remove(item)
        seen.add(key)
    candidate.write_text(sexpdata.dumps(data), encoding="utf-8")
    report = validate(candidate)
    if not report["violations"] and not report["unconnected_items"]:
        shutil.copy2(candidate, path)
        validate(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("nets", nargs="+")
    args = parser.parse_args()
    route(args.path, args.nets)