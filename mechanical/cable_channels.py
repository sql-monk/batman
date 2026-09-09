"""Add segregated, removable wiring ducts without changing the prior assembly."""

import bpy
import bmesh
import json
import math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parent
SOURCE = bpy.data.scenes["BATMAN - detailed assembly"]
NAME = "BATMAN - cable assembly"
if bpy.data.scenes.get(NAME):
    raise RuntimeError("Cable revision exists; preserve it and open the preceding revision to rebuild.")
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
scene.render.resolution_x = 1800
scene.render.resolution_y = 1500
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "AgX"
collections = {}
copied_objects = {}
ducts = []
printables = []
routes = []


def collection(name):
    if name not in collections:
        value = bpy.data.collections.new("Cable | " + name)
        scene.collection.children.link(value)
        collections[name] = value
    return collections[name]


for original_collection in SOURCE.collection.children:
    category = original_collection.name.removeprefix("Detail | ")
    for original in original_collection.objects:
        obj = original.copy()
        if original.data:
            obj.data = original.data.copy()
        collection(category).objects.link(obj)
        copied_objects[original] = obj
        if obj.type == "CAMERA":
            scene.camera = obj
for original, obj in copied_objects.items():
    if original.parent:
        obj.parent = copied_objects[original.parent]


def material(name, color):
    value = bpy.data.materials.new("Cable | " + name)
    value.diffuse_color = (*color, 1)
    value.use_nodes = True
    shader = next(node for node in value.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = 0.5
    return value


power = material("Power duct amber", (0.82, 0.38, 0.035))
signal = material("Signal duct blue", (0.035, 0.25, 0.48))
analog = material("Analog duct green", (0.14, 0.43, 0.17))
white = material("Duct legends", (0.94, 0.96, 0.92))
black = material("Wire insulation", (0.022, 0.024, 0.027))
red = material("Positive wire", (0.62, 0.025, 0.018))


def mesh_object(name, vertices, faces, owner, mat, printable=False):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    editable = bmesh.new()
    editable.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(editable, faces=list(editable.faces))
    editable.to_mesh(mesh)
    editable.free()
    obj = bpy.data.objects.new(name, mesh)
    collection(owner).objects.link(obj)
    obj.data.materials.append(mat)
    obj["cable_group"] = owner
    if printable:
        obj["cable_printable"] = True
        printables.append(obj)
    return obj


def box(name, size, pos, owner, mat, printable=False):
    vertices = [(pos[0]+side_x*size[0]/2,pos[1]+side_y*size[1]/2,pos[2]+side_z*size[2]/2)
                for side_x,side_y,side_z in ((-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1))]
    return mesh_object(name,vertices,[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)],owner,mat,printable)


def label(body, pos, owner, rotation=0):
    curve = bpy.data.curves.new(body,"FONT")
    curve.body = body
    curve.size = 2.2
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new(body,curve)
    collection(owner).objects.link(obj)
    obj.location = pos
    obj.rotation_euler.z = rotation
    curve.materials.append(white)
    obj["cable_group"] = owner
    return obj


def swept(name, path, profile, owner, mat, printable=True):
    centers = [Vector(point) for point in path]
    vertices = []
    for index, point in enumerate(centers):
        tangent = centers[min(index+1,len(centers)-1)]-centers[max(index-1,0)]
        tangent.normalize()
        normal = Vector((-tangent.y,tangent.x,0))
        if normal.length < 0.1:
            normal = Vector((1,0,0))
        normal.normalize()
        up = tangent.cross(normal).normalized()
        for offset, height in profile:
            vertices.append(point+normal*offset+up*height)
    count = len(profile)
    faces = [tuple(reversed(range(count))),tuple(range((len(centers)-1)*count,len(centers)*count))]
    for index in range(len(centers)-1):
        for edge in range(count):
            faces.append((index*count+edge,index*count+(edge+1)%count,(index+1)*count+(edge+1)%count,(index+1)*count+edge))
    return mesh_object(name,vertices,faces,owner,mat,printable)


def duct(name, path, width, height, mat, owner, conductors, diameter, wall=1.6):
    outer = width/2+wall
    profile = [(-outer,0),(outer,0),(outer,height+wall),(width/2,height+wall),
               (width/2,wall),(-width/2,wall),(-width/2,height+wall),(-outer,height+wall)]
    obj = swept(name,path,profile,owner,mat)
    lid = swept(name+" removable lid",path,[(-outer,height+wall+0.3),(outer,height+wall+0.3),
                                            (outer,height+wall+1.7),(-outer,height+wall+1.7)],owner,mat)
    lid["duct_lid"] = True
    lid["retention"] = "Reusable straps through saddle slots; no unverified snap fits"
    area = conductors*math.pi*(diameter/2)**2
    fill = area/(width*height)
    assert fill <= 0.45, (name,fill)
    item = {"id":name,"path_mm":[list(point) for point in path],"inner_mm":[width,height],
            "conductors_design":conductors,"wire_outer_diameter_assumed_mm":diameter,
            "fill_percent":round(fill*100,1),"owner":owner,"length_mm":sum((Vector(end)-Vector(start)).length for start,end in zip(path,path[1:]))}
    obj["duct_id"] = name
    ducts.append(item)
    return obj


duct("P0 POWER",[(0,-90,148),(0,88,148)],18,14,power,"L2 power ducts",8,3.5)
duct("S2 CONTROL",[(21,-85,104),(21,65,104)],12,10,signal,"L2 signal ducts",22,1.3)
duct("S1 LOGIC",[(21,-85,61),(21,70,61)],12,10,signal,"L1 signal ducts",24,1.3)


def validate():
    bpy.context.view_layer.update()
    meshes = []
    for obj in printables:
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        manifold = all(edge.is_manifold for edge in mesh.edges)
        mesh.free()
        assert manifold,obj.name
        bounds = [obj.matrix_world@Vector(corner) for corner in obj.bound_box]
        minimum = [min(point[axis] for point in bounds) for axis in range(3)]
        maximum = [max(point[axis] for point in bounds) for axis in range(3)]
        assert all(minimum[axis]>=-107 and maximum[axis]<=107 for axis in (0,1)),obj.name
        assert minimum[2]>=3 and maximum[2]<=213,obj.name
        meshes.append({"name":obj.name,"closed_manifold":manifold,"min_mm":minimum,"max_mm":maximum})
    obstacles = []
    for obj in copied_objects.values():
        if obj.type != "MESH" or obj.hide_render:
            continue
        points = [obj.matrix_world@vertex.co for vertex in obj.data.vertices]
        tree = BVHTree.FromPolygons(points,[tuple(face.vertices) for face in obj.data.polygons])
        obstacles.append((obj.name,tree))
    collisions = []
    for obj in printables:
        points=[obj.matrix_world@vertex.co for vertex in obj.data.vertices]
        tree=BVHTree.FromPolygons(points,[tuple(face.vertices) for face in obj.data.polygons])
        for name,other in obstacles:
            if tree.overlap(other):
                collisions.append([obj.name,name])
    assert not collisions,collisions
    assert len(SOURCE.objects)==1345
    result={"scene":scene.name,"ducts":ducts,"parts":meshes,"surface_collisions_with_existing_geometry":collisions,
            "routes":routes,"source_objects_preserved":len(SOURCE.objects),
            "limitations":["Wire outside diameters are design allowances, confirm actual cable", "Surface collision check is not a full assembly validation", "No STL release or strength verification"]}
    (ROOT/"cable-check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


bpy.app.driver_namespace["batman_cables"] = globals()
result=validate()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-cable-routing.blend"))