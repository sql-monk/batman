import argparse
import heapq
import math
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Point

import clean_paths
from polish import endpoint, segments


def aligned(start, end):
    delta_x, delta_y = abs(end[0] - start[0]), abs(end[1] - start[1])
    return min(delta_x, delta_y, abs(delta_x - delta_y)) < 0.000002


def paths(start, end):
    if aligned(start, end):
        yield [start, end]
        return
    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    diagonal = min(abs(delta_x), abs(delta_y))
    offset_x, offset_y = math.copysign(diagonal, delta_x), math.copysign(diagonal, delta_y)
    for corner in [(start[0] + offset_x, start[1] + offset_y),
                   (end[0] - offset_x, end[1] - offset_y)]:
        yield [start, tuple(round(value, 6) for value in corner), end]


class Octilinear(clean_paths.Routes):
    def visibility(self, start, end, obstacles):
        expanded = obstacles.buffer(0.18, quad_segs=2).simplify(0.12, preserve_topology=True)
        polygons = list(expanded.geoms) if expanded.geom_type == "MultiPolygon" else [expanded]
        points = [start, end]
        for anchor in [start, end]:
            for distance in [1, 1.5, 2, 3, 4, 6, 10]:
                for direction_x, direction_y in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                    points.append((anchor[0] + distance * direction_x, anchor[1] + distance * direction_y))
        for polygon in polygons:
            for ring in [polygon.exterior, *polygon.interiors]:
                points.extend(tuple(round(value, 3) for value in coordinate) for coordinate in ring.coords[:-1])
        points = list(dict.fromkeys(points))
        points = points[:2] + [coordinate for coordinate in points[2:]
                              if self.bounds.covers(Point(coordinate)) and not obstacles.covers(Point(coordinate))]
        vertices = np.asarray(points)
        distances = {0: 0.0}
        parents = {}
        queue = [(math.dist(start, end), 0)]
        visited = set()
        shapely.prepare(obstacles)
        while queue:
            _, index = heapq.heappop(queue)
            if index in visited:
                continue
            if index == 1:
                route = []
                while index != 0:
                    previous, coordinates = parents[index]
                    route = coordinates[1:] + route
                    index = previous
                route = [start] + route
                shortened = [route[0]]
                first = 0
                while first < len(route) - 1:
                    choice = [route[first], route[first + 1]]
                    following = first + 1
                    for last in range(len(route) - 1, first + 1, -1):
                        candidate = next((candidate for candidate in paths(route[first], route[last])
                                          if all(math.dist(left, right) >= 0.99999 for left, right in zip(candidate, candidate[1:]))
                                          and self.clear(candidate, obstacles)), None)
                        if candidate:
                            choice, following = candidate, last
                            break
                    shortened.extend(choice[1:])
                    first = following
                return [tuple(float(value) for value in coordinate) for coordinate in shortened]
            visited.add(index)
            origin = vertices[index]
            delta = vertices - origin
            diagonal = np.minimum(np.abs(delta[:, 0]), np.abs(delta[:, 1]))
            offset = np.sign(delta) * diagonal[:, None]
            for corners in [origin + offset, vertices - offset]:
                first_length = np.linalg.norm(corners - origin, axis=1)
                second_length = np.linalg.norm(vertices - corners, axis=1)
                valid = ((first_length < 0.000001) | (first_length >= 0.99999)) & ((second_length < 0.000001) | (second_length >= 0.99999))
                coordinates = np.stack([np.broadcast_to(origin, vertices.shape), corners, vertices], axis=1)
                lines = shapely.linestrings(coordinates)
                valid &= ~shapely.intersects(obstacles, lines)
                valid &= shapely.covers(self.bounds, lines)
                for following in np.flatnonzero(valid):
                    following = int(following)
                    if following in visited:
                        continue
                    bends = int(first_length[following] > 0.000001) + int(second_length[following] > 0.000001)
                    distance = distances[index] + first_length[following] + second_length[following] + 6 * bends
                    if distance < distances.get(following, math.inf):
                        coordinates = [tuple(origin), tuple(corners[following]), tuple(vertices[following])]
                        coordinates = [coordinate for offset, coordinate in enumerate(coordinates)
                                       if offset == 0 or math.dist(coordinate, coordinates[offset - 1]) > 0.000001]
                        parents[following] = index, coordinates
                        distances[following] = distance
                        heapq.heappush(queue, (distance + math.dist(points[following], end), following))
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    clean_paths.paths = paths
    routes = Octilinear(args.path)
    report = routes.redraw()
    bad = [item for item in segments(routes.data) if not aligned(endpoint(item, "start"), endpoint(item, "end"))]
    assert not bad, f"{len(bad)} non-45-degree segments remain"
    assert not report["violations"] and not report["unconnected_items"]
    print("PASS: every segment is horizontal, vertical or 45 degrees; DRC clean", flush=True)