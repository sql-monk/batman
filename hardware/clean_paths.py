import argparse
from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
import pcbnew
import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
import sexpdata

import freeroute
from cad_common import track
from pcb import position
from polish import children, endpoint, field, length, segments, without_fills
from reroute_clean import validate
from straighten import chains, line, make_segment, net, paths, read_pads


class Routes:
    def __init__(self, path):
        self.path = path
        self.data = without_fills(sexpdata.loads(path.read_text(encoding="utf-8")))
        self.pads = read_pads(path)
        self.board = pcbnew.LoadBoard(str(path))
        bounds = self.board.GetBoardEdgesBoundingBox()
        self.bounds = box(pcbnew.ToMM(bounds.GetLeft()) + 1.2, pcbnew.ToMM(bounds.GetTop()) + 1.2,
                          pcbnew.ToMM(bounds.GetRight()) - 1.2, pcbnew.ToMM(bounds.GetBottom()) - 1.2)

    def obstacles(self, name, width):
        obstacles = []
        for pad in self.pads:
            if pad["net"] == name or pad["reference"].startswith("W"):
                continue
            gap = 1 if name in {"B1", "B2", "LOAD+", "VIN_DC"} or pad["net"] in {"B1", "B2", "LOAD+", "VIN_DC"} else 0.65
            obstacles.append(pad["shape"].buffer(width / 2 + gap + 0.025))
        for item in segments(self.data):
            if net(item) == name:
                continue
            gap = 1 if name in {"B1", "B2", "LOAD+", "VIN_DC"} or net(item) in {"B1", "B2", "LOAD+", "VIN_DC"} else 0.65
            obstacles.append(line(item).buffer((width + field(item, "width")[1]) / 2 + gap + 0.025))
        for zone in self.board.Zones():
            if zone.GetIsRuleArea():
                bounds = zone.GetBoundingBox()
                obstacles.append(box(pcbnew.ToMM(bounds.GetLeft()), pcbnew.ToMM(bounds.GetTop()),
                                     pcbnew.ToMM(bounds.GetRight()), pcbnew.ToMM(bounds.GetBottom())).buffer(width / 2 + 0.025))
        return unary_union(obstacles)

    def clear(self, coordinates, obstacles):
        route = LineString(coordinates)
        return self.bounds.covers(route) and not route.intersects(obstacles)

    def simplify(self):
        total = 0
        grouped = defaultdict(list)
        for item in segments(self.data):
            grouped[(net(item), field(item, "width")[1])].append(item)
        for (name, width), items in grouped.items():
            anchors = {pad["center"] for pad in self.pads if pad["net"] == name}
            for item in items:
                for other in items:
                    if item is other:
                        continue
                    for kind in ["start", "end"]:
                        coordinate = endpoint(item, kind)
                        if line(other).distance(Point(coordinate)) < 0.00001:
                            anchors.add(coordinate) if coordinate not in [endpoint(other, "start"), endpoint(other, "end")] else None
            obstacles = self.obstacles(name, width)
            for nodes, route in chains(items, anchors):
                if len(route) < 2:
                    continue
                graph = nx.DiGraph()
                for first in range(len(nodes) - 1):
                    graph.add_edge(first, first + 1, weight=1000 + length(route[first]), coordinates=[nodes[first], nodes[first + 1]])
                    for second in range(first + 2, len(nodes)):
                        for coordinates in paths(nodes[first], nodes[second]):
                            if any(math.dist(start, end) < 0.99999 for start, end in zip(coordinates, coordinates[1:])):
                                continue
                            if not self.clear(coordinates, obstacles):
                                continue
                            weight = 1000 * (len(coordinates) - 1) + LineString(coordinates).length
                            if not graph.has_edge(first, second) or graph[first][second]["weight"] > weight:
                                graph.add_edge(first, second, weight=weight, coordinates=coordinates)
                sequence = nx.shortest_path(graph, 0, len(nodes) - 1, weight="weight")
                replacement = []
                for first, second in zip(sequence, sequence[1:]):
                    coordinates = graph[first][second]["coordinates"]
                    replacement.extend(make_segment(route[0], start, end) for start, end in zip(coordinates, coordinates[1:]))
                if len(replacement) < len(route):
                    for item in route:
                        self.data.remove(item)
                    self.data.extend(replacement)
                    total += len(route) - len(replacement)
        print(f"Removed {total} unnecessary segments by whole-path shortcuts", flush=True)
        self.path.write_text(sexpdata.dumps(self.data), encoding="utf-8")
        return validate(self.path)

    def visibility(self, start, end, obstacles):
        expanded = obstacles.buffer(0.04).simplify(0.015, preserve_topology=True)
        polygons = list(expanded.geoms) if expanded.geom_type == "MultiPolygon" else [expanded]
        vertices = [start, end]
        for polygon in polygons:
            for ring in [polygon.exterior, *polygon.interiors]:
                vertices.extend(tuple(coordinate) for coordinate in ring.coords[:-1] if self.bounds.covers(Point(coordinate)))
        vertices = list(dict.fromkeys(vertices))
        graph = nx.Graph()
        graph.add_nodes_from(range(len(vertices)))
        for index, start_point in enumerate(vertices[:-1]):
            following = np.asarray(vertices[index + 1:])
            lengths = np.linalg.norm(following - np.asarray(start_point), axis=1)
            coordinates = np.stack([np.broadcast_to(start_point, following.shape), following], axis=1)
            routes = shapely.linestrings(coordinates)
            valid = (lengths >= 0.99999) & ~shapely.intersects(routes, obstacles)
            for offset in np.flatnonzero(valid):
                graph.add_edge(index, index + 1 + int(offset), weight=float(lengths[offset]) + 12)
        try:
            return [vertices[index] for index in nx.shortest_path(graph, 0, 1, weight="weight")]
        except nx.NetworkXNoPath:
            return None

    def finish(self):
        groups = freeroute.copper_groups(self.board)
        for name, clusters in groups.items():
            if len(clusters) < 2:
                continue
            width = 1.2 if name in {"B1", "B2", "LOAD+", "VIN_DC"} else 1.0 if name.startswith("+") or name == "GND" else 0.8
            obstacles = self.obstacles(name, width)
            options = sorted((math.dist(position(first), position(second)), position(first), position(second))
                             for index, cluster in enumerate(clusters) for other in clusters[index + 1:]
                             for first in cluster for second in other)
            for _, start, end in options[:12]:
                coordinates = next((candidate for candidate in paths(start, end) if self.clear(candidate, obstacles)), None)
                if coordinates is None:
                    coordinates = self.visibility(start, end, obstacles)
                if coordinates:
                    for first, second in zip(coordinates, coordinates[1:]):
                        track(self.board, name, first, second, width)
                    pcbnew.SaveBoard(str(self.path), self.board)
                    print(f"Connected {name} with {len(coordinates)-1} straight segments", flush=True)
                    return validate(self.path)
        raise RuntimeError("No clear route found for remaining connections")

    def redraw(self, names=None, clear=False):
        grouped = defaultdict(list)
        for item in segments(self.data):
            if names is None or net(item) in names:
                grouped[net(item)].append(item)
        if clear:
            self.data[:] = [item for item in self.data if item not in segments(self.data) or net(item) not in grouped]
        for name, old in sorted(grouped.items(), key=lambda entry: names.index(entry[0]) if isinstance(names, list) else len(entry[1])):
            if name == "GND":
                continue
            terminals = sorted({pad["center"] for pad in self.pads if pad["net"] == name
                                and not pad["reference"].startswith("W") and pad["reference"] != "NT1.1"})
            if len(terminals) < 2:
                continue
            parents = {coordinate: coordinate for coordinate in terminals}
            def root(coordinate):
                while parents[coordinate] != coordinate:
                    parents[coordinate] = parents[parents[coordinate]]
                    coordinate = parents[coordinate]
                return coordinate
            for footprint in self.board.GetFootprints():
                if not footprint.GetReference().startswith("W"):
                    continue
                ends = [position(pad) for pad in footprint.Pads() if pad.GetNetname() == name and position(pad) in parents]
                for coordinate in ends[1:]:
                    parents[root(coordinate)] = root(ends[0])
            for item in old:
                if item in self.data:
                    self.data.remove(item)
            width = field(old[0], "width")[1]
            obstacles = self.obstacles(name, width)
            edges = sorted((math.dist(first, second), first, second) for index, first in enumerate(terminals)
                           for second in terminals[index + 1:])
            added = []
            for _, start, end in edges:
                if root(start) == root(end):
                    continue
                coordinates = next((candidate for candidate in paths(start, end)
                                    if all(math.dist(first, second) >= 0.99999 for first, second in zip(candidate, candidate[1:]))
                                    and self.clear(candidate, obstacles)), None)
                if coordinates is None:
                    coordinates = self.visibility(start, end, obstacles)
                if coordinates:
                    added.extend(make_segment(old[0], first, second) for first, second in zip(coordinates, coordinates[1:]))
                    parents[root(start)] = root(end)
                if len({root(coordinate) for coordinate in terminals}) == 1:
                    break
            if len({root(coordinate) for coordinate in terminals}) == 1:
                self.data.extend(added)
                print(f"Redrew {name}: {len(old)} -> {len(added)} straight segments", flush=True)
            else:
                self.data.extend(old)
                print(f"Kept new autoroute for {name}: no complete replacement path", flush=True)
        self.path.write_text(sexpdata.dumps(self.data), encoding="utf-8")
        return validate(self.path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--finish", action="store_true")
    parser.add_argument("--redraw", action="store_true")
    parser.add_argument("--ground", action="store_true")
    args = parser.parse_args()
    routes = Routes(args.path)
    if args.ground:
        routes.data[:] = [item for item in routes.data if item not in segments(routes.data) or net(item) != "GND"]
        routes.path.write_text(sexpdata.dumps(routes.data), encoding="utf-8")
        validate(routes.path)
    elif args.finish:
        routes.finish()
    elif args.redraw:
        routes.redraw()
    else:
        routes.simplify()