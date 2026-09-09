"""Finalize inspection framing and verify saved detailed scene contents."""

import bpy
import json
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
source = bpy.data.scenes["BATMAN - detailed assembly"]
black = bpy.data.materials["Detail | Component black"]
for obj in source.objects:
    if obj.type == "FONT" and obj.get("detail_group") == "Rear XT60 interfaces":
        obj.data.materials.clear()
        obj.data.materials.append(black)
framing = {}
for scene in bpy.data.scenes:
    if scene.name not in ("BATMAN - detailed levels","BATMAN - XT60 rear","BATMAN - logic detail","BATMAN - power detail","BATMAN - detailed open"):
        continue
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    points = [scene.camera.matrix_world.inverted() @ (obj.matrix_world @ Vector(corner))
              for obj in scene.objects if obj.type == "MESH" and not obj.hide_render for corner in obj.bound_box]
    horizontal = max(abs(point.x) for point in points)
    vertical = max(abs(point.y) for point in points)
    scale = max(horizontal*2,vertical*2*scene.render.resolution_x/scene.render.resolution_y)*1.08
    scene.camera.data.ortho_scale = max(scene.camera.data.ortho_scale,scale)
    limits = (scene.camera.data.ortho_scale/2,scene.camera.data.ortho_scale/2*scene.render.resolution_y/scene.render.resolution_x)
    assert all(abs(point[axis]) < limits[axis] for point in points for axis in (0,1))
    framing[scene.name] = {"scale":scene.camera.data.ortho_scale,"all_meshes_visible":True}
report=json.loads((ROOT/"detail-check.json").read_text())
report["framing"]=framing
expected={"mMCU","mDPS","mREL2","mDC5","mOLED","ADS 0x48","ADS 0x49","mSW1","mSW2","mACS1","mACS2","mACS3","mDIO1","mDIO2","mDIO3",
          "PCB A","PCB B","PCB C","PCB D","F1","F2","Fchg","Fout","T1","T2","Button","C1 LOAD buffer","C2 LOAD buffer",
          "XT60 BAT1","XT60 BAT2","XT60 PSU IN","XT60 LOAD OUT","B1 distribution","B2 distribution","LOAD distribution"}
actual={obj.get("component_id") for obj in source.objects if obj.get("component_id")}
assert expected <= actual, expected-actual
report["required_assembly_items"] = len(expected)
report["missing_assembly_items"] = sorted(expected-actual)
assert len(bpy.data.scenes["BATMAN - assembly"].objects)==255
(ROOT/"detail-check.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
bpy.context.window.scene=bpy.data.scenes["BATMAN - detailed levels"]
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-detailed.blend"))
result={"required_items":len(expected),"missing":[],"framing":framing,"saved":bpy.data.filepath}