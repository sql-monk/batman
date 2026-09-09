"""Run in Blender. Millimetre concept model; unmeasured interfaces are provisional."""

import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
CAD = ROOT / "cad"
CAD.mkdir(exist_ok=True)
SCENE_NAME = "BATMAN - assembly"
existing_scene = bpy.data.scenes.get(SCENE_NAME)
if existing_scene and len(existing_scene.objects):
    raise RuntimeError("Generated scene already exists; use a fresh Blender session to rebuild.")
scene = existing_scene or bpy.data.scenes.new(SCENE_NAME)
bpy.context.window.scene = scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 0.001
scene.unit_settings.length_unit = "MILLIMETERS"
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.render.resolution_x = 1500
scene.render.resolution_y = 1500
scene.render.resolution_percentage = 100
scene.world = bpy.data.worlds.new("BATMAN studio")
scene.world.use_nodes = True
background = next(node for node in scene.world.node_tree.nodes if node.type == "BACKGROUND")
background.inputs[0].default_value = (0.65, 0.69, 0.72, 1)
background.inputs[1].default_value = 0.6
scene.view_settings.view_transform = "AgX"
groups = {}
parts = []
envelopes = []
slides = []


def collection(name):
    if name not in groups:
        group = bpy.data.collections.new(name)
        scene.collection.children.link(group)
        groups[name] = group
    return groups[name]


def material(name, color, metallic=0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1)
    value.use_nodes = True
    shader = next(node for node in value.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    next(socket for socket in shader.inputs if socket.identifier == "Base Color").default_value = (*color, 1)
    next(socket for socket in shader.inputs if socket.identifier == "Roughness").default_value = 0.36
    next(socket for socket in shader.inputs if socket.identifier == "Metallic").default_value = metallic
    return value


shell = material("PETG warm white", (0.72, 0.76, 0.73))
frame = material("PETG deep teal", (0.035, 0.23, 0.24))
tray = material("PETG carriers", (0.18, 0.43, 0.42))
orange = material("PETG retainers", (0.96, 0.30, 0.065))
green = material("PCB reference", (0.055, 0.31, 0.13))
black = material("Module reference", (0.035, 0.045, 0.055))
silver = material("Aluminium reference", (0.55, 0.60, 0.63), 0.75)
blue = material("Capacitor reference - provisional", (0.04, 0.20, 0.46))
white = material("Reference legends", (0.93, 0.96, 0.94))


def register(obj, name, group, mat, printable=False):
    obj.name = name
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    collection(group).objects.link(obj)
    if mat:
        obj.data.materials.append(mat)
    obj["group"] = group
    obj["printable_concept"] = printable
    if printable:
        parts.append(obj)
    return obj


def box(name, size, pos, group, mat, printable=False):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = register(bpy.context.object, name, group, mat, printable)
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def cylinder(name, radius, depth, pos, group, mat, printable=False):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=depth, location=pos)
    return register(bpy.context.object, name, group, mat, printable)


def subtract(obj, cutter):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Machined opening", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def hole(obj, pos, diameter, depth=20, axis="Z"):
    cutter = cylinder("temporary cutter", diameter / 2, depth, pos, "Construction", None)
    if axis == "Y":
        cutter.rotation_euler.x = math.pi / 2
    if axis == "X":
        cutter.rotation_euler.y = math.pi / 2
    subtract(obj, cutter)


def slot(obj, size, pos):
    subtract(obj, box("temporary cutter", size, pos, "Construction", None))


def label(text, pos, size, group, mat=white, vertical=False):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body = text
    curve.size = size
    curve.align_x = "CENTER"
    curve.extrude = 0
    obj = bpy.data.objects.new("Legend " + text, curve)
    collection(group).objects.link(obj)
    obj.location = pos
    if vertical:
        obj.rotation_euler.x = math.pi / 2
    obj.data.materials.append(mat)
    return obj


