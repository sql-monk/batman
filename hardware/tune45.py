from pathlib import Path

from shapely.geometry import LineString, box
from shapely.ops import unary_union
import sexpdata

import clean_paths
from octilinear import Octilinear, paths
from polish import endpoint, field, segments
from reroute_clean import validate
from straighten import line, make_segment, net


ROOT = Path(__file__).resolve().parent / "batman/reports/routing45"
clean_paths.paths = paths


def power_a():
    path = ROOT / "A/candidate.kicad_pcb"
    routes = Octilinear(path)
    items = [item for item in segments(routes.data) if net(item) == "+3V3"]
    for item in items:
        ends = [endpoint(item, kind) for kind in ["start", "end"]]
        if all(coordinate[1] >= 90 for coordinate in ends) or any(abs(coordinate[0] - 62.89) < 0.00001 or coordinate == (59, 42) for coordinate in ends):
            routes.data.remove(item)
    obstacles = unary_union([routes.obstacles("+3V3", 1.0), box(55, 43, 92, 101)])
    coordinates = routes.visibility((52, 42), (82.7, 102), obstacles)
    assert coordinates, "No exterior power path"
    routes.data.extend(make_segment(items[0], first, second) for first, second in zip(coordinates, coordinates[1:]))
    coordinates = [(82.7, 102), (94, 90.7), (95, 90.7), (95, 89)]
    assert routes.clear(coordinates, routes.obstacles("+3V3", 1.0))
    routes.data.extend(make_segment(items[0], first, second) for first, second in zip(coordinates, coordinates[1:]))
    path.write_text(sexpdata.dumps(routes.data), encoding="utf-8")
    return validate(path)


def ground_b(path=None, coordinates=None):
    path = path or ROOT / "B/candidate.kicad_pcb"
    routes = Octilinear(path)
    coordinates = coordinates or [(167, 67.1), (175, 67.1)]
    geometry = LineString(coordinates)
    conflicts = {net(item) for item in segments(routes.data)
                 if net(item) != "GND" and line(item).distance(geometry) < (field(item, "width")[1] + 1) / 2 + 0.675}
    saved = [item for item in segments(routes.data) if net(item) in conflicts]
    for item in saved:
        routes.data.remove(item)
    assert routes.clear(coordinates, routes.obstacles("GND", 1.0))
    for first, second in zip(coordinates, coordinates[1:]):
        template = make_segment(saved[0], first, second)
        field(template, "net")[1] = "GND"
        field(template, "width")[1] = 1.0
        routes.data.append(template)
    routes.data.extend(saved)
    print("Reroute around ground:", conflicts, flush=True)
    routes.redraw(conflicts, clear=True)


def divider_b():
    path = ROOT / "grounded-B/candidate.kicad_pcb"
    routes = Octilinear(path)
    first = [item for item in segments(routes.data) if net(item) == "U_B1"]
    for item in first:
        routes.data.remove(item)
    branches = [
        [(160.08, 46), (160.08, 51.8858), (164.46, 56.2658), (164.46, 59.9483), (164.46, 62)],
        [(164.46, 59.9483), (170.6273, 59.9483), (171.6273, 60.9483), (171.6273, 69.3727), (168, 73), (168, 75.1)],
        [(167, 70.9), (167, 72), (168, 73)],
    ]
    for coordinates in branches:
        routes.data.extend(make_segment(first[0], start, end) for start, end in zip(coordinates, coordinates[1:]))
    second = [item for item in segments(routes.data) if net(item) == "U_B2"]
    for item in second:
        ends = [endpoint(item, kind) for kind in ["start", "end"]]
        if all(coordinate[0] >= 175 and coordinate[1] >= 71.4129 for coordinate in ends):
            routes.data.remove(item)
    coordinates = [(175, 70.9), (175, 73), (176, 74), (176, 75.1)]
    routes.data.extend(make_segment(second[0], start, end) for start, end in zip(coordinates, coordinates[1:]))
    path.write_text(sexpdata.dumps(routes.data), encoding="utf-8")
    return validate(path)


if __name__ == "__main__":
    power_a()
    ground_b()