from collections import defaultdict, deque
from heapq import heappop, heappush
from pathlib import Path
import csv
import json
import math

import numpy as np
import pcbnew

from circuit import circuit, validate
from cad_common import point, outline, track, new_board
from schematic import uid, generate as generate_schematic


ROOT = Path(__file__).resolve().parent / "batman"
LIB = ROOT / "Batman.pretty"
ORIGINS = {"A": (30, 30)}
GRID = 0.25


def position(item):
    value = item.GetPosition()
    return pcbnew.ToMM(value.x), pcbnew.ToMM(value.y)


def draw_text(board, content, x, y, size=1.0, layer=pcbnew.F_SilkS):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(content)
    item.SetPosition(point(x, y))
    item.SetTextSize(point(size, size))
    item.SetTextThickness(pcbnew.FromMM(0.15))
    item.SetLayer(layer)
    board.Add(item)


def add_pad(board, item, number, x, y, net, diameter=2.0, drill=0.8, smd=False):
    pad = pcbnew.PAD(item)
    pad.SetNumber(str(number))
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD if smd else pcbnew.PAD_ATTRIB_PTH)
    pad.SetShape(pcbnew.PAD_SHAPE_RECT if smd else pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(2, 1.6) if smd else point(diameter, diameter))
    if smd:
        layers = pcbnew.LSET()
        layers.AddLayer(pcbnew.B_Cu)
        pad.SetLayerSet(layers)
    else:
        pad.SetDrillSize(point(drill, drill))
        pad.SetLayerSet(pcbnew.LSET.AllCuMask())
    pad.SetPosition(point(x, y))
    if net:
        pad.SetNet(board.FindNet(net))
    item.Add(pad)
    return pad


