"""Show the shared kit, sliding cassettes and two equal-inventory routes."""

import bpy
import json
import math
from collections import Counter
from mathutils import Vector


ns = bpy.app.driver_namespace["batman_modular"]
source = ns["scene"]
bpy.context.window.scene = source
if bpy.data.scenes.get("BATMAN - modular cable kit"):
    raise RuntimeError("Modular inspection scenes already exist.")
bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=3.1, depth=2.4)
nut = bpy.context.object
nut.name = "M3 captive nut template"
ns["hole"](nut, (0, 0, 0), 3.05, 4)
for collection in list(nut.users_collection):
    collection.objects.unlink(nut)
ns["group"]("Construction").objects.link(nut)
nut.data.materials.append(ns["materials"]["metal"])
bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=3.1, radius2=1.5, depth=1.5)
head = bpy.context.object
head.name = "M3 countersunk head template"
for collection in list(head.users_collection):
    collection.objects.unlink(head)
ns["group"]("Construction").objects.link(head)
head.data.materials.append(ns["materials"]["metal"])
for route in ns["routes"]:
    mount = route["mount"]
    owner = ns["group"](mount["level"] + " " + mount["lane"] + " cable cassette")
    for tile in route["tiles"]:
        for offset_x in (-12.5, 12.5):
            for offset_y in (-12.5, 12.5):
                for height in (3.5, 12.5):
                    obj = bpy.data.objects.new("M3 captive nut reference", nut.data)
                    owner.objects.link(obj)
                    obj.location = (tile["xy"][0] + offset_x, tile["xy"][1] + offset_y, route["base_z"] + height)
                    obj["fastener_reference"] = True
                obj = bpy.data.objects.new("M3 flush mounting head reference", head.data)
                owner.objects.link(obj)
                obj.location = (tile["xy"][0] + offset_x, tile["xy"][1] + offset_y, mount["plate_bottom"] + 0.75)
                obj["fastener_reference"] = True


def new_scene(name):
    target = bpy.data.scenes.new(name)
    target.unit_settings.system = "METRIC"
    target.unit_settings.scale_length = source.unit_settings.scale_length
    target.unit_settings.length_unit = "MILLIMETERS"
    target.world = source.world
    target.render.engine = "CYCLES"
    target.cycles.samples = 24
    target.render.resolution_x = 1800
    target.render.resolution_y = 1500
    target.render.resolution_percentage = 100
    target.view_settings.view_transform = "AgX"
    for obj in source.objects:
        if obj.type == "LIGHT":
            target.collection.objects.link(obj.copy())
    target["inspection_only"] = True
    return target


def camera_fit(target, direction):
    bpy.context.window.scene = target
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(corner) for obj in target.objects
               if obj.type == "MESH" and not obj.hide_render for corner in obj.bound_box]
    low = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    high = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    focal = (low + high) / 2
    data = bpy.data.cameras.new(target.name)
    data.type = "ORTHO"
    data.clip_end = 4000
    camera = bpy.data.objects.new(target.name + " camera", data)
    target.collection.objects.link(camera)
    camera.location = focal + Vector(direction)
    camera.rotation_euler = (focal - camera.location).to_track_quat("-Z", "Y").to_euler()
    target.camera = camera
    bpy.context.view_layer.update()
    projected = [camera.matrix_world.inverted() @ corner for corner in corners]
    data.ortho_scale = max(max(abs(point.x) for point in projected) * 2,
                          max(abs(point.y) for point in projected) * 2 * 1800 / 1500) * 1.12


def show_template(target, code, point, rotation=0, material=None):
    obj = bpy.data.objects.new(code, ns["templates"][code].data)
    target.collection.objects.link(obj)
    obj.location = point
    obj.rotation_euler.z = math.radians(rotation)
    obj["kit_code"] = code
    if obj.material_slots:
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material or ns["materials"]["signal"]
    return obj


def label(target, text, point, size=4):
    data = bpy.data.curves.new(text, "FONT")
    data.body = text
    data.align_x = "CENTER"
    data.size = size
    obj = bpy.data.objects.new(text, data)
    target.collection.objects.link(obj)
    obj.location = point
    data.materials.append(bpy.data.materials["Module reference"])


