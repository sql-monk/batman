"""Inspection scenes and focused geometric checks for the detailed revision."""

import bpy
import json
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
source = bpy.data.scenes["BATMAN - detailed assembly"]
settings = (
    ("BATMAN - detailed open", "open", (350,-490,380), (0,10,105), 380),
    ("BATMAN - detailed levels", "levels", (360,-540,540), (0,5,190), 610),
    ("BATMAN - logic detail", "logic", (90,-180,410), (0,0,47), 290),
    ("BATMAN - power detail", "power", (90,-180,490), (0,0,133), 285),
    ("BATMAN - XT60 rear", "rear", (290,480,250), (0,10,100), 370),
)
for name, mode, camera_pos, target, scale in settings:
    if bpy.data.scenes.get(name):
        raise RuntimeError("Inspection scene already exists: " + name)
    scene = bpy.data.scenes.new(name)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = source.unit_settings.scale_length
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.world = source.world
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.render.resolution_x = 1800
    scene.render.resolution_y = 1500
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    mapping = {}
    for collection in source.collection.children:
        category = collection.name.removeprefix("Detail | ")
        if category == "Construction":
            continue
        if mode in ("open","levels") and category.startswith(("Shell","Lid")):
            continue
        if mode == "levels" and category in ("Structure","Front instruments"):
            continue
        if mode in ("logic","power") and not (category.startswith("L1" if mode == "logic" else "L2") or category == "Studio"):
            continue
        copied = bpy.data.collections.new(name + " | " + category)
        scene.collection.children.link(copied)
        for original in collection.objects:
            if original.hide_render:
                continue
            obj = original.copy()
            copied.objects.link(obj)
            mapping[original] = obj
            if obj.type == "CAMERA":
                obj.data = obj.data.copy()
                scene.camera = obj
            if not original.parent and mode == "levels":
                if category.startswith("L1"):
                    obj.location.z += 75
                if category.startswith("L2"):
                    obj.location.z += 165
            if obj.type == "LIGHT" and mode == "levels":
                obj.location.z += 130
    for original,obj in mapping.items():
        if original.parent:
            obj.parent = mapping[original.parent]
    scene.camera.location = camera_pos
    scene.camera.rotation_euler = (Vector(target)-scene.camera.location).to_track_quat("-Z","Y").to_euler()
    scene.camera.data.ortho_scale = scale
    scene["inspection_only"] = True

bpy.context.window.scene = source
bpy.context.view_layer.update()
extents = []
violations = []
for node in source.objects:
    name = node.get("component_id", "")
    if name not in ("mMCU","mDPS","mREL2","mDC5","ADS 0x48","ADS 0x49","mACS1","mACS2","mACS3","mSW1","mSW2","mDIO1","mDIO2","mDIO3"):
        continue
    points = [obj.matrix_world @ Vector(corner) for obj in node.children if obj.type == "MESH" for corner in obj.bound_box]
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    record = {"id":name,"min_mm":minimum,"max_mm":maximum,"lid_clearance_mm":213-maximum[2]}
    extents.append(record)
    if any(minimum[axis] < -107 or maximum[axis] > 107 for axis in (0,1)) or minimum[2]<3 or maximum[2]>198:
        violations.append(record)
assert not violations, violations
report = json.loads((ROOT/"detail-check.json").read_text())
report["internal_modules_checked"] = extents
report["shell_bounds_and_15mm_lid_clearance_pass"] = True
report["inspection_scenes"] = [item[0] for item in settings]
(ROOT/"detail-check.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
bpy.context.window.scene = bpy.data.scenes["BATMAN - detailed levels"]
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        space = area.spaces.active
        space.region_3d.view_location = (0,5,190)
        space.region_3d.view_distance = 780
        space.region_3d.view_perspective = "ORTHO"
        space.region_3d.view_rotation = bpy.context.scene.camera.rotation_euler.to_quaternion()
        space.overlay.show_floor = False
        space.overlay.show_axis_x = False
        space.overlay.show_axis_y = False
        space.overlay.show_extras = False
        space.shading.color_type = "MATERIAL"
        space.clip_end = 5000
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-detailed.blend"))
result = {"scenes":report["inspection_scenes"],"checked_modules":len(extents),"violations":violations}