def create_part(board, part, rotation=0):
    origin = ORIGINS[part.board]
    x, y = origin[0] + part.position[0], origin[1] + part.position[1]
    item = pcbnew.FOOTPRINT(board)
    item.SetReference(part.ref)
    item.SetValue(part.value)
    item.SetPosition(point(x, y))
    item.SetAttributes(pcbnew.FP_SMD if part.kind == "R" else pcbnew.FP_THROUGH_HOLE)
    if part.ref == "D3":
        item.SetAttributes(item.GetAttributes() | pcbnew.FP_DNP)
    item.SetPath(pcbnew.KIID_PATH(f'/{uid("root")}/{uid("sheet/" + part.sheet)}/{uid("symbol/" + part.ref)}'))
    name = "LUT_" + part.ref
    part.footprint = "Batman:" + name
    item.SetFPID(pcbnew.LIB_ID("Batman", name))
    field = pcbnew.PCB_FIELD(item, pcbnew.FIELD_T_USER, "Board")
    field.SetText(part.board)
    field.SetVisible(False)
    item.Add(field)
    alias_field = pcbnew.PCB_FIELD(item, pcbnew.FIELD_T_USER, "Alias")
    alias_field.SetText(part.alias)
    alias_field.SetVisible(False)
    item.Add(alias_field)
    item.Reference().SetPosition(point(x, y - 2.5))
    item.Reference().SetTextSize(point(0.9, 0.9))
    item.Reference().SetTextThickness(pcbnew.FromMM(0.12))
    if part.kind == "net_tie":
        item.Reference().SetVisible(False)
    item.Value().SetVisible(False)
    board.Add(item)
    nets = [net or f"unconnected-({part.ref}-{name}-Pad{number})" for number, name, net, _ in part.pins]
    if part.kind == "net_tie":
        item.SetAttributes(pcbnew.FP_SMD)
        item.AddNetTiePadGroup("1,2,3")
        for index, (dx, dy) in enumerate([(0, 0), (0, 3.5), (3.5, 3.5)]):
            add_pad(board, item, index + 1, x + dx, y + dy, nets[index], smd=True)
        for end in [(x, y + 3.5), (x + 3.5, y + 3.5)]:
            copper = pcbnew.PCB_SHAPE(item)
            copper.SetShape(pcbnew.SHAPE_T_SEGMENT)
            copper.SetStart(point(x, y))
            copper.SetEnd(point(*end))
            copper.SetWidth(pcbnew.FromMM(0.7))
            copper.SetLayer(pcbnew.B_Cu)
            item.Add(copper)
    elif part.kind == "R":
        for index, dx in enumerate([-1.9, 1.9]):
            add_pad(board, item, index + 1, x + dx, y, nets[index], smd=True)
    elif part.kind in ["C", "C_bus"]:
        vertical = part.kind == "C_bus"
        for index in range(2):
            dx = 0 if vertical else (index * 5.08 - 2.54)
            dy = index * 5.08 if vertical else 0
            add_pad(board, item, index + 1, x + dx, y + dy, nets[index])
            smd_x = 0 if vertical else (index * 3.8 - 1.9)
            smd_y = 0.64 + index * 3.8 if vertical else 0
            pad = add_pad(board, item, index + 1, x + smd_x, y + smd_y, nets[index], smd=True)
            if vertical:
                pad.SetSize(point(1.6, 2))
    elif part.kind in ["D", "TVS", "CP"]:
        for index in range(2):
            dx = (index * 7.62 - 3.81) if part.kind == "D" else 0
            dy = index * (10.16 if part.kind == "TVS" else 5) if part.kind != "D" else 0
            add_pad(board, item, index + 1, x + dx, y + dy, nets[index],
                    2.0 if part.kind == "CP" else 2.4, 0.8 if part.kind == "CP" else 1.1)
    elif part.kind in ["NPN", "PNP"]:
        for index, (dx, dy) in enumerate([(-2.54, 0), (0, 2.54), (2.54, 0)]):
            add_pad(board, item, index + 1, x + dx, y + dy, nets[index])
    else:
        for index, net in enumerate(nets):
            if part.kind == "MCU":
                dx, dy = (25.4 if index >= 19 else 0), (index % 19) * 2.54
            elif part.kind in ["header_h", "terminal"]:
                dx, dy = index * (5 if part.kind == "terminal" else 2.54), 0
            else:
                dx, dy = 0, index * 2.54
            add_pad(board, item, index + 1, x + dx, y + dy, net,
                    3.5 if part.kind == "terminal" else 2, 1.5 if part.kind == "terminal" else 0.8)
    item.SetOrientationDegrees(rotation)
    if part.ref == "J1":
        draw_text(board, "J1: USB BELOW / ANTENNA ABOVE", x + 12.7, y + 49, 0.8, pcbnew.F_Fab)
    for pad in item.Pads():
        px, py = position(pad)
        if part.kind in ["header", "header_h", "terminal", "MCU", "NPN", "PNP", "D", "TVS", "CP"]:
            label = pad.GetNumber()
            if part.kind in ["NPN", "PNP", "D", "TVS"]:
                label += ":" + part.pins[int(pad.GetNumber()) - 1][1]
            if part.kind == "CP":
                label += ":+" if pad.GetNumber() == "1" else ":-"
            label_x, label_y = px, py + 1.7
            if part.kind == "MCU":
                label_x = px + 2.3 if int(pad.GetNumber()) <= 19 else px - 2.3
                label_y = py
            elif part.kind in ["header", "header_h"]:
                vertical = (part.kind == "header") != (abs(rotation) % 180 == 90)
                if vertical:
                    label_x, label_y = px - 2, py
            elif part.kind in ["TVS", "CP"]:
                label_x, label_y = px + 2.5, py
            elif part.kind == "terminal":
                label_y = py + 2.7
            draw_text(board, label, label_x, label_y, 0.7, pcbnew.F_Fab)
    return item


def add_assembly_guides(board):
    for item in board.GetFootprints():
        if item.GetReference().startswith(("W", "H", "NT")):
            continue
        if any(graphic.GetLayer() == pcbnew.F_Fab for graphic in item.GraphicalItems()):
            continue
        for pad in item.Pads():
            center_x, center_y = position(pad)
            width, height = pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y)
            if abs(pad.GetOrientationDegrees() % 180 - 90) < 0.01:
                width, height = height, width
            guide = pcbnew.PCB_SHAPE(item)
            guide.SetLayer(pcbnew.F_Fab)
            guide.SetWidth(pcbnew.FromMM(0.12))
            if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                guide.SetShape(pcbnew.SHAPE_T_CIRCLE)
                guide.SetCenter(point(center_x, center_y))
                guide.SetEnd(point(center_x + width / 2, center_y))
            else:
                guide.SetShape(pcbnew.SHAPE_T_RECT)
                guide.SetStart(point(center_x - width / 2, center_y - height / 2))
                guide.SetEnd(point(center_x + width / 2, center_y + height / 2))
            item.Add(guide)


