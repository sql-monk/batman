import argparse
from pathlib import Path
import shutil
import sys

import sexpdata

from polish import check, field, identifier, segments, without_fills
from reroute_clean import validate


def prune(path):
    data = without_fills(sexpdata.loads(path.read_text(encoding="utf-8")))
    trial_path = path.with_name("prune-trial.kicad_pcb")
    for suffix in [".kicad_pro", ".kicad_dru"]:
        shutil.copy2(path.with_suffix(suffix), trial_path.with_suffix(suffix))
    cli = Path(sys.executable).with_name("kicad-cli.exe")
    assert check(data, trial_path, cli)
    original = len(segments(data))
    def remove(items):
        nonlocal data
        ids = {identifier(item) for item in items}
        trial = [item for item in data if item not in segments(data) or identifier(item) not in ids]
        if check(trial, trial_path, cli):
            data = trial
            print(f"Removed {len(items)} redundant GND segments; remaining {len(segments(data))}", flush=True)
        elif len(items) > 1:
            middle = len(items) // 2
            remove(items[:middle])
            remove(items[middle:])
    ground = [item for item in segments(data) if field(item, "net")[1] == "GND"]
    if ground:
        remove(ground)
    assert check(data, path, cli)
    print(f"Pruned {original - len(segments(data))} segments without changing connectivity", flush=True)
    return validate(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    prune(parser.parse_args().path)