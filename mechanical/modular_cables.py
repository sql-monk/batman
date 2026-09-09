"""Interchangeable sliding cable cassettes and a shared 32 mm routing kit."""

import bpy
import bmesh
import json
import math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parent
SOURCE = bpy.data.scenes["BATMAN - detailed assembly"]
NAME = "BATMAN - modular cable assembly"
if bpy.data.scenes.get(NAME):
    raise RuntimeError("Modular revision already exists; preserve it.")
if bpy.context.object and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
scene = bpy.data.scenes.new(NAME)
bpy.context.window.scene = scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = SOURCE.unit_settings.scale_length
scene.unit_settings.length_unit = "MILLIMETERS"
scene.world = SOURCE.world
scene.render.engine = "CYCLES"
scene.cycles.samples = 24
scene.render.resolution_x = 1600
scene.render.resolution_y = 1400
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "AgX"
groups = {}
mapping = {}
parts = []
templates = {}
routes = []
mounts = []
pitch = 32
rows = (-80, -48, -16, 16, 48, 80)
materials = {
    "carrier": bpy.data.materials["PETG carriers"],
    "frame": bpy.data.materials["PETG deep teal"],
    "signal": bpy.data.materials["Cable | Signal duct blue"],
    "power": bpy.data.materials["Cable | Power duct amber"],
    "analog": bpy.data.materials["Cable | Analog duct green"],
    "metal": bpy.data.materials["Detail | Tin and aluminium"],
}


def group(name):
    if name not in groups:
        groups[name] = bpy.data.collections.new("Modular | " + name)
        scene.collection.children.link(groups[name])
    return groups[name]


for source_group in SOURCE.collection.children:
    category = source_group.name.removeprefix("Detail | ").removeprefix("Detailed | ")
    if "Construction" in category:
        continue
    for original in source_group.objects:
        obj = original.copy()
        if original.data:
            obj.data = original.data.copy()
        group(category).objects.link(obj)
        obj["modular_source"] = original.name
        mapping[original] = obj
        if obj.type == "CAMERA":
            scene.camera = obj
for original, obj in mapping.items():
    if original.parent:
        obj.parent = mapping[original.parent]


def mesh(name, vertices, faces, owner, material):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    editable = bmesh.new()
    editable.from_mesh(data)
    bmesh.ops.recalc_face_normals(editable, faces=list(editable.faces))
    editable.to_mesh(data)
    editable.free()
    obj = bpy.data.objects.new(name, data)
    group(owner).objects.link(obj)
    if material:
        data.materials.append(material)
    return obj