def arrange_labels(board):
    labels = [item.Reference() for item in board.GetFootprints() if item.Reference().IsVisible()]
    labels.extend(item for item in board.GetDrawings() if isinstance(item, pcbnew.PCB_TEXT)
                  and item.GetLayer() == pcbnew.F_Fab)
    obstacles = []
    edges = board.GetBoardEdgesBoundingBox()
    board_left, board_top = pcbnew.ToMM(edges.GetX()), pcbnew.ToMM(edges.GetY())
    board_right = board_left + pcbnew.ToMM(edges.GetWidth())
    board_bottom = board_top + pcbnew.ToMM(edges.GetHeight())
    for item in board.GetFootprints():
        for pad in item.Pads():
            bounds = pad.GetBoundingBox()
            left, top = pcbnew.ToMM(bounds.GetX()), pcbnew.ToMM(bounds.GetY())
            obstacles.append((left - 0.15, top - 0.15,
                              left + pcbnew.ToMM(bounds.GetWidth()) + 0.15,
                              top + pcbnew.ToMM(bounds.GetHeight()) + 0.15))
    for label in labels:
        label.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))
        original = position(label)
        candidates = sorted((math.hypot(dx, dy), dx / 2, dy / 2)
                    for dx in range(-12, 13) for dy in range(-12, 13))
        for _, dx, dy in candidates:
            label.SetPosition(point(original[0] + dx, original[1] + dy))
            bounds = label.GetBoundingBox()
            left, top = pcbnew.ToMM(bounds.GetX()) - 0.15, pcbnew.ToMM(bounds.GetY()) - 0.15
            right, bottom = left + pcbnew.ToMM(bounds.GetWidth()) + 0.3, top + pcbnew.ToMM(bounds.GetHeight()) + 0.3
            if left < board_left + 0.8 or right > board_right - 0.8 or top < board_top + 0.8 or bottom > board_bottom - 0.8:
                continue
            if any(left < other_right and right > other_left and top < other_bottom and bottom > other_top
                   for other_left, other_top, other_right, other_bottom in obstacles):
                continue
            obstacles.append((left, top, right, bottom))
            break
        else:
            raise ValueError(f"No clear label position for {label.GetText()}")


def mount(board, ref, x, y):
    item = pcbnew.FOOTPRINT(board)
    item.SetReference(ref)
    item.SetValue("M3_NPTH_3.4")
    item.SetPosition(point(x, y))
    item.SetFPID(pcbnew.LIB_ID("Batman", "Mount_M3"))
    item.SetAttributes(pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    item.Reference().SetVisible(False)
    item.Value().SetVisible(False)
    board.Add(item)
    pad = add_pad(board, item, "", x, y, None, 3.4, 3.4)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)


