import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import sexpdata


def children(node, name):
    return [item for item in node if isinstance(item, list) and item and str(item[0]) == name]


def field(node, name):
    return children(node, name)[0]


def segments(board):
    return children(board, "segment")


def endpoint(segment, name):
    return tuple(field(segment, name)[1:3])


def length(segment):
    return math.dist(endpoint(segment, "start"), endpoint(segment, "end"))


def short_count(board):
    return sum(length(item) < 1 - 1e-9 for item in segments(board))


def identifier(node):
    return field(node, "uuid")[1]


def without_fills(board):
    for zone in children(board, "zone"):
        zone[:] = [item for item in zone if not (isinstance(item, list) and item and str(item[0]) == "filled_polygon")]
    return board


def collapse(board, selected, replacement=None):
    trial = deepcopy(board)
    target = next(item for item in segments(trial) if identifier(item) == selected)
    start, end = endpoint(target, "start"), endpoint(target, "end")
    net, layer = field(target, "net")[1:], field(target, "layer")[1:]
    trial.remove(target)
    if replacement is not None:
        for item in segments(trial):
            if field(item, "net")[1:] != net or field(item, "layer")[1:] != layer:
                continue
            for name in ["start", "end"]:
                if endpoint(item, name) in [start, end]:
                    field(item, name)[1:3] = replacement
        trial[:] = [item for item in trial if item not in segments(trial) or length(item) > 1e-9]
    return trial


def check(board, path, cli):
    path.write_text(sexpdata.dumps(board), encoding="utf-8")
    report = path.with_suffix(".json")
    result = subprocess.run([str(cli), "pcb", "drc", "--refill-zones", "--save-board", "--format", "json",
                             "--output", str(report), str(path)], capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    data = json.loads(report.read_text(encoding="utf-8"))
    return not data.get("violations") and not data.get("unconnected_items")


def proposals(board, item):
    start, end = endpoint(item, "start"), endpoint(item, "end")
    midpoint = tuple(round((first + second) / 2, 6) for first, second in zip(start, end))
    for replacement in [None, start, end, midpoint]:
        yield collapse(board, identifier(item), replacement)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    cli = Path(sys.executable).with_name("kicad-cli.exe")
    source = args.board
    trial_path = source.with_name("polish-trial.kicad_pcb")
    for suffix in [".kicad_pro", ".kicad_dru"]:
        shutil.copy2(source.with_suffix(suffix), trial_path.with_suffix(suffix))
    backup = source.with_name("before-polish.kicad_pcb")
    if not backup.exists():
        shutil.copy2(source, backup)
    board = without_fills(sexpdata.loads(source.read_text(encoding="utf-8")))
    before = {"segments": len(segments(board)), "short_segments": short_count(board)}
    if not check(board, trial_path, cli):
        raise RuntimeError("Input must pass DRC before simplification")
    attempts = 0
    while short_count(board):
        accepted = False
        for item in sorted(segments(board), key=length):
            if length(item) >= 1 - 1e-9:
                break
            for trial in proposals(board, item):
                if short_count(trial) >= short_count(board):
                    continue
                attempts += 1
                if check(trial, trial_path, cli):
                    board = trial
                    shutil.copy2(trial_path, source)
                    accepted = True
                    print(f"Accepted: {len(segments(board))} segments, {short_count(board)} below 1 mm", flush=True)
                    break
            if accepted:
                break
        if not accepted:
            break
    if not check(board, trial_path, cli):
        raise RuntimeError("Final simplified board failed DRC")
    shutil.copy2(trial_path, source)
    shutil.copy2(trial_path.with_suffix(".json"), source.with_name("drc.json"))
    summary = {"before": before, "after": {"segments": len(segments(board)), "short_segments": short_count(board),
               "minimum_length_mm": min(length(item) for item in segments(board))}, "drc_trials": attempts}
    source.with_name("polish.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    if short_count(board):
        raise SystemExit("Some short segments still need local rerouting")


if __name__ == "__main__":
    main()