def box(name, size, center, owner="Construction", material=None):
    vertices = [(center[0] + axis_x * size[0] / 2,
                 center[1] + axis_y * size[1] / 2,
                 center[2] + axis_z * size[2] / 2)
                for axis_x, axis_y, axis_z in
                ((-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
                 (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1))]
    return mesh(name, vertices,
                [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
                 (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)], owner, material)


def cut(target, cutter):
    linked = [obj for obj in bpy.data.objects if obj != target and obj.data == target.data]
    if linked:
        target.data = target.data.copy()
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    modifier = target.modifiers.new("Modular interface", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.context.view_layer.update()
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    for obj in linked:
        obj.data = target.data
    bpy.data.objects.remove(cutter, do_unlink=True)


def hole(target, center, diameter, depth, vertices=32, axis="Z"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=diameter / 2,
                                      depth=depth, location=center)
    cutter = bpy.context.object
    if axis == "Y":
        cutter.rotation_euler.x = math.pi / 2
    cut(target, cutter)


def register(obj, code):
    obj["modular_part"] = code
    parts.append(obj)
    return obj


def instance(code, center, owner, material, rotation=0):
    original = templates[code]
    obj = bpy.data.objects.new(code, original.data)
    group(owner).objects.link(obj)
    obj.location = center
    obj.rotation_euler.z = math.radians(rotation)
    if obj.material_slots:
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
    register(obj, code)
    return obj


def bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return ([min(point[axis] for point in points) for axis in range(3)],
            [max(point[axis] for point in points) for axis in range(3)])


carrier = box("C92 grid cassette", (92, 202, 2), (0, 0, 1), material=materials["carrier"])
for center_x in (-15, 17):
    for center_y in rows:
        cut(carrier, box("Air and cable window", (22, 22, 5), (center_x, center_y, 1)))
        for offset_x in (-12.5, 12.5):
            for offset_y in (-12.5, 12.5):
                point = (center_x + offset_x, center_y + offset_y, 1)
                hole(carrier, point, 3.4, 6)
                bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=3.2, radius2=1.7,
                                               depth=1.5, location=(point[0], point[1], 0.75))
                cut(carrier, bpy.context.object)
templates["C92"] = carrier

port_vectors = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
tile_ports = {"S32": ("N", "S"), "L32": ("N", "E"),
              "T32": ("N", "E", "S"), "X32": ("N", "E", "S", "W"),
              "D32": ("N",)}
for code, ports in tile_ports.items():
    tile = box(code, (31.6, 31.6, 16), (0, 0, 8), material=materials["signal"])
    cut(tile, box("Central cavity", (18, 18, 17), (0, 0, 10.5)))
    for port in ports:
        direction_x, direction_y = port_vectors[port]
        size = (18, 18, 17)
        cut(tile, box("Open port", size, (direction_x * 12, direction_y * 12, 10.5)))
        join_size = (17.8, 8.4, 2) if direction_y else (8.4, 17.8, 2)
        cut(tile, box("Flush joint key seat", join_size,
                      (direction_x * 16, direction_y * 16, 2)))
    if code == "D32":
        hole(tile, (0, 0, 1), 16, 5)
    for offset_x in (-12.5, 12.5):
        for offset_y in (-12.5, 12.5):
            hole(tile, (offset_x, offset_y, 8), 3.4, 20)
            for nut_z in (3.5, 12.5):
                hole(tile, (offset_x, offset_y, nut_z), 6.4, 2.6, 6)
                cut(tile, box("Nut loading slot", (7, 5.7, 2.6),
                              (math.copysign(15, offset_x), offset_y, nut_z)))
    templates[code] = tile

cover = box("K32 shared lid", (31.6, 31.6, 1.6), (0, 0, 0.8), material=materials["signal"])
for offset_x in (-12.5, 12.5):
    for offset_y in (-12.5, 12.5):
        hole(cover, (offset_x, offset_y, 0.8), 3.4, 5)
templates["K32"] = cover
templates["J32"] = box("J32 flush joint key", (17.6, 7.6, 1), (0, 0, 1.5), material=materials["signal"])
spacer = box("A4 mounting shoe", (31.6, 31.6, 4.2), (0, 0, 2.1), material=materials["carrier"])
cut(spacer, box("Shoe cable window", (22, 22, 7), (0, 0, 2)))
for offset_x in (-12.5, 12.5):
    for offset_y in (-12.5, 12.5):
        hole(spacer, (offset_x, offset_y, 2), 3.4, 8)
templates["A4"] = spacer


def hardware(center, owner, length, head=True):
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=1.5, depth=length, location=center)
    obj = bpy.context.object
    obj.name = "M3 cassette fastener reference"
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    group(owner).objects.link(obj)
    obj.data.materials.append(materials["metal"])
    obj["fastener_reference"] = True
    if head:
        bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=2.8, depth=1.6,
                                          location=(center[0], center[1], center[2] + length / 2 + 0.8))
        head_obj = bpy.context.object
        head_obj.name = "M3 lid screw head reference"
        for collection in list(head_obj.users_collection):
            collection.objects.unlink(head_obj)
        group(owner).objects.link(head_obj)
        head_obj.data.materials.append(materials["metal"])
        head_obj["fastener_reference"] = True


def source_named(name):
    return next(obj for obj in mapping.values() if obj.get("source_object") == name)