class Router:
    def __init__(self, board, track_width=0.7, clearance=0.5):
        self.board = board
        self.track_width = track_width
        self.clearance = clearance
        bounds = board.GetBoardEdgesBoundingBox()
        self.width = round(pcbnew.ToMM(bounds.GetWidth()) / GRID) + 1
        self.height = round(pcbnew.ToMM(bounds.GetHeight()) / GRID) + 1
        self.grid = np.zeros((self.width, self.height), dtype=np.int32)
        self.grid[:5, :] = self.grid[-5:, :] = -1
        self.grid[:, :5] = self.grid[:, -5:] = -1
        for zone in board.Zones():
            if zone.GetIsRuleArea():
                bounds = zone.Outline().BBox()
                lower_x = pcbnew.ToMM(bounds.GetX()) - 30
                lower_y = pcbnew.ToMM(bounds.GetY()) - 30
                width = pcbnew.ToMM(bounds.GetWidth())
                height = pcbnew.ToMM(bounds.GetHeight())
                self.paint(lower_x + width / 2, lower_y + height / 2,
                           width / 2 + 0.4, height / 2 + 0.4, -1, False)
        self.pads = defaultdict(list)
        self.drills = []
        self.bodies = []
        self.wires = []
        for item in board.GetFootprints():
            x, y = position(item)
            if not 30 <= x <= 130:
                continue
            bounds = []
            for pad in item.Pads():
                px, py = position(pad)
                px, py = px - 30, py - 30
                net = pad.GetNetCode() or -1
                size = pad.GetSize()
                sx, sy = pcbnew.ToMM(size.x), pcbnew.ToMM(size.y)
                if abs(pad.GetOrientationDegrees() % 180 - 90) < 0.01:
                    sx, sy = sy, sx
                margin = track_width / 2 + clearance + 0.075
                self.paint(px, py, sx / 2 + margin, sy / 2 + margin, net,
                           pad.GetShape() != pcbnew.PAD_SHAPE_RECT)
                usable = net > 0 and not pad.GetNetname().startswith("unconnected-")
                if usable and pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                    self.pads[net].append((px, py))
                elif usable and (item.GetReference().startswith("R") or item.GetReference() == "NT1"):
                    self.pads[net].append((px, py))
                drill = pcbnew.ToMM(pad.GetDrillSize().x)
                if drill:
                    self.drills.append((px, py, drill))
                bounds.append((px, py))
            if bounds:
                self.bodies.append((min(px for px, _ in bounds) - 1.4, min(py for _, py in bounds) - 1.4,
                                    max(px for px, _ in bounds) + 1.4, max(py for _, py in bounds) + 1.4))

    def paint(self, x, y, rx, ry, net, circle=True):
        min_x, max_x = max(0, math.floor((x - rx) / GRID)), min(self.width - 1, math.ceil((x + rx) / GRID))
        min_y, max_y = max(0, math.floor((y - ry) / GRID)), min(self.height - 1, math.ceil((y + ry) / GRID))
        for column in range(min_x, max_x + 1):
            for row in range(min_y, max_y + 1):
                dx, dy = column * GRID - x, row * GRID - y
                if circle and (dx / rx) ** 2 + (dy / ry) ** 2 > 1:
                    continue
                if not circle and (abs(dx) > rx or abs(dy) > ry):
                    continue
                old = self.grid[column, row]
                self.grid[column, row] = net if old == 0 or old == net else -1

    def cell(self, xy):
        return round(xy[0] / GRID), round(xy[1] / GRID)

    def find(self, start, end, net, congestion=None):
        origin, target = self.cell(start), self.cell(end)
        if self.grid[origin] not in (0, net) or self.grid[target] not in (0, net):
            return None
        queue = [(0, 0, origin)]
        costs = {origin: 0}
        parents = {}
        while queue:
            _, cost, current = heappop(queue)
            if current == target:
                route = [current]
                while current != origin:
                    current = parents[current]
                    route.append(current)
                return list(reversed(route))
            if cost != costs[current]:
                continue
            column, row = current
            for neighbor in [(column + 1, row), (column - 1, row), (column, row + 1), (column, row - 1)]:
                nx, ny = neighbor
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                if self.grid[neighbor] not in (0, net):
                    continue
                next_cost = cost + 1 + (int(congestion[neighbor]) if congestion is not None else 0)
                if next_cost < costs.get(neighbor, 1000000):
                    costs[neighbor] = next_cost
                    parents[neighbor] = current
                    distance = abs(nx - target[0]) + abs(ny - target[1])
                    heappush(queue, (next_cost + distance, next_cost, neighbor))
        return None

    def commit(self, route, start, end, net):
        coordinates = [start] + [(column * GRID, row * GRID) for column, row in route] + [end]
        simplified = []
        for coordinate in coordinates:
            if simplified and coordinate == simplified[-1]:
                continue
            while len(simplified) >= 2:
                previous, last = simplified[-2:]
                if (last[0] - previous[0]) * (coordinate[1] - last[1]) != (last[1] - previous[1]) * (coordinate[0] - last[0]):
                    break
                simplified.pop()
            simplified.append(coordinate)
        net_name = self.board.FindNet(net).GetNetname()
        for first, second in zip(simplified, simplified[1:]):
            track(self.board, net_name, (first[0] + 30, first[1] + 30), (second[0] + 30, second[1] + 30), self.track_width)
            length = math.dist(first, second)
            for index in range(max(1, math.ceil(length / 0.2)) + 1):
                fraction = index / max(1, math.ceil(length / 0.2))
                x, y = first[0] + (second[0] - first[0]) * fraction, first[1] + (second[1] - first[1]) * fraction
                margin = self.track_width + self.clearance + 0.075
                self.paint(x, y, margin, margin, net)

    def landing(self, source, net):
        origin = self.cell(source)
        queue = deque([origin])
        parents = {origin: None}
        while queue:
            current = queue.popleft()
            x, y = current[0] * GRID, current[1] * GRID
            valid = 3 <= x <= 97 and 3 <= y <= 77
            if valid and math.dist((x, y), source) >= 2.6:
                valid = not any(left - 0.3 < x < right + 0.3 and top - 0.3 < y < bottom + 0.3
                                for left, top, right, bottom in self.bodies)
                valid = valid and all(math.dist((x, y), (px, py)) > 0.55 + drill / 2 + 0.4
                                      for px, py, drill in self.drills)
                if valid:
                    column, row = current
                    neighborhood = self.grid[column - 4:column + 5, row - 4:row + 5]
                    valid = bool(np.all((neighborhood == 0) | (neighborhood == net)))
                if valid:
                    route = [current]
                    while parents[current] is not None:
                        current = parents[current]
                        route.append(current)
                    return (x, y), list(reversed(route))
            column, row = current
            for neighbor in [(column + 1, row), (column - 1, row), (column, row + 1), (column, row - 1)]:
                nx, ny = neighbor
                if (0 <= nx < self.width and 0 <= ny < self.height and neighbor not in parents
                        and self.grid[neighbor] in (0, net)):
                    parents[neighbor] = current
                    queue.append(neighbor)
        print(f"Lead-solder wire endpoint: {source}, {self.board.FindNet(net).GetNetname()}", flush=True)
        return source, []

    def jumper(self, first, second, net):
        first_landing, first_route = self.landing(first, net)
        self.commit(first_route, first, first_landing, net)
        if first_route:
            self.paint(*first_landing, 2.125, 2.125, net)
            self.drills.append((*first_landing, 1.1))
            self.bodies.append((first_landing[0] - 1.5, first_landing[1] - 1.5, first_landing[0] + 1.5, first_landing[1] + 1.5))
        second_landing, second_route = self.landing(second, net)
        self.commit(second_route, second, second_landing, net)
        if second_route:
            self.paint(*second_landing, 2.125, 2.125, net)
            self.drills.append((*second_landing, 1.1))
            self.bodies.append((second_landing[0] - 1.5, second_landing[1] - 1.5, second_landing[0] + 1.5, second_landing[1] + 1.5))
        ref = f"W{len(self.wires) + 1}"
        net_name = self.board.FindNet(net).GetNetname()
        add_jumper(self.board, ref, net_name, (first_landing[0] + 30, first_landing[1] + 30),
                   (second_landing[0] + 30, second_landing[1] + 30), (not first_route, not second_route))
        self.wires.append([ref, net_name, *first_landing, *second_landing, round(math.dist(first_landing, second_landing) + 10, 1),
                       "existing pad" if not first_route else "1.1 mm hole", "existing pad" if not second_route else "1.1 mm hole"])

    def run(self):
        connections = defaultdict(list)
        for net, pads in self.pads.items():
            remaining = list(dict.fromkeys(pads))
            connected = [remaining.pop(0)]
            while remaining:
                _, first, second = min((math.dist(first, second), first, second)
                                       for first in connected for second in remaining)
                connections[net].append((first, second))
                connected.append(second)
                remaining.remove(second)
        masks = {}
        paths = {}
        history = np.zeros_like(self.grid)
        best = None
        offsets = [(dx, dy) for dx in range(-5, 6) for dy in range(-5, 6)
                   if dx * dx + dy * dy <= (1.275 / GRID) ** 2]
        for attempt in range(12):
            occupancy = sum(masks.values(), np.zeros_like(self.grid))
            order = sorted(connections, key=lambda net: (len(connections[net]) > 5,
                           -sum(int(occupancy[self.cell(pad)]) for pad in self.pads[net]), net))
            for net in order:
                if net in masks:
                    occupancy -= masks[net]
                congestion = occupancy * (8 + attempt * 4) + history
                mask = np.zeros_like(self.grid)
                paths[net] = []
                for first, second in connections[net]:
                    route = self.find(first, second, net, congestion)
                    paths[net].append((first, second, route))
                    if route:
                        coordinates = np.array(route)
                        for dx, dy in offsets:
                            columns = np.clip(coordinates[:, 0] + dx, 0, self.width - 1)
                            rows = np.clip(coordinates[:, 1] + dy, 0, self.height - 1)
                            mask[columns, rows] = 1
                        congestion[coordinates[:, 0], coordinates[:, 1]] = 0
                masks[net] = mask
                occupancy += mask
            candidates = [(net, first, second, route) for net, routes in paths.items()
                          for first, second, route in routes if route]
            conflicts = [set() for _ in candidates]
            route_masks = []
            for net, first, second, route in candidates:
                mask = np.zeros(self.grid.shape, dtype=bool)
                coordinates = np.array(route)
                for dx, dy in offsets:
                    mask[np.clip(coordinates[:, 0] + dx, 0, self.width - 1),
                         np.clip(coordinates[:, 1] + dy, 0, self.height - 1)] = True
                route_masks.append(mask)
            for index, (net, first, second, route) in enumerate(candidates):
                for other in range(index):
                    if net == candidates[other][0]:
                        continue
                    coordinates = np.array(candidates[other][3])
                    if route_masks[index][coordinates[:, 0], coordinates[:, 1]].any():
                        conflicts[index].add(other)
                        conflicts[other].add(index)
            removed = set()
            while any(conflicts):
                index = max(range(len(conflicts)), key=lambda value: len(conflicts[value]))
                removed.add(index)
                for other in conflicts[index]:
                    conflicts[other].discard(index)
                conflicts[index].clear()
            accepted = [candidate for index, candidate in enumerate(candidates) if index not in removed]
            failures = [(net, first, second) for index, (net, first, second, route) in enumerate(candidates) if index in removed]
            failures += [(net, first, second) for net, routes in paths.items() for first, second, route in routes if not route]
            print(f"Routing pass {attempt + 1}: {len(failures)} wire bridges", flush=True)
            if best is None or len(failures) < len(best[1]):
                best = accepted, failures
            for index in removed:
                net, first, second, route = candidates[index]
                coordinates = np.array(route)
                foreign = occupancy[coordinates[:, 0], coordinates[:, 1]] - masks[net][coordinates[:, 0], coordinates[:, 1]]
                contested = coordinates[foreign > 0]
                history[contested[:, 0], contested[:, 1]] += 2
            if not failures:
                break
        accepted, failures = best
        for net, first, second, route in accepted:
            self.commit(route, first, second, net)
        print(f"Copper routes: {len(accepted)}; wire bridges needed: {len(failures)}", flush=True)
        for net, first, second in failures:
            self.jumper(first, second, net)
        return self.wires