def module(name, size, pos, group, height_source="provisional"):
    obj = box(name + " envelope", size, pos, group, green)
    obj["reference_only"] = True
    obj["dimension_source"] = height_source
    obj.hide_render = True
    obj.hide_set(True)
    envelopes.append(obj)
    bottom = pos[2] - size[2] / 2
    box(name + " board illustration", (size[0], size[1], min(1.6, size[2])), (pos[0], pos[1], bottom + min(1.6, size[2]) / 2), group, green)
    if size[2] > 2:
        body_height = max(1, size[2] - 2)
        box(name + " component illustration", (size[0] * 0.67, size[1] * 0.65, body_height), (pos[0], pos[1], bottom + 1.6 + body_height / 2), group, black)
    label(name, (pos[0], pos[1], pos[2] + size[2] / 2 + 0.12), 3.2, group)
    return obj


def standoff(name, xy, top, group):
    obj = cylinder(name, 4, 5, (*xy, top + 2.5), group, tray, True)
    hole(obj, (*xy, top + 2.5), 3.4)
    return obj


def carrier(name, lane, center_y, depth, level):
    group = name
    center_x = -49 if lane == "left" else 49
    obj = box(name + " plate", (92, depth, 2), (center_x, center_y, level + 1.2), group, tray, True)
    obj["level_z_mm"] = level
    obj["insertion_axis"] = "+Y; remove front cassette first"
    pull = box(name + " pull lip", (24, 3, 7), (center_x, center_y - depth / 2 + 1.5, level + 5.7), group, orange, True)
    slides.append({"name": name, "lane": lane, "level": level, "min_y": center_y - depth / 2, "max_y": center_y + depth / 2, "center_x": center_x, "width": 92, "thickness": 2})
    return obj, center_x, level + 2.2


def mounting_pattern(plate, name, center, size, top, group, pitch=None):
    pitch = pitch or (size[0] - 7, size[1] - 7)
    for dx in (-pitch[0] / 2, pitch[0] / 2):
        for dy in (-pitch[1] / 2, pitch[1] / 2):
            xy = (center[0] + dx, center[1] + dy)
            hole(plate, (*xy, top - 1), 3.4)
            standoff(name + " M3 spacer", xy, top, group)


base = box("base", (220, 220, 3), (0, 0, 1.5), "L0 base", shell, True)
for center_x in (-100, 100):
    for center_y in (-100, 100):
        hole(base, (center_x, center_y, 1.5), 3.4)
        post = box("corner post", (9, 9, 210), (center_x, center_y, 108), "Structure", frame, True)
        hole(post, (center_x, center_y, 108), 4, 214)
        for center_z in (30, 41.2, 100, 124.2, 190):
            hole(post, (center_x, center_y, center_z), 2.8, 12, "Y")
        for center_z in (30, 100, 190):
            hole(post, (center_x, center_y, center_z), 2.8, 12, "X")

