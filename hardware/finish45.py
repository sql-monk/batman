import argparse
from pathlib import Path
import shutil
import sys

import sexpdata

from octilinear import aligned
from polish import check, endpoint, length, proposals, segments, without_fills
from reroute_clean import validate


def finish(path):
    data = without_fills(sexpdata.loads(path.read_text(encoding="utf-8")))
    trial_path = path.with_name("angle-trial.kicad_pcb")
    for suffix in [".kicad_pro", ".kicad_dru"]:
        shutil.copy2(path.with_suffix(suffix), trial_path.with_suffix(suffix))
    cli = Path(sys.executable).with_name("kicad-cli.exe")
    assert check(data, trial_path, cli)
    while True:
        accepted = False
        for item in sorted(segments(data), key=length):
            if length(item) >= 0.99999:
                break
            for trial in proposals(data, item):
                if not all(aligned(endpoint(segment, "start"), endpoint(segment, "end")) for segment in segments(trial)):
                    continue
                if check(trial, trial_path, cli):
                    data = trial
                    accepted = True
                    print(f"Removed redundant transition; {len(segments(data))} segments remain", flush=True)
                    break
            if accepted:
                break
        if not accepted:
            break
    assert check(data, path, cli)
    return validate(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    finish(parser.parse_args().path)