def add_jumper(board, ref, net, first, second, existing=(False, False)):
    contacts = []
    for endpoint, reuse in zip([first, second], existing):
        contacts.append(next((pad for owner in board.GetFootprints() for pad in owner.Pads()
                              if math.dist(position(pad), endpoint) < 0.01 and pad.GetNetname() == net), None) if reuse else None)
    item = pcbnew.FOOTPRINT(board)
    item.SetReference(ref)
    item.SetValue("INSULATED_WIRE")
    item.SetPosition(point(*first))
    item.SetFPID(pcbnew.LIB_ID("Batman", "LUT_" + ref))
    item.SetAttributes(pcbnew.FP_THROUGH_HOLE | pcbnew.FP_BOARD_ONLY)
    item.SetDuplicatePadNumbersAreJumpers(True)
    item.Reference().SetVisible(False)
    item.Value().SetVisible(False)
    board.Add(item)
    for (x, y), reuse, contact in zip([first, second], existing, contacts):
        pad = add_pad(board, item, 1, x, y, net, 2.4, 1.1)
        if reuse:
            assert contact is not None, (ref, x, y)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetDrillSize(point(0, 0))
            pad.SetSize(contact.GetSize())
            pad.SetShape(contact.GetShape())
            pad.SetOrientationDegrees(contact.GetOrientationDegrees())
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.B_Cu)
            pad.SetLayerSet(layers)
        draw_text(board, ref, x, y - 1.9, 0.75, pcbnew.Dwgs_User)
    graphic = pcbnew.PCB_SHAPE(item)
    graphic.SetShape(pcbnew.SHAPE_T_SEGMENT)
    graphic.SetStart(point(*first))
    graphic.SetEnd(point(*second))
    graphic.SetWidth(pcbnew.FromMM(0.15))
    graphic.SetLayer(pcbnew.Dwgs_User)
    item.Add(graphic)


