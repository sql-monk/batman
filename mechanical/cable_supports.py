"""Supported, connected revision of the cable-channel assembly."""

import ast
import bpy
import bmesh
import json
import math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT=Path(__file__).resolve().parent
SOURCE=bpy.data.scenes["BATMAN - cable assembly"]
NAME="BATMAN - supported cable assembly"
if bpy.data.scenes.get(NAME):
    raise RuntimeError("Supported revision already exists; preserve it.")
if bpy.context.object and bpy.context.object.mode!="OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
scene=bpy.data.scenes.new(NAME)
bpy.context.window.scene=scene
scene.unit_settings.system="METRIC"
scene.unit_settings.scale_length=SOURCE.unit_settings.scale_length
scene.unit_settings.length_unit="MILLIMETERS"
scene.world=SOURCE.world
scene.render.engine="CYCLES"
scene.cycles.samples=24
scene.render.resolution_x=1800
scene.render.resolution_y=1500
scene.render.resolution_percentage=100
scene.view_settings.view_transform="AgX"
groups={}
mapping={}
new_parts=[]
connections=[]
anchors=[]
duct_specs={item["id"]:item for item in json.loads((ROOT/"cable-check.json").read_text())["ducts"]}


def group(name):
    if name not in groups:
        value=bpy.data.collections.new("Supported | "+name)
        scene.collection.children.link(value)
        groups[name]=value
    return groups[name]


for source_group in SOURCE.collection.children:
    category=source_group.name.removeprefix("Cable | ")
    if category in ("Construction","Power bend references"):
        continue
    for original in source_group.objects:
        obj=original.copy()
        if original.data:
            obj.data=original.data.copy()
        group(category).objects.link(obj)
        obj["supported_source"]=original.name
        mapping[original]=obj
        if obj.type=="CAMERA":
            scene.camera=obj
for original,obj in mapping.items():
    if original.parent:
        obj.parent=mapping[original.parent]
power=bpy.data.materials["Cable | Power duct amber"]
signal=bpy.data.materials["Cable | Signal duct blue"]
analog=bpy.data.materials["Cable | Analog duct green"]
metal=bpy.data.materials["Detail | Tin and aluminium"]


def mesh_object(name,vertices,faces,owner,mat):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(vertices,[],faces)
    editable=bmesh.new()
    editable.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(editable,faces=list(editable.faces))
    editable.to_mesh(mesh)
    editable.free()
    obj=bpy.data.objects.new(name,mesh)
    group(owner).objects.link(obj)
    mesh.materials.append(mat)
    obj["cable_group"]=owner
    obj["support_revision_part"]=True
    new_parts.append(obj)
    return obj


def box(name,size,pos,owner,mat):
    vertices=[(pos[0]+axis_x*size[0]/2,pos[1]+axis_y*size[1]/2,pos[2]+axis_z*size[2]/2)
              for axis_x,axis_y,axis_z in ((-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1))]
    return mesh_object(name,vertices,[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)],owner,mat)


def boolean(target,cutter,operation="DIFFERENCE"):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active=target
    modifier=target.modifiers.new("Supported cable joint", "BOOLEAN")
    modifier.operation=operation
    modifier.solver="EXACT"
    modifier.object=cutter
    bpy.context.view_layer.update()
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    if cutter in new_parts:
        new_parts.remove(cutter)
    bpy.data.objects.remove(cutter,do_unlink=True)


def bore(target,pos,diameter,depth,axis="Z"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=diameter/2,depth=depth,location=pos)
    cutter=bpy.context.object
    if axis=="Y":
        cutter.rotation_euler.x=math.pi/2
    boolean(target,cutter)


def named_source(name):
    return next(obj for obj in scene.objects if obj.get("source_object")==name)


def duct(name):
    return next(obj for obj in scene.objects if obj.get("duct_id")==name)


def bounds(obj):
    points=[obj.matrix_world@Vector(corner) for corner in obj.bound_box]
    return (Vector(tuple(min(point[axis] for point in points) for axis in range(3))),
            Vector(tuple(max(point[axis] for point in points) for axis in range(3))))


def extend(name,axis,old,new):
    originals=[obj for obj in scene.objects if obj.get("supported_source","") in (name,name+" removable lid")]
    for obj in originals:
        for vertex in obj.data.vertices:
            if abs(vertex.co[axis]-old)<0.01:
                vertex.co[axis]=new
    for point in duct_specs[name]["path_mm"]:
        if abs(point[axis]-old)<0.01:
            point[axis]=new


def rectangle_sweep(name,path,profile,owner,mat):
    points=[Vector(point) for point in path]
    vertices=[]
    for index,point in enumerate(points):
        tangent=(points[min(index+1,len(points)-1)]-points[max(index-1,0)]).normalized()
        normal=Vector((-tangent.y,tangent.x,0))
        if normal.length<0.1:
            normal=Vector((1,0,0))
        normal.normalize()
        up=tangent.cross(normal).normalized()
        vertices.extend(point+normal*offset+up*height for offset,height in profile)
    count=len(profile)
    faces=[tuple(reversed(range(count))),tuple(range((len(points)-1)*count,len(points)*count))]
    for index in range(len(points)-1):
        for edge in range(count):
            faces.append((index*count+edge,index*count+(edge+1)%count,(index+1)*count+(edge+1)%count,(index+1)*count+edge))
    return mesh_object(name,vertices,faces,owner,mat)


def interior(name):
    spec=duct_specs[name]
    width,height=spec["inner_mm"]
    wall=1.2 if name.startswith("SV ") and name!="SV LOGIC LINK" or name=="UI FRONT RISER" else 1.6
    return rectangle_sweep("Cable void",spec["path_mm"],[(-width/2,wall),(width/2,wall),(width/2,height+wall+2),(-width/2,height+wall+2)],"Construction",signal)


