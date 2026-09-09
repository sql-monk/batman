"""Export actual populated PCB footprint geometry using KiCad's Python."""

import json
from pathlib import Path

import pcbnew


ROOT = Path(__file__).resolve().parent
layout = json.loads((ROOT.parent / "hardware/modular-layout.json").read_text())
board = pcbnew.LoadBoard(str(ROOT.parent / "hardware/batman/batman.kicad_pcb"))
footprints = {item.GetReference() or "aux-" + item.m_Uuid.AsString()[:8]: item for item in board.GetFootprints()}
result = {}
for board_name, spec in layout.items():
    entries = []
    for reference, footprint in sorted(footprints.items()):
        position = footprint.GetPosition()
        local = [pcbnew.ToMM(position.x) - spec["origin"][0],
                 pcbnew.ToMM(position.y) - spec["origin"][1]]
        if not (0 <= local[0] <= spec["size"][0] and 0 <= local[1] <= spec["size"][1]):
            continue
        if reference.startswith("WC"):
            continue
        pads = []
        for pad in footprint.Pads():
            point = pad.GetPosition()
            pads.append({"number": pad.GetNumber(),
                         "xy": [pcbnew.ToMM(point.x) - spec["origin"][0],
                                pcbnew.ToMM(point.y) - spec["origin"][1]],
                         "size": [pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y)],
                         "drill": [pcbnew.ToMM(pad.GetDrillSize().x), pcbnew.ToMM(pad.GetDrillSize().y)],
                         "net": pad.GetNetname()})
        entries.append({"reference": reference, "value": footprint.GetValue(),
                        "footprint": str(footprint.GetFPID().GetLibItemName()),
                        "back": footprint.IsFlipped(),
                        "xy": local, "rotation": footprint.GetOrientationDegrees(),
                        "pads": pads})
        assert 0 <= local[0] <= spec["size"][0] and 0 <= local[1] <= spec["size"][1], reference
    result[board_name] = {"size": spec["size"], "components": entries,
                          "stale_layout_references": sorted(set(spec["parts"]) - set(footprints))}
(ROOT / "pcb-components.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"boards": {name: len(spec["components"]) for name, spec in result.items()},
                  "total": sum(len(spec["components"]) for spec in result.values())}))