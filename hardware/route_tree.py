import argparse
from collections import defaultdict
from pathlib import Path

import networkx as nx
from shapely.geometry import Point
from shapely.ops import unary_union
import sexpdata

from clean_paths import Routes
from polish import endpoint, field, segments
from reroute_clean import validate
from straighten import line, make_segment, net


def tree(path):
    routes = Routes(path)
    grouped = defaultdict(list)
    for item in segments(routes.data):
        grouped[(net(item), field(item, "width")[1])].append(item)
    for (name, width), items in grouped.items():
        union = unary_union([line(item) for item in items])
        lines = list(union.geoms) if union.geom_type == "MultiLineString" else [union]
        graph = nx.Graph()
        for geometry in lines:
            coordinates = [tuple(round(value, 6) for value in coordinate) for coordinate in geometry.coords]
            for start, end in zip(coordinates, coordinates[1:]):
                graph.add_edge(start, end, weight=Point(start).distance(Point(end)), virtual=False)
        anchors = set()
        for pad in routes.pads:
            if pad["net"] != name or pad["reference"].startswith("W"):
                continue
            nodes = [node for node in graph if pad["shape"].buffer(0.00001).covers(Point(node))]
            anchors.update(nodes)
            for node in nodes[1:]:
                graph.add_edge(nodes[0], node, weight=0, virtual=True)
        forest = nx.minimum_spanning_tree(graph)
        removed = graph.number_of_edges() - forest.number_of_edges()
        if not removed:
            continue
        while True:
            leaves = [node for node in forest if forest.degree(node) == 1 and node not in anchors]
            if not leaves:
                break
            forest.remove_nodes_from(leaves)
        changed = True
        while changed:
            changed = False
            for node in list(forest):
                if forest.degree(node) != 2 or node in anchors:
                    continue
                first, second = list(forest[node])
                if forest[node][first]["virtual"] or forest[node][second]["virtual"]:
                    continue
                delta_first = (node[0] - first[0], node[1] - first[1])
                delta_second = (second[0] - node[0], second[1] - node[1])
                if abs(delta_first[0] * delta_second[1] - delta_first[1] * delta_second[0]) < 0.00001:
                    forest.remove_node(node)
                    forest.add_edge(first, second, virtual=False, weight=Point(first).distance(Point(second)))
                    changed = True
        replacements = [make_segment(items[0], first, second) for first, second, attributes in forest.edges(data=True)
                        if not attributes["virtual"]]
        for item in items:
            routes.data.remove(item)
        routes.data.extend(replacements)
        print(f"{name}: removed {removed} loops; {len(items)} -> {len(replacements)} segments", flush=True)
    path.write_text(sexpdata.dumps(routes.data), encoding="utf-8")
    return validate(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    tree(parser.parse_args().path)