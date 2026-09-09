"""Verify physical contact paths from every duct to a bolted enclosure anchor."""

import bpy
import json
from collections import deque
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ns=bpy.app.driver_namespace["batman_supported"]
scene=ns["scene"]
bpy.context.window.scene=scene
bpy.context.view_layer.update()
tolerance=0.16
objects=[obj for obj in scene.objects if obj.type=="MESH" and not obj.hide_render and not obj.get("duct_lid")
         and (obj.get("cable_printable") or obj.get("support_revision_part"))]
geometry={}


def geo(obj):
    if obj.name not in geometry:
        points=[obj.matrix_world@vertex.co for vertex in obj.data.vertices]
        tree=BVHTree.FromPolygons(points,[tuple(face.vertices) for face in obj.data.polygons])
        geometry[obj.name]=(points,tree,ns["bounds"](obj))
    return geometry[obj.name]


def distance(first,second):
    first_points,first_tree,(first_low,first_high)=geo(first)
    second_points,second_tree,(second_low,second_high)=geo(second)
    box_gap=max(max(second_low[axis]-first_high[axis],first_low[axis]-second_high[axis],0) for axis in range(3))
    if box_gap>tolerance:
        return box_gap
    if first_tree.overlap(second_tree):
        return 0
    closest=1000000
    for points,tree in ((first_points,second_tree),(second_points,first_tree)):
        for point in points:
            nearest=tree.find_nearest(point)
            if nearest and nearest[0] is not None:
                closest=min(closest,nearest[3])
                if closest<=tolerance:
                    return closest
    return closest


graph={obj.name:set() for obj in objects}
for index,first in enumerate(objects):
    for second in objects[index+1:]:
        if distance(first,second)<=tolerance:
            graph[first.name].add(second.name)
            graph[second.name].add(first.name)
root_contacts=[]
roots=set()
for item in ns["anchors"]:
    support=scene.objects[item["support"]]
    target=scene.objects[item["target"]]
    gap=distance(support,target)
    if gap<=tolerance:
        roots.add(support.name)
    root_contacts.append({"support":support.name,"anchor":target.name,"contact_gap_mm":round(gap,4),"pass":gap<=tolerance})
for original,obj in ns["mapping"].items():
    if original.get("mount_target"):
        target_original=ns["SOURCE"].objects.get(original["mount_target"])
        if not target_original:
            continue
        target=ns["mapping"][target_original]
        gap=distance(obj,target)
        if gap<=tolerance:
            roots.add(obj.name)
        root_contacts.append({"support":obj.name,"anchor":target.name,"contact_gap_mm":round(gap,4),"pass":gap<=tolerance})
paths={name:[name] for name in roots}
queue=deque(roots)
while queue:
    node=queue.popleft()
    for neighbor in graph[node]:
        if neighbor not in paths:
            paths[neighbor]=[neighbor]+paths[node]
            queue.append(neighbor)
duct_results=[{"duct":obj["duct_id"],"supported":obj.name in paths,"contact_path":paths.get(obj.name,[])}
              for obj in objects if obj.get("duct_id")]
unanchored=[item["duct"] for item in duct_results if not item["supported"]]
result={"duct_count":len(duct_results),"unsupported_ducts":unanchored,"ducts":duct_results,"anchor_contacts":root_contacts,
        "contact_tolerance_mm":tolerance,"failed_anchor_contacts":[item for item in root_contacts if not item["pass"]]}
joint_results=[]
for item in ns["connections"]:
    if item["second"].startswith("@"):
        continue
    first=ns["duct"](item["first"])
    second=ns["duct"](item["second"])
    if item["bridge"]:
        connector=scene.objects[item["bridge"]]
        if item.get("via_joint"):
            via=scene.objects[item["via_joint"]]
            gaps=[distance(first,connector),distance(connector,via),distance(via,second)]
        else:
            gaps=[distance(first,connector),distance(connector,second)]
    else:
        gaps=[distance(first,second)]
    joint_results.append({"first":item["first"],"second":item["second"],"gaps_mm":[round(gap,4) for gap in gaps],"pass":all(gap<=tolerance for gap in gaps)})
result["joints"]=joint_results
result["failed_joints"]=[item for item in joint_results if not item["pass"]]
ns["support_graph_report"]=result
ns["contact_check_namespace"]=globals()
(ns["ROOT"]/"cable-contact-check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
assert not unanchored,result
assert not result["failed_anchor_contacts"],result["failed_anchor_contacts"]
assert not result["failed_joints"],result["failed_joints"]