level_frame_mesh = None
for level, name in ((40, "L1 logic frame"), (123, "L2 power frame")):
    members = []
    for center_x, width in ((-97.5, 3), (0, 3.4), (97.5, 3)):
        members.append(box(name + " rail web", (width, 210, 8.4), (center_x, 0, level + 1.2), name, frame, True))
        lip_width = 8 if center_x else 12
        lip_x = math.copysign(95, center_x) if center_x else 0
        for center_z in (level - 1.5, level + 3.9):
            upper = center_z > level
            current_width = (6 if center_x else 8) if upper else lip_width
            current_x = math.copysign(96, center_x) if upper and center_x else lip_x
            members.append(box(name + " rail lip", (current_width, 210, 3), (current_x, 0, center_z), name, frame, True))
    rear = box(name + " rear stop", (211, 4, 8.4), (0, 105, level + 1.2), name, frame, True)
    front = box(name + " removable retainer", (211, 4, 8.4), (0, -105, level + 1.2), name, orange, True)
    for member in members:
        bpy.ops.object.select_all(action="DESELECT")
        rear.select_set(True)
        bpy.context.view_layer.objects.active = rear
        modifier = rear.modifiers.new("Frame union", "BOOLEAN")
        modifier.operation = "UNION"
        modifier.solver = "EXACT"
        modifier.object = member
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        parts.remove(member)
        bpy.data.objects.remove(member, do_unlink=True)
    rear.name = name + " grooved frame"
    for member in (rear, front):
        for corner_x in (-100, 100):
            for corner_y in (-100, 100):
                slot(member, (9.4, 9.4, 20), (corner_x, corner_y, level))
    for member in (rear, front):
        for center_x in (-100, 100):
            hole(member, (center_x, member.location.y, level + 1.2), 3.4, axis="Y")
    label(name.upper(), (0, -107.1, level - 0.6), 3.2, name, vertical=True)
    if level_frame_mesh is None:
        level_frame_mesh = rear.data
    else:
        rear.data = level_frame_mesh.copy()

for lane, board, center_y, depth in (("left", "A", -47, 102), ("right", "B", -51, 94), ("left", "C", 64, 62), ("right", "D", 72, 62)):
    spec = json.loads((ROOT.parent / "hardware" / "modular-layout.json").read_text())[board]
    size = spec["size"]
    name = "L1 carrier " + board
    plate, center_x, top = carrier(name, lane, center_y, depth, 40)
    mounting_pattern(plate, board, (center_x, center_y), size, top, name)
    module("PCB " + board, (*size, 1.6), (center_x, center_y, top + 5.8), name, "current PCB XY; assumed 1.6 mm substrate")
    if board == "A":
        module("ESP32", (28, 55, 13), (center_x - 11, center_y - 2, top + 13.1), name, "measured module; socket height provisional")
        box("ESP RF keepout - reference", (32, 18, 15), (center_x - 11, center_y + 34.5, top + 14.1), "Clearance references", orange)
    for offset in (-size[0] / 3, size[0] / 3):
        box(board + " header reference", (10, 5, 10), (center_x + offset, center_y - size[1] / 2 + 7, top + 11.6), name, black)

plate, center_x, top = carrier("L1 carrier ADS pair", "right", 20, 32, 40)
for center_x, name in ((29, "ADS 0x48"), (77, "ADS 0x49")):
    module(name, (28, 17, 8), (center_x, 20, top + 9), "L1 carrier ADS pair")
    for delta in (-7, 7):
        box(name + " edge support", (28, 3, 5), (center_x, 20 + delta, top + 2.5), "L1 carrier ADS pair", tray, True)
    for delta in (-10.5, 10.5):
        box(name + " adjustable edge saddle", (32, 3, 5), (center_x, 20 + delta, top + 2.5), "L1 carrier ADS pair", orange, True)

plate, center_x, top = carrier("L2 carrier DPS", "left", -46, 104, 123)
mounting_pattern(plate, "DPS", (center_x, -46), (67, 91), top, "L2 carrier DPS", (64, 86))
module("DPS5015", (67, 91, 40), (center_x, -46, top + 25), "L2 carrier DPS", "measured 91 x 67 x 40; rotated 90 degrees")
for center_x in range(-78, -35, 6):
    box("DPS heatsink illustration", (2, 48, 15), (center_x, -48, top + 37.5), "L2 carrier DPS", silver)

plate, center_x, top = carrier("L2 carrier relay supply", "left", 56.5, 93, 123)
module("mREL2", (50, 40, 19), (-53, 36, top + 14.5), "L2 carrier relay supply", "measured envelope; hole pattern unknown")
module("LM2596", (44, 22, 15), (-53, 83, top + 12.5), "L2 carrier relay supply", "supplier dimensions; hole pattern unknown")
for center_y, width, length in ((36, 50, 40), (83, 44, 22)):
    for delta in (-length / 2 + 1.5, length / 2 - 1.5):
        box("module edge support", (width, 3, 5), (-53, center_y + delta, top + 2.5), "L2 carrier relay supply", tray, True)
    for delta in (-length / 2 - 2, length / 2 + 2):
        box("adjustable module edge saddle", (width + 4, 3, 5), (-53, center_y + delta, top + 2.5), "L2 carrier relay supply", orange, True)