def bridge(name,first,second,path,width,height,owner,mat):
    wall=1.6
    outer=width/2+wall
    profile=[(-outer,0),(outer,0),(outer,height+wall),(width/2,height+wall),
             (width/2,wall),(-width/2,wall),(-width/2,height+wall),(-outer,height+wall)]
    body=rectangle_sweep(name,path,profile,owner,mat)
    body["duct_joint"]=True
    void_profile=[(-width/2,wall),(width/2,wall),(width/2,height+wall+2),(-width/2,height+wall+2)]
    for endpoint in (first,second):
        boolean(body,interior(endpoint))
        boolean(duct(endpoint),rectangle_sweep("Joint cable void",path,void_profile,"Construction",mat))
    lid=rectangle_sweep(name+" removable cover",path,[(-outer,height+wall+0.3),(outer,height+wall+0.3),
                                                   (outer,height+wall+1.7),(-outer,height+wall+1.7)],owner,mat)
    lid["duct_lid"]=True
    for endpoint in (first,second):
        endpoint_lid=next(obj for obj in scene.objects if obj.get("supported_source")==endpoint+" removable lid")
        cutter=lid.copy()
        cutter.data=lid.data.copy()
        group("Construction").objects.link(cutter)
        boolean(endpoint_lid,cutter)
    connections.append({"first":first,"second":second,"bridge":body.name,"gap_mm":0,"joint":"removable covered transition"})
    return body


def post(name,point,bottom,top,target,owner,mat,size=(7,7)):
    obj=box(name,(size[0],size[1],top-bottom),(*point,(bottom+top)/2),owner,mat)
    bore(obj,(*point,(bottom+top)/2),3.4,top-bottom+2)
    target_low,target_high=bounds(target)
    bore(target,(*point,(target_low.z+target_high.z)/2),3.4,12)
    anchors.append({"support":obj.name,"target":target.name,"xy_mm":list(point),"bottom_mm":bottom,"top_mm":top,"fastener":"M3 through bolt"})
    obj["mount_target"]=target.name
    return obj


extend("S1 LOGIC",1,-85,-99)
for name,point in (("S1 A",(10,10,61)),("S1 C",(10,36,61)),("S1 D",(32,43,61)),("S1 B",(32,-88,61))):
    center=(21,point[1],61)
    bridge("Joint "+name,name,"S1 LOGIC",[point,center],duct_specs[name]["inner_mm"][0],8,"L1 connected joints",signal)
left_frame=named_source("L1 logic frame grooved frame")
beam=box("L1 A bolted crossmember",(101,7,3),(-47.5,10,46.9),"L1 supported ducts",signal)
for center_x in (-96,0):
    bore(beam,(center_x,10,46.9),3.4,8)
    bore(left_frame,(center_x,10,44),3.4,12)
anchors.append({"support":beam.name,"target":left_frame.name,"fastener":"2 x M3 through bolts","xy_mm":[[-96,10],[0,10]]})
for center_x in (-65,-10):
    support=post("A duct post",(center_x,10),48.4,61,beam,"L1 supported ducts",signal)
for center_x in (-58,-10):
    post("C duct post",(center_x,40),42.2,61,named_source("L1 carrier C plate"),"L1 supported ducts",signal)
for center_x in (40,77):
    post("D duct post",(center_x,48),42.2,61,named_source("L1 carrier D plate"),"L1 supported ducts",signal)
for center_x in (42,79):
    post("B duct post",(center_x,-90),42.2,61,named_source("L1 carrier B plate"),"L1 supported ducts",signal,(7,5))


def validation():
    bpy.context.view_layer.update()
    obstacles=[]
    for original,obj in mapping.items():
        if obj.type!="MESH" or obj.hide_render or obj.get("cable_printable"):
            continue
        tree=BVHTree.FromPolygons([obj.matrix_world@vertex.co for vertex in obj.data.vertices],[tuple(face.vertices) for face in obj.data.polygons])
        obstacles.append((obj,tree,bounds(obj)))
    collisions=[]
    invalid=[]
    for obj in new_parts:
        if obj.name.startswith("Cable void"):
            continue
        editable=bmesh.new()
        editable.from_mesh(obj.data)
        if not all(edge.is_manifold for edge in editable.edges):
            invalid.append(obj.name)
        editable.free()
        low,high=bounds(obj)
        assert low.x>=-107.01 and high.x<=107.01 and low.y>=-107.01 and high.y<=107.01 and low.z>=2.99 and high.z<=213.01,(obj.name,list(low),list(high))
        tree=BVHTree.FromPolygons([obj.matrix_world@vertex.co for vertex in obj.data.vertices],[tuple(face.vertices) for face in obj.data.polygons])
        targets={entry["target"] for entry in anchors if entry["support"]==obj.name}
        for other,other_tree,(other_low,other_high) in obstacles:
            if other.name in targets:
                continue
            if any(high[axis]<=other_low[axis]+0.01 or low[axis]>=other_high[axis]-0.01 for axis in range(3)):
                continue
            if tree.overlap(other_tree):
                collisions.append([obj.name,other.name])
    assert not invalid,invalid
    assert not collisions,collisions
    result={"scene":scene.name,"new_parts":len(new_parts),"connections":connections,"anchors":anchors,"non_manifold":invalid,"unexpected_collisions":collisions}
    (ROOT/"cable-support-check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


bpy.app.driver_namespace["batman_supported"]=globals()
result=validation()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-cable-supported.blend"))