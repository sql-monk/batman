"""Repair the in-session prototype after correcting inward cutter normals."""

import ast
import bpy
import bmesh
from pathlib import Path


ROOT=Path(__file__).resolve().parent
ns=bpy.app.driver_namespace["batman_cables"]
branch=bpy.app.driver_namespace["batman_cable_branches"]
syntax=ast.parse((ROOT/"cable_channels.py").read_text())
exec(compile(ast.Module(body=[node for node in syntax.body if isinstance(node,ast.FunctionDef) and node.name=="mesh_object"],type_ignores=[]),"fixed_mesh_factory","exec"),ns)
for obj in ns["printables"]:
    mesh=bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(mesh,faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    if obj.name.startswith("UI FRONT RISER"):
        for vertex in obj.data.vertices:
            vertex.co.x+=0.4
for item in ns["ducts"]:
    if item["id"]=="UI FRONT RISER":
        for point in item["path_mm"]:
            point[0]+=0.4
targets={item["part"] for item in branch["modifications"] if "plate" in item["part"]}
targets.update(item["target"] for item in branch["mounts"])
for name in targets:
    target=ns["scene"].objects[name]
    original=next(obj for obj in ns["SOURCE"].objects if obj.get("source_object")==target.get("source_object"))
    target.data=original.data.copy()
for item in list(branch["modifications"]):
    if "plate" not in item["part"]:
        continue
    cutter=ns["box"]("Repaired cutter",item["opening_mm"],item["center_mm"],"Construction",ns["power"])
    branch["subtract"](ns["scene"].objects[item["part"]],cutter)
for item in branch["mounts"]:
    target=ns["scene"].objects[item["target"]]
    branch["bore"](target,(*item["xy_mm"],target.location.z),1.7,10)
for item in list(branch["modifications"]):
    if "strap ear" not in item["part"]:
        continue
    obj=ns["scene"].objects[item["part"]]
    points=[vertex.co for vertex in obj.data.vertices]
    minimum=[min(point[axis] for point in points) for axis in range(3)]
    maximum=[max(point[axis] for point in points) for axis in range(3)]
    position=[(lower+upper)/2 for lower,upper in zip(minimum,maximum)]
    replacement=ns["box"]("Rebuilt ear",[upper-lower for lower,upper in zip(minimum,maximum)],position,obj["cable_group"],obj.data.materials[0])
    obj.data=replacement.data
    bpy.data.objects.remove(replacement,do_unlink=True)
    cutter=ns["box"]("Strap cutter",item["opening_mm"],position,"Construction",ns["power"])
    branch["subtract"](obj,cutter)
result=ns["validate"]()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-cable-routing.blend"))