for branch, center_y in enumerate((-65, -3, 59), 1):
    name = "L2 carrier branch " + str(branch)
    plate, center_x, top = carrier(name, "right", center_y, 58, 123)
    module("mACS" + str(branch), (17.8, 20.3, 8), (22, center_y - 5, top + 9), name)
    if branch < 3:
        module("mSW" + str(branch), (20.3, 25.4, 14), (51, center_y - 5, top + 12), name)
        box("manual switch", (6, 5, 3), (51, center_y - 5, top + 20.5), name, silver)
    else:
        module("LOAD node", (22, 20, 15), (51, center_y - 5, top + 12.5), name)
    module("mDIO" + str(branch), (17, 10, 5), (81, center_y - 5, top + 7.5), name, "measured XY; height estimated")
    for center_x, width in ((22, 17.8), (51, 22), (81, 17)):
        for delta in (-width / 2 + 1.5, width / 2 - 1.5):
            box("module edge support", (3, 8, 5), (center_x + delta, center_y - 5, top + 2.5), name, tray, True)
        for delta in (-width / 2 - 2.4, width / 2 + 2.4):
            box("provisional adjustable saddle", (3, 23, 5), (center_x + delta, center_y - 5, top + 2.5), name, orange, True)

cap_group = "L0 capacitors - PROVISIONAL"
cap_mount = box("C1 C2 adjustable cradle", (62, 32, 3), (53, 78, 4.5), cap_group, tray, True)
for center_x in (30, 76):
    slot(cap_mount, (3.4, 18, 10), (center_x, 78, 4.5))
for center_x in (39, 67):
    box("capacitor strap guide", (3, 26, 4), (center_x, 78, 8), cap_group, orange, True)
cap = cylinder("C1 placeholder D12 H22 - NOT MEASURED", 6, 22, (51, 78, 17), cap_group, blue)
cap["reference_only"] = True
envelopes.append(cap)
cylinder("C1 vent illustration", 5.6, 0.3, (51, 78, 28.15), cap_group, silver)
module("C2 TBD", (6, 4, 7), (62, 78, 9.5), cap_group)
label("C1/C2 - SIZE TBD", (53, 57, 3.1), 3.5, cap_group, frame)

for side in (-1, 1):
    wall = box("wall left" if side == -1 else "wall right", (3, 220, 210), (side * 108.5, 0, 108), "Shell sides", shell, True)
    for center_y in range(-80, 90, 17):
        slot(wall, (10, 10, 10), (side * 108.5, center_y, 14))
    if side == -1:
        hole(wall, (-108.5, -46, 166), 45, 12, "X")
        for delta_y in (-20, 20):
            for delta_z in (-20, 20):
                hole(wall, (-108.5, -46 + delta_y, 166 + delta_z), 4.5, 12, "X")
    for center_y in (-100, 100):
        for center_z in (30, 100, 190):
            hole(wall, (side * 108.5, center_y, center_z), 3.4, 12, "X")

