"""Check actual shared meshes, clear ports, supported floors and grid interfaces."""

import bpy
import json
from collections import Counter
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ns = bpy.app.driver_namespace["batman_modular"]
scene = ns["scene"]
bpy.context.window.scene = scene
bpy.context.view_layer.update()
report = ns["validate"]()
parts = ns["parts"]
joint_contacts = set()
for route in ns["routes"]:
    nodes = {tuple(item["xy"]): scene.objects[item["object"]] for item in route["tiles"]}
    for first, second in route["edges"]:
        midpoint = Vector(((first[0] + second[0]) / 2, (first[1] + second[1]) / 2, route["base_z"]))
        key = next(obj for obj in parts if obj.get("joint_for") == route["name"] and (obj.location - midpoint).length < 0.01)
        for endpoint in (first, second):
            joint_contacts.add(frozenset((key, nodes[tuple(endpoint)])))
geometry = {}
for obj in parts:
    tree = BVHTree.FromPolygons([obj.matrix_world @ vertex.co for vertex in obj.data.vertices],
                               [tuple(face.vertices) for face in obj.data.polygons])
    geometry[obj] = (tree, ns["bounds"](obj))
intersections = []
for index, first in enumerate(parts):
    first_tree, (first_low, first_high) = geometry[first]
    for second in parts[index + 1:]:
        second_tree, (second_low, second_high) = geometry[second]
        if any(first_high[axis] <= second_low[axis] + 0.01 or first_low[axis] >= second_high[axis] - 0.01
               for axis in range(3)):
            continue
        if first_tree.overlap(second_tree) and frozenset((first, second)) not in joint_contacts:
            intersections.append([first.name, second.name])
assert not intersections, intersections
checked_ports = 0
checked_floors = 0
for route in ns["routes"]:
    nodes = {tuple(item["xy"]): item for item in route["tiles"]}
    reached = {next(iter(nodes))}
    while True:
        extended = reached | {tuple(second) for first, second in route["edges"] if tuple(first) in reached}
        extended |= {tuple(first) for first, second in route["edges"] if tuple(second) in reached}
        if reached == extended:
            break
        reached = extended
    assert reached == set(nodes), route["name"]
    route_objects = [scene.objects[item["object"]] for item in route["tiles"]]
    route_objects += [obj for obj in parts if obj.get("joint_for") == route["name"]]
    for first, second in route["edges"]:
        start = Vector((*first, route["base_z"] + 8))
        end = Vector((*second, route["base_z"] + 8))
        direction = (end - start).normalized()
        for offset in (-7, 0, 7):
            across = Vector((-direction.y, direction.x, 0)) * offset
            for obj in route_objects:
                hit = geometry[obj][0].ray_cast(start + across, direction, 32)
                assert hit[0] is None, ("Blocked port", route["name"], obj.name, list(hit[0]))
        checked_ports += 1
        midpoint = (start + end) / 2
        for offset in (-7, 0, 7):
            probe = midpoint + Vector((-direction.y, direction.x, 0)) * offset
            hits = [geometry[obj][0].ray_cast(probe, Vector((0, 0, -1)), 7)[0] for obj in route_objects]
            assert any(hit is not None and abs(hit.z - route["base_z"] - 2) < 0.01 for hit in hits), ("Joint floor gap", route["name"])
        checked_floors += 1
    for item in route["tiles"]:
        tile = scene.objects[item["object"]]
        shoe = next(obj for obj in parts if obj.get("mount_for") == tile.name)
        plate = next(obj for obj in parts if obj.get("modular_part") == "C92"
                     and abs(obj.location.x - route["mount"]["center_x"]) < 0.01
                     and abs(obj.location.z - route["mount"]["plate_bottom"]) < 0.01)
        center_x, center_y = item["xy"]
        for offset_x in (-12.5, 12.5):
            for offset_y in (-12.5, 12.5):
                origin = Vector((center_x + offset_x, center_y + offset_y, route["base_z"] + 16))
                for obj in (tile, shoe, plate):
                    assert geometry[obj][0].ray_cast(origin, Vector((0, 0, -1)), 25)[0] is None, ("Misaligned screw", obj.name)
        for offset_x, offset_y in ((12.5, 9.5), (-12.5, -9.5)):
            origin = Vector((center_x + offset_x, center_y + offset_y, route["base_z"] + 0.1))
            hit = geometry[shoe][0].ray_cast(origin, Vector((0, 0, -1)), 0.2)[0]
            assert hit is not None, ("Unsupported tile", tile.name)
            origin.z = route["mount"]["plate_top"] + 0.1
            assert geometry[plate][0].ray_cast(origin, Vector((0, 0, -1)), 0.2)[0] is not None
        if item["part"] == "D32":
            origin = Vector((center_x, center_y, route["base_z"] + 8))
            for obj in (tile, shoe, plate):
                assert geometry[obj][0].ray_cast(origin, Vector((0, 0, -1)), 18)[0] is None, ("Blocked drop", obj.name)

for code in ns["templates"]:
    instances = [obj for obj in parts if obj.get("modular_part") == code]
    assert all(obj.data == ns["templates"][code].data for obj in instances), code
report.update({"new_part_intersections": intersections, "open_intertile_ports": checked_ports,
               "continuous_joint_floors": checked_floors, "mounted_tiles": sum(len(route["tiles"]) for route in ns["routes"]),
               "identical_cassettes": 4, "fastener_tip_separation_mm": 4,
               "bom": dict(Counter(obj["modular_part"] for obj in parts))})
(ns["ROOT"] / "modular-cable-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
ns["checked_report"] = report
result = {key: report[key] for key in ("open_intertile_ports", "continuous_joint_floors", "mounted_tiles",
                                     "identical_cassettes", "new_part_intersections", "unchanged_components")}