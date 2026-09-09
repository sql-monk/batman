import csv
import json
from pathlib import Path
import sys

import pcbnew

from cad_common import new_board, outline, point
from circuit import circuit, validate
import freeroute
from pcb import ROOT, ORIGINS, add_jumper, arrange_labels, create_part, draw_text, mount, position


LAYOUT = json.loads(Path(__file__).with_name("modular-layout.json").read_text(encoding="utf-8"))
CABLES = [("J22", "J23"), ("J24", "J25"), ("J26", "J27"),
          ("J28", "J29"), ("X6", "X8")]


def build_module(key):
    parts = [part for part in circuit() if part.board == key]
    settings = LAYOUT[key]
    assert {part.ref for part in parts} == settings["parts"].keys(), key
    nets = sorted({net or f"unconnected-({part.ref}-{name}-Pad{number})"
                   for part in parts for number, name, net, _ in part.pins})
    board = new_board(nets)
    ORIGINS[key] = (30, 30)
    width, height = settings["size"]
    outline(board, 30, 30, width, height)
    for part in parts:
        local_x, local_y, rotation = settings["parts"][part.ref]
        part.position = (local_x, local_y)
        create_part(board, part, rotation)
    for index, (local_x, local_y) in enumerate([(3.5, 3.5), (width-3.5, 3.5),
                                               (3.5, height-3.5), (width-3.5, height-3.5)], 1):
        mount(board, f"H{key}{index}", local_x+30, local_y+30)
    if key == "A":
        mcu_x, mcu_y, _ = settings["parts"]["J1"]
        zone = pcbnew.ZONE(board)
        zone.SetIsRuleArea(True)
        zone.SetLayerSet(pcbnew.LSET.AllCuMask())
        zone.SetDoNotAllowTracks(True)
        zone.SetDoNotAllowPads(True)
        zone.SetDoNotAllowVias(True)
        zone.SetDoNotAllowZoneFills(True)
        zone.SetZoneName("ESP32_ANTENNA_NO_COPPER")
        polygon = zone.Outline()
        polygon.NewOutline()
        for local_x, local_y in [(mcu_x-4, 0), (mcu_x+29.8, 0), (mcu_x+29.8, mcu_y-2), (mcu_x-4, mcu_y-2)]:
            polygon.Append(pcbnew.FromMM(local_x+30), pcbnew.FromMM(local_y+30))
        board.Add(zone)
    draw_text(board, key + " / " + settings["name"], 30+width/2, 37 if key == "B" else 30+height-3, 0.8, pcbnew.F_Fab)
    arrange_labels(board)
    return board


def merge_modules():
    parts = circuit()
    names = {net or f"unconnected-({part.ref}-{name}-Pad{number})"
             for part in parts if part.board for number, name, net, _ in part.pins}
    combined = new_board(sorted(names))
    wire_rows = []
    for key, settings in LAYOUT.items():
        directory = ROOT / "reports" / key
        board = pcbnew.LoadBoard(str(directory / "candidate.kicad_pcb"))
        if key == "B":
            for item in board.GetDrawings():
                if isinstance(item, pcbnew.PCB_TEXT) and item.GetText() == key + " / " + settings["name"]:
                    item.SetPosition(point(30+settings["size"][0]/2, 37))
        arrange_labels(board)
        for zone in board.Zones():
            if not zone.GetIsRuleArea():
                zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
                zone.UnFill()
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        freeroute.REPORTS = directory
        freeroute.save_candidate(board, None)
        delta = point(settings["origin"][0]-30, settings["origin"][1]-30)
        for source in [*board.GetFootprints(), *board.GetTracks(), *board.Zones(), *board.GetDrawings()]:
            item = source.Duplicate(False) if isinstance(source, (pcbnew.FOOTPRINT, pcbnew.ZONE)) else source.Duplicate()
            if isinstance(source, pcbnew.FOOTPRINT):
                item = pcbnew.Cast_to_FOOTPRINT(item)
            elif isinstance(source, pcbnew.ZONE):
                item = pcbnew.Cast_to_ZONE(item)
            elif isinstance(source, pcbnew.PCB_TRACK):
                item = pcbnew.Cast_to_PCB_TRACK(item)
            item.SetParent(combined)
            combined.Add(item)
            if isinstance(item, pcbnew.ZONE):
                item.SetZoneName(source.GetZoneName() if source.GetIsRuleArea() else source.GetZoneName()+"_"+key)
                if not item.GetIsRuleArea():
                    item.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
                    item.UnFill()
            if isinstance(item, pcbnew.FOOTPRINT):
                for pad in item.Pads():
                    if pad.GetNetname():
                        pad.SetNet(combined.FindNet(pad.GetNetname()))
            elif isinstance(item, (pcbnew.PCB_TRACK, pcbnew.ZONE)) and item.GetNetname():
                item.SetNet(combined.FindNet(item.GetNetname()))
            item.Move(delta)
        with (directory / "jumpers.csv").open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                wire_rows.append([row["Ref"], key, row["Net"], row["A_X1_mm"], row["A_Y1_mm"],
                                  row["X2_mm"], row["Y2_mm"], row["Wire_cut_min_mm"]])
    footprints = {item.GetReference(): item for item in combined.GetFootprints()}
    cables = []
    for index, (first_ref, second_ref) in enumerate(CABLES, 2):
        first_pads = {pad.GetNumber(): pad for pad in footprints[first_ref].Pads()}
        second_pads = {pad.GetNumber(): pad for pad in footprints[second_ref].Pads()}
        assert first_pads.keys() == second_pads.keys()
        for number, first in first_pads.items():
            second = second_pads[number]
            assert first.GetNetname() == second.GetNetname()
            ref = f"WC{index}_{number}"
            add_jumper(combined, ref, first.GetNetname(), position(first), position(second), (True, True))
            footprints[ref] = next(item for item in combined.GetFootprints() if item.GetReference() == ref)
            footprints[ref].SetValue("EXTERNAL_CABLE_NOT_PCB")
            cables.append([f"CB{index}", first_ref, number, second_ref, number, first.GetNetname()])
    combined.BuildConnectivity()
    pcbnew.ZONE_FILLER(combined).Fill(combined.Zones())
    freeroute.REPORTS = ROOT / "reports"
    freeroute.save_candidate(combined, None, publish=True)
    for filename, header, rows in [
            ("module-jumpers.csv", ["Ref", "Board", "Net", "X1_mm", "Y1_mm", "X2_mm", "Y2_mm", "Min_length_mm"], wire_rows),
            ("interboard-cables.csv", ["Cable", "From", "Pin", "To", "Pin_to", "Net"], cables)]:
        with (ROOT / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
    print(f"Merged four PCBs; {len(wire_rows)} local wires; {len(CABLES)} cables / {len(cables)} conductors")


def main():
    validate(circuit())
    if "--merge" in sys.argv:
        merge_modules()
        return
    selected = sys.argv[sys.argv.index("--board")+1] if "--board" in sys.argv else None
    for key in [selected] if selected else LAYOUT:
        freeroute.REPORTS = ROOT / "reports" / key
        board = build_module(key)
        if "--route" in sys.argv:
            assert "--publish" not in sys.argv, "Use --merge to publish all four boards together"
            freeroute.reroute(board, "W"+key)
        else:
            freeroute.prepare(board)


if __name__ == "__main__":
    main()