frames = []
for level_name, height in (("C1", 87), ("C2", 173)):
    owner = level_name + " cable frame"
    for source_name in ("L1 logic frame grooved frame", "L1 logic frame removable retainer"):
        original = source_named(source_name)
        obj = original.copy()
        obj.data = original.data.copy()
        group(owner).objects.link(obj)
        obj.location.z += height - 40
        obj.name = level_name + " " + source_name.removeprefix("L1 logic frame ")
        if "grooved" in source_name:
            cut(obj, box("Retainer assembly clearance", (220, 3.4, 20), (0, -104.5, height + 1.2)))
        register(obj, "F92" if "grooved" in source_name else "R92")
        frames.append(obj)
    for obj in mapping.values():
        if obj.get("source_object", "").startswith("corner post"):
            low, high = bounds(obj)
            hole(obj, ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, height + 1.2), 2.8, 12, axis="Y")
    for lane, center_x, rotation in (("left", -49, 0), ("right", 49, 180)):
        owner = level_name + " " + lane + " cable cassette"
        instance("C92", (center_x, 0, height + 0.2), owner, materials["carrier"], rotation)
        mounts.append({"level": level_name, "lane": lane, "height": height,
                       "center_x": center_x, "rotation": rotation,
                       "plate_bottom": height + 0.2, "plate_top": height + 2.2})


