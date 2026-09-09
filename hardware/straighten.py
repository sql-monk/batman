import argparse
from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import networkx as nx
import pcbnew
import sexpdata
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from polish import check, children, endpoint, field, identifier, length, segments, without_fills


TOLERANCE = 0.00001
RAW_NETS = {"B1", "B2", "LOAD+", "VIN_DC"}


def point(coordinate):
    return tuple(round(float(value), 6) for value in coordinate)


def line(segment):
    return LineString([endpoint(segment, "start"), endpoint(segment, "end")])


def net(segment):
    return str(field(segment, "net")[1])


def make_segment(template, start, end):
    result = deepcopy(template)
    field(result, "start")[1:3] = point(start)
    field(result, "end")[1:3] = point(end)
    field(result, "uuid")[1] = str(uuid4())
    return result


def read_pads(path):
    board = pcbnew.LoadBoard(str(path))
    pads = []
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if not pad.GetLayerSet().Contains(pcbnew.B_Cu):
                continue
            polygon = pad.GetEffectivePolygon(pcbnew.B_Cu)
            outlines = []
            for index in range(polygon.OutlineCount()):
                outline = polygon.COutline(index)
                outlines.append(Polygon([(pcbnew.ToMM(outline.CPoint(vertex).x),
                                          pcbnew.ToMM(outline.CPoint(vertex).y))
                                         for vertex in range(outline.PointCount())]))
            pads.append({"net": pad.GetNetname(), "center": point((pcbnew.ToMM(pad.GetPosition().x),
                                                                   pcbnew.ToMM(pad.GetPosition().y))),
                         "shape": unary_union(outlines),
                         "reference": footprint.GetReference() + "." + pad.GetNumber()})
    return pads


def paths(start, end):
    yield [start, end]
    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    diagonal = min(abs(delta_x), abs(delta_y))
    offset = (math.copysign(diagonal, delta_x), math.copysign(diagonal, delta_y))
    for corner in [(start[0] + offset[0], start[1] + offset[1]),
                   (end[0] - offset[0], end[1] - offset[1]),
                   (start[0], end[1]), (end[0], start[1])]:
        corner = point(corner)
        if corner not in [start, end]:
            yield [start, corner, end]


def chains(items, anchors):
    graph = nx.Graph()
    for item in items:
        start, end = endpoint(item, "start"), endpoint(item, "end")
        graph.add_edge(start, end, segment=item)
    junctions = {node for node in graph if graph.degree(node) != 2 or node in anchors}
    seen = set()
    result = []
    for start in sorted(junctions):
        for following in list(graph[start]):
            nodes = [start, following]
            items = [graph[start][following]["segment"]]
            edge = frozenset([start, following])
            if edge in seen:
                continue
            seen.add(edge)
            while following not in junctions:
                next_node = next(node for node in graph[following] if node != nodes[-2])
                edge = frozenset([following, next_node])
                if edge in seen:
                    break
                seen.add(edge)
                items.append(graph[following][next_node]["segment"])
                nodes.append(next_node)
                following = next_node
            result.append((nodes, items))
    return result