def build(route=True):
    ROOT.mkdir(parents=True, exist_ok=True)
    LIB.mkdir(exist_ok=True)
    parts = circuit()
    validate(parts)
    nets = sorted({net or f"unconnected-({part.ref}-{name}-Pad{number})"
                   for part in parts if part.board for number, name, net, _ in part.pins})
    board = new_board(nets)
    outline(board, 30, 30, 100, 80)
    keepout = pcbnew.ZONE(board)
    keepout.SetIsRuleArea(True)
    keepout.SetLayerSet(pcbnew.LSET.AllCuMask())
    keepout.SetDoNotAllowTracks(True)
    keepout.SetDoNotAllowVias(True)
    keepout.SetDoNotAllowZoneFills(True)
    keepout.SetDoNotAllowPads(True)
    keepout.SetZoneName("ESP32_ANTENNA_NO_COPPER")
    layout = json.loads(Path(__file__).with_name("floorplan.json").read_text(encoding="utf-8"))
    mcu_x, mcu_y = layout["J1"]["position"]
    assert layout["J1"]["rotation"] == 0
    polygon = keepout.Outline()
    polygon.NewOutline()
    for x, y in [(mcu_x + 26, max(30, mcu_y + 16)), (mcu_x + 59.8, max(30, mcu_y + 16)),
                 (mcu_x + 59.8, mcu_y + 28), (mcu_x + 26, mcu_y + 28)]:
        polygon.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(keepout)
    for part in parts:
        if part.board:
            part.position = tuple(layout[part.ref]["position"])
            create_part(board, part, layout[part.ref]["rotation"])
    for index, xy in enumerate([(33.5, 33.5), (126.5, 33.5), (33.5, 106.5), (126.5, 106.5)], 1):
        mount(board, f"H{index}", *xy)
    arrange_labels(board)
    if not route:
        return board
    router = Router(board)
    wires = router.run()
    draw_text(board, "A - LOGIC / 100 x 80", 80, 45, 1.0, pcbnew.F_Fab)
    draw_text(board, "ALT: SDA SCL GND VCC -> REWIRE", 77, 114, 0.8, pcbnew.Dwgs_User)
    draw_text(board, "OLED J10: GND VDD SCK SDA", 80, 117, 0.8, pcbnew.F_Fab)
    plugin = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    for item in board.GetFootprints():
        plugin.FootprintSave(str(LIB), item)
    (ROOT / "fp-lib-table").write_text('(fp_lib_table (version 7) (lib (name "Batman") (type "KiCad") (uri "${KIPRJMOD}/Batman.pretty") (options "") (descr "Local single-sided LUT footprints")))\n', encoding="utf-8")
    pcbnew.SaveBoard(str(ROOT / "batman.kicad_pcb"), board)
    with (ROOT / "jumpers.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Ref", "Net", "A_X1_mm", "A_Y1_mm", "X2_mm", "Y2_mm", "Wire_cut_min_mm", "End1", "End2"])
        writer.writerows(wires)
    generate_schematic(parts)
    print(f"Saved PCB with {len(board.GetFootprints())} footprints and {len(wires)} wires", flush=True)


if __name__ == "__main__":
    raise SystemExit("Legacy single-board entry point disabled. Use hardware/modular.py; see hardware/README.md")