def build_route(name, mount, cells, edges, material):
    owner = mount["level"] + " " + mount["lane"] + " cable cassette"
    base_z = mount["height"] + 6.4
    adjacency = {tuple(cell): set() for cell in cells}
    for first, second in edges:
        first, second = tuple(first), tuple(second)
        delta = (second[0] - first[0], second[1] - first[1])
        assert abs(delta[0]) + abs(delta[1]) == pitch, (first, second)
        port = next(key for key, vector in port_vectors.items()
                    if vector == (delta[0] // pitch, delta[1] // pitch))
        opposite = {"N": "S", "E": "W", "S": "N", "W": "E"}[port]
        adjacency[first].add(port)
        adjacency[second].add(opposite)
        midpoint = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2, base_z)
        obj = instance("J32", midpoint, owner, material, 90 if delta[0] else 0)
        obj["joint_for"] = name
    route_tiles = []
    for point, ports in adjacency.items():
        chosen = None
        for code, standard_ports in tile_ports.items():
            for rotation in (0, 90, 180, 270):
                cardinal = "ENWS"
                rotated = {cardinal[(cardinal.index(port) + rotation // 90) % 4] for port in standard_ports}
                if rotated == ports:
                    chosen = code, rotation
                    break
            if chosen:
                break
        assert chosen, (name, point, ports)
        code, rotation = chosen
        tile = instance(code, (*point, base_z), owner, material, rotation)
        tile["route"] = name
        tile["ports"] = ",".join(sorted(ports))
        shoe = instance("A4", (*point, mount["plate_top"]), owner, materials["carrier"])
        shoe["mount_for"] = tile.name
        lid = instance("K32", (*point, base_z + 16.2), owner, material)
        lid["duct_lid"] = True
        for offset_x in (-12.5, 12.5):
            for offset_y in (-12.5, 12.5):
                hardware((point[0] + offset_x, point[1] + offset_y, base_z + 13.8), owner, 8)
                hardware((point[0] + offset_x, point[1] + offset_y, base_z + 0.55), owner, 10.5, False)
        route_tiles.append({"object": tile.name, "part": code, "rotation": rotation,
                            "xy": list(point), "ports": sorted(ports)})
    routes.append({"name": name, "mount": mount, "base_z": base_z,
                   "tiles": route_tiles, "edges": edges})


for mount in mounts:
    side = -1 if mount["lane"] == "left" else 1
    inner, outer = side * 32, side * 64
    if mount["level"] == "C1" and side == -1:
        cells = [(inner, value) for value in (-80, -48, -16, 16, 48, 80)] + [(outer, -48), (outer, 48)]
        edges = [[cells[index], cells[index + 1]] for index in range(5)] + [[(inner, -48), (outer, -48)], [(inner, 48), (outer, 48)]]
        build_route("Logic and control", mount, cells, edges, materials["signal"])
    elif mount["level"] == "C1":
        for center_x, suffix in ((inner, "48"), (outer, "49")):
            cells = [(center_x, value) for value in (-48, -16, 16)]
            build_route("Spare digital " + suffix, mount, cells, [[cells[0], cells[1]], [cells[1], cells[2]]], materials["signal"])
    elif side == -1:
        cells = [(inner, value) for value in (-80, -48, -16, 16, 48, 80)] + [(outer, -80), (outer, 80)]
        edges = [[cells[index], cells[index + 1]] for index in range(5)] + [[(inner, -80), (outer, -80)], [(inner, 80), (outer, 80)]]
        build_route("DPS relay supply", mount, cells, edges, materials["power"])
    else:
        cells = [(inner, value) for value in (-80, -48, -16, 16, 48, 80)] + [(outer, value) for value in (-48, 16, 80)]
        edges = [[cells[index], cells[index + 1]] for index in range(5)] + [[(inner, value), (outer, value)] for value in (-48, 16, 80)]
        build_route("Power branches", mount, cells, edges, materials["power"])

group("Construction").hide_render = True
group("Construction").hide_viewport = True
bpy.context.view_layer.update()
bpy.app.driver_namespace["batman_modular"] = globals()


def validate():
    bpy.context.view_layer.update()
    invalid = []
    checked = set()
    for obj in [*templates.values(), *frames]:
        if obj.data in checked:
            continue
        checked.add(obj.data)
        editable = bmesh.new()
        editable.from_mesh(obj.data)
        if not all(edge.is_manifold for edge in editable.edges):
            invalid.append(obj.name)
        editable.free()
    assert not invalid, invalid
    components = [obj for obj in mapping.values() if obj.get("component_id")]
    for original, copied in mapping.items():
        if copied.get("component_id"):
            assert all(abs(original.matrix_world[row][column] - copied.matrix_world[row][column]) < 0.0001
                       for row in range(4) for column in range(4)), copied.name
    collisions = []
    obstacles = []
    for obj in mapping.values():
        if obj.type != "MESH" or obj.hide_render:
            continue
        tree = BVHTree.FromPolygons([obj.matrix_world @ vertex.co for vertex in obj.data.vertices],
                                   [tuple(face.vertices) for face in obj.data.polygons])
        obstacles.append((obj, tree, bounds(obj)))
    for obj in parts:
        low, high = bounds(obj)
        assert low[0] >= -107.01 and high[0] <= 107.01 and low[1] >= -107.01 and high[1] <= 107.01
        assert low[2] > 3 and high[2] < 213
        tree = BVHTree.FromPolygons([obj.matrix_world @ vertex.co for vertex in obj.data.vertices],
                                   [tuple(face.vertices) for face in obj.data.polygons])
        for other, other_tree, (other_low, other_high) in obstacles:
            if any(high[axis] <= other_low[axis] + 0.01 or low[axis] >= other_high[axis] - 0.01 for axis in range(3)):
                continue
            if tree.overlap(other_tree):
                collisions.append([obj.name, other.name])
    assert not collisions, collisions
    for route in routes:
        mount = route["mount"]
        for tile in route["tiles"]:
            center_x, center_y = tile["xy"]
            assert center_y in rows
            local_x = (center_x - mount["center_x"]) * (1 if mount["rotation"] == 0 else -1)
            assert local_x in (-15, 17), tile
        assert len(route["edges"]) == len(route["tiles"]) - 1
    report = {"scene": scene.name, "pitch_mm": pitch, "cassette_mm": [92, 202, 2],
              "groove_mm": 2.4, "vertical_slide_clearance_mm": 0.4,
              "levels_mm": [87.2, 173.2], "mounts": mounts, "routes": routes,
              "shared_templates": list(templates), "unchanged_components": len(components),
              "non_manifold": invalid, "unexpected_component_collisions": collisions,
              "status": "Modular mechanical layout; harness lengths and print fit require verification"}
    (ROOT / "modular-cable-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


result = validate()