class Straightener:
    def __init__(self, source, work):
        self.source = source
        self.work = work
        work.mkdir(parents=True, exist_ok=True)
        self.path = work / "candidate.kicad_pcb"
        for suffix in [".kicad_pro", ".kicad_dru"]:
            shutil.copy2(source.with_suffix(suffix), self.path.with_suffix(suffix))
        shutil.copy2(source.parent / "fp-lib-table", work / "fp-lib-table")
        shutil.copytree(source.parent / "Batman.pretty", work / "Batman.pretty", dirs_exist_ok=True)
        shutil.copy2(source, work / "saved-input.kicad_pcb")
        self.board = without_fills(sexpdata.loads(source.read_text(encoding="utf-8")))
        self.pads = read_pads(source)
        self.cli = Path(sys.executable).with_name("kicad-cli.exe")
        self.attempts = 0
        self.accepted = 0
        self.failed = set()

    def accept(self, removed, added):
        key = tuple(sorted(identifier(item) for item in removed)), tuple(sexpdata.dumps(item[:-1]) for item in added)
        if key in self.failed:
            return False
        trial = list(self.board)
        for item in removed:
            trial.remove(item)
        trial.extend(added)
        self.attempts += 1
        if check(trial, self.path, self.cli):
            self.board = trial
            self.accepted += 1
            shutil.copy2(self.path, self.work / "accepted.kicad_pcb")
            print(f"Accepted {self.accepted}: {len(segments(trial))} segments", flush=True)
            return True
        self.failed.add(key)
        return False

    def clearance_ok(self, added, removed):
        for item in added:
            route = line(item)
            width = float(field(item, "width")[1])
            for pad in self.pads:
                if pad["net"] == net(item) or pad["reference"].startswith("NT"):
                    continue
                gap = 1.0 if net(item) in RAW_NETS or pad["net"] in RAW_NETS else 0.65
                if route.distance(pad["shape"]) < width / 2 + gap - TOLERANCE:
                    return False
            for other in segments(self.board):
                if other in removed or net(item) == net(other):
                    continue
                gap = 1.0 if net(item) in RAW_NETS or net(other) in RAW_NETS else 0.65
                if route.distance(line(other)) < (width + float(field(other, "width")[1])) / 2 + gap - TOLERANCE:
                    return False
        return True

    def simplify(self):
        grouped = defaultdict(list)
        for item in segments(self.board):
            grouped[(net(item), tuple(field(item, "layer")[1:]), field(item, "width")[1])].append(item)
        candidates = []
        for (net_name, _, _), items in grouped.items():
            anchors = {pad["center"] for pad in self.pads if pad["net"] == net_name}
            for nodes, route in chains(items, anchors):
                for count in range(len(route), 1, -1):
                    for start in range(len(route) - count + 1):
                        removed = route[start:start + count]
                        for coordinates in paths(nodes[start], nodes[start + count]):
                            added = [make_segment(removed[0], first, second)
                                     for first, second in zip(coordinates, coordinates[1:])]
                            if len(added) >= len(removed) or any(length(item) < 1 - TOLERANCE for item in added):
                                continue
                            saving = sum(length(item) for item in removed) - sum(length(item) for item in added)
                            if saving < -TOLERANCE:
                                continue
                            candidates.append((len(removed) - len(added), saving, removed, added))
        candidates.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        for _, _, removed, added in candidates:
            if self.clearance_ok(added, removed) and self.accept(removed, added):
                return True
        return False

    def repair_pads(self):
        for item in segments(self.board):
            width = float(field(item, "width")[1])
            for pad in self.pads:
                if pad["net"] != net(item) or pad["reference"].startswith("W"):
                    continue
                if line(item).distance(pad["shape"]) > width / 2 + TOLERANCE:
                    continue
                center = pad["center"]
                if line(item).distance(Point(center)) < TOLERANCE:
                    continue
                for name in sorted(["start", "end"], key=lambda name: math.dist(endpoint(item, name), center)):
                    old = endpoint(item, name)
                    if Point(old).distance(pad["shape"]) > width / 2 + TOLERANCE:
                        continue
                    if any(net(other) == net(item) and identifier(other) != identifier(item)
                           and line(other).distance(Point(old)) < TOLERANCE for other in segments(self.board)):
                        continue
                    replacement = deepcopy(item)
                    field(replacement, name)[1:3] = center
                    if length(replacement) > TOLERANCE and self.clearance_ok([replacement], [item]):
                        if self.accept([item], [replacement]):
                            return True
        return False

    def repair_contacts(self):
        items = segments(self.board)
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if net(first) != net(second):
                    continue
                first_line, second_line = line(first), line(second)
                distance = first_line.distance(second_line)
                if distance < TOLERANCE or distance > (field(first, "width")[1] + field(second, "width")[1]) / 2 + TOLERANCE:
                    continue
                closest = nearest_points(first_line, second_line)
                coordinates = [point(value.coords[0]) for value in closest]
                for moving, fixed, location in [(first, second, coordinates[1]), (second, first, coordinates[0])]:
                    for name in sorted(["start", "end"], key=lambda name: math.dist(endpoint(moving, name), location)):
                        old = endpoint(moving, name)
                        if math.dist(old, location) > 2:
                            continue
                        if any(pad["net"] == net(moving) and math.dist(pad["center"], old) < TOLERANCE for pad in self.pads):
                            continue
                        removed, added = [], []
                        for connected in items:
                            if net(connected) != net(moving) or connected is fixed:
                                continue
                            replacement = deepcopy(connected)
                            changed = False
                            for endpoint_name in ["start", "end"]:
                                if endpoint(connected, endpoint_name) == old:
                                    field(replacement, endpoint_name)[1:3] = location
                                    changed = True
                            if changed:
                                removed.append(connected)
                                if length(replacement) > TOLERANCE:
                                    added.append(replacement)
                        if removed and self.clearance_ok(added, removed) and self.accept(removed, added):
                            return True
        return False

    def audit(self):
        items = segments(self.board)
        contacts = []
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if net(first) != net(second):
                    continue
                distance = line(first).distance(line(second))
                if TOLERANCE < distance <= (field(first, "width")[1] + field(second, "width")[1]) / 2 + TOLERANCE:
                    contacts.append({"net": net(first), "first": identifier(first), "second": identifier(second),
                                     "centerline_gap_mm": round(distance, 6)})
        return {"segments": len(items), "minimum_length_mm": min(map(length, items)),
                "below_1mm": sum(length(item) < 1 - TOLERANCE for item in items),
                "edge_only_contacts": contacts, "drc_trials": self.attempts}

    def run(self):
        before = self.audit()
        if not check(self.board, self.path, self.cli):
            raise RuntimeError("Saved input does not pass DRC")
        while self.repair_pads() or self.repair_contacts() or self.simplify():
            pass
        if not check(self.board, self.path, self.cli):
            raise RuntimeError("Final DRC failed")
        report = {"before": before, "after": self.audit()}
        (self.work / "straightening.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    Straightener(args.board, args.work).run()


if __name__ == "__main__":
    main()