for mode in ("cutaway", "levels"):
    target = new_scene("BATMAN - modular cable " + mode)
    mapping = {}
    for collection in source.collection.children:
        category = collection.name.removeprefix("Modular | ")
        if category in ("Construction", "Shell front", "Shell sides", "Lid"):
            continue
        if mode == "levels" and not category.startswith(("C1 ", "C2 ")):
            continue
        for original in collection.objects:
            if original.hide_render or original.type in ("LIGHT", "CAMERA") or original.get("duct_lid") or original.get("fastener_reference"):
                continue
            obj = original.copy()
            target.collection.objects.link(obj)
            mapping[original] = obj
            if mode == "levels":
                obj.location += Vector((-125, 0, 0) if category.startswith("C1 ") else (125, 0, -86))
                if category == "C1 left cable cassette" or category == "C2 right cable cassette":
                    obj.location.y -= 45
                if original.get("modular_part") == "R92":
                    obj.location += Vector((0, -65, -12))
    for original, obj in mapping.items():
        if original.parent and original.parent in mapping:
            obj.parent = mapping[original.parent]
    camera_fit(target, (340, -500, 390) if mode == "cutaway" else (160, -350, 600))
    target["covers_and_fasteners_hidden_for_view"] = True
    if mode == "levels":
        target["exploded_only_not_mounting_coordinates"] = True

kit = new_scene("BATMAN - modular cable kit")
show_template(kit, "C92", (-90, 0, 0), material=ns["materials"]["carrier"])
label(kit, "C92 / 92 x 202", (-90, -110, 0))
for code, point in (("S32", (-10, 75, 0)), ("L32", (35, 75, 0)), ("T32", (80, 75, 0)),
                    ("X32", (-10, 15, 0)), ("D32", (35, 15, 0)), ("A4", (80, 15, 0)),
                    ("K32", (-10, -45, 0)), ("J32", (35, -45, 0))):
    show_template(kit, code, point)
    label(kit, code, (point[0], point[1] - 23, 0))
camera_fit(kit, (100, -180, 650))

alternatives = new_scene("BATMAN - modular cable alternatives")
inventories = []
paths = (
    [(-15, -48), (17, -48), (17, -16), (17, 16), (17, 48), (-15, 48)],
    [(-15, -80), (-15, -48), (17, -48), (17, -16), (17, 16), (17, 48)],
)
for offset, path in zip((-62, 62), paths):
    show_template(alternatives, "C92", (offset, 0, 0), material=ns["materials"]["carrier"])
    inventory = Counter()
    for index, point in enumerate(path):
        neighbors = path[max(0, index - 1):index] + path[index + 1:index + 2]
        ports = {next(port for port, vector in ns["port_vectors"].items()
                      if vector == ((other[0] - point[0]) // 32, (other[1] - point[1]) // 32)) for other in neighbors}
        options = [(code, rotation) for code, standard in ns["tile_ports"].items() for rotation in (0, 90, 180, 270)
                   if {"ENWS"[("ENWS".index(port) + rotation // 90) % 4] for port in standard} == ports]
        code, rotation = options[0]
        show_template(alternatives, code, (offset + point[0], point[1], 6.2), rotation)
        show_template(alternatives, "A4", (offset + point[0], point[1], 2), material=ns["materials"]["carrier"])
        inventory[code] += 1
        if index:
            previous = path[index - 1]
            show_template(alternatives, "J32", (offset + (previous[0] + point[0]) / 2,
                                                (previous[1] + point[1]) / 2, 6.2),
                          90 if previous[0] != point[0] else 0)
    inventories.append(dict(inventory))
    label(alternatives, "2 S32 + 2 L32 + 2 D32", (offset, -112, 0), 3.6)
assert inventories[0] == inventories[1], inventories
camera_fit(alternatives, (0, -150, 650))
report = ns["checked_report"]
report["equal_inventory_examples"] = inventories
report["views"] = [target.name for target in bpy.data.scenes if target.name.startswith("BATMAN - modular cable ")]
(ns["ROOT"] / "modular-cable-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
bpy.context.window.scene = bpy.data.scenes["BATMAN - modular cable levels"]
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.region_3d.view_perspective = "CAMERA"
        area.spaces.active.shading.color_type = "MATERIAL"
        area.spaces.active.overlay.show_extras = False
bpy.ops.wm.save_as_mainfile(filepath=str(ns["ROOT"] / "cad/assembly-cable-modular.blend"))
result = {"file": bpy.data.filepath, "views": report["views"], "equal_inventory_examples": inventories}