back = box("panel back - interface blanks", (214, 3, 210), (0, 108.5, 108), "Shell back", shell, True)
front = box("panel front", (214, 3, 210), (0, -108.5, 108), "Shell front", shell, True)
slot(front, (26, 10, 18), (-43, -108.5, 193))
hole(front, (0, -108.5, 193), 12, 12, "Y")
slot(front, (38, 10, 24), (-64, -108.5, 67))
label("BATMAN", (27, -110.1, 174), 9, "Shell front", frame, True)
label("USB SERVICE / FIT TBD", (-64, -110.1, 48), 2.8, "Shell front", frame, True)
oled = box("OLED envelope", (28, 4, 28), (-43, -104, 193), "Front instruments", black)
button = cylinder("button reference", 6, 8, (0, -109, 193), "Front instruments", silver)
button.rotation_euler.x = math.pi / 2
for panel in (front, back):
    for center_x in (-100, 100):
        for center_z in (30, 100, 190):
            hole(panel, (center_x, panel.location.y, center_z), 3.4, 12, "Y")

for center_x, name in zip((-75, -25, 25, 75), ("BAT1", "BAT2", "PSU", "LOAD")):
    module(name + " terminal TBD", (32, 18, 18), (center_x, 94, 20), "Rear interfaces - PROVISIONAL")
    module(name + " ATO TBD", (30, 15, 20), (center_x, 94, 72), "Rear interfaces - PROVISIONAL")
    label(name + " +/-", (center_x, 110.1, 20), 3.2, "Rear interfaces - PROVISIONAL")

lid = box("lid ventilated", (220, 220, 3), (0, 0, 214.5), "Lid", shell, True)
for center_x in range(-88, 89, 16):
    for center_y in (-64, 0, 64):
        slot(lid, (8, 52, 10), (center_x, center_y, 214.5))
for center_x in (-100, 100):
    for center_y in (-100, 100):
        hole(lid, (center_x, center_y, 214.5), 3.4)

for center_x in (-93, 93):
    box("reserved harness riser", (8, 12, 106), (center_x, 13, 61), "Clearance references", orange)
collection("Clearance references").hide_render = True
collection("Clearance references").hide_viewport = True

camera_data = bpy.data.cameras.new("BATMAN camera")
camera = bpy.data.objects.new("BATMAN camera", camera_data)
collection("Studio").objects.link(camera)
scene.camera = camera
camera_data.type = "ORTHO"
camera_data.ortho_scale = 370
camera_data.clip_end = 5000
camera.location = (360, -460, 360)
camera.rotation_euler = (Vector((0, 0, 105)) - camera.location).to_track_quat("-Z", "Y").to_euler()
for name, pos, power, size in (("Key", (100, -250, 500), 3500000, 300), ("Fill", (-350, -100, 250), 2400000, 250), ("Rim", (100, 300, 400), 3000000, 250)):
    light_data = bpy.data.lights.new(name, "AREA")
    light_data.energy = power
    light_data.shape = "DISK"
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    collection("Studio").objects.link(light)
    light.location = pos
    light.rotation_euler = (Vector((0, 0, 90)) - light.location).to_track_quat("-Z", "Y").to_euler()

scene["design_status"] = "CONCEPT - unmeasured components and fastening joints require resolution before printing"
scene["outer_dimensions_mm"] = [220, 220, 216]
scene["level_carrier_bottoms_mm"] = [3, 40.2, 123.2]
bpy.context.view_layer.update()
manifest = {
    "outer_mm": [220, 220, 216],
    "groove_height_mm": 2.4,
    "carrier_thickness_mm": 2,
    "slides": slides,
    "parts": [{"name": obj.name, "size_mm": list(obj.dimensions), "group": obj["group"]} for obj in parts],
    "envelopes": [{"name": obj.name, "center_mm": list(obj.location), "size_mm": list(obj.dimensions)} for obj in envelopes],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.clip_end = 5000
        area.spaces.active.region_3d.view_distance = 480
        area.spaces.active.region_3d.view_location = (0, 0, 100)
        area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
        area.spaces.active.shading.color_type = "MATERIAL"
bpy.ops.wm.save_as_mainfile(filepath=str(CAD / "assembly.blend"))
result = {"scene": scene.name, "objects": len(scene.objects), "parts": len(parts), "manifest": str(ROOT / "manifest.json"), "blend": str(CAD / "assembly.blend")}