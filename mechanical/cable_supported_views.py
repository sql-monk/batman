"""Show supported ducts with mounting walls retained in the cutaway."""

import bpy
import json
import math
from mathutils import Vector


ns=bpy.app.driver_namespace["batman_supported"]
scene=ns["scene"]
bpy.context.window.scene=scene
if bpy.data.scenes.get("BATMAN - supported cable cutaway"):
    raise RuntimeError("Supported inspection scenes already exist.")


def fastener(name,point,depth,radius,vertices=24,axis="Z"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=point)
    obj=bpy.context.object
    obj.name=name
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    ns["group"]("Duct fasteners").objects.link(obj)
    obj.data.materials.append(ns["metal"])
    if axis=="Y":
        obj.rotation_euler.x=math.pi/2
    obj["fastener_reference"]=True
    return obj


for item in ns["anchors"]:
    target=scene.objects[item["target"]]
    low,high=ns["bounds"](target)
    if item.get("axis")=="Y":
        center_x,unused_y,center_z=item["center_mm"]
        side=1 if low.y>0 else -1
        outside=high.y if side>0 else low.y
        fastener("M3 panel screw head",(center_x,outside+side,center_z),2,2.8,axis="Y")
        fastener("M3 panel screw shaft",(center_x,outside-side*4,center_z),9,1.5,axis="Y")
        fastener("M3 panel nut",(center_x,outside-side*7,center_z),2.4,3.2,6,"Y")
    else:
        points=item["xy_mm"]
        if isinstance(points[0],(float,int)):
            points=[points]
        for point in points:
            fastener("M3 underside screw head",(*point,low.z-1),2,2.8)
            fastener("M3 mounting screw shaft",(*point,(low.z+high.z)/2+2),high.z-low.z+6,1.5)

ns["validation"]()
specifications=(
    ("BATMAN - supported cable cutaway","cutaway",(350,-480,370),(0,10,109)),
    ("BATMAN - supported cable logic","logic",(100,-210,470),(0,0,57)),
    ("BATMAN - supported cable power","power",(110,-240,520),(0,0,143)),
    ("BATMAN - supported cable rear anchors","rear",(-330,-400,290),(-10,55,105)),
)
for name,mode,camera_position,focal in specifications:
    target=bpy.data.scenes.new(name)
    target.unit_settings.system="METRIC"
    target.unit_settings.scale_length=scene.unit_settings.scale_length
    target.unit_settings.length_unit="MILLIMETERS"
    target.world=scene.world
    target.render.engine="CYCLES"
    target.cycles.samples=24
    target.render.resolution_x=1800
    target.render.resolution_y=1500
    target.render.resolution_percentage=100
    target.view_settings.view_transform="AgX"
    mapping={}
    for source_collection in scene.collection.children:
        category=source_collection.name.removeprefix("Supported | ")
        if category in ("Construction","Power bend references","Lid","Shell front"):
            continue
        if category=="Shell sides":
            continue
        if mode in ("logic","power") and not (category.startswith("L1" if mode=="logic" else "L2") or category=="Studio"):
            continue
        copied=bpy.data.collections.new(name+" | "+category)
        target.collection.children.link(copied)
        for original in source_collection.objects:
            if original.hide_render or original.get("duct_lid"):
                continue
            obj=original.copy()
            copied.objects.link(obj)
            mapping[original]=obj
            if obj.type=="CAMERA":
                obj.data=obj.data.copy()
                target.camera=obj
    for original,obj in mapping.items():
        if original.parent:
            obj.parent=mapping[original.parent]
    if mode in ("cutaway","rear"):
        bpy.context.window.scene=target
        panel=ns["named_source"]("panel front")
        witness=bpy.data.collections.new(name+" | Front panel cutaway strips")
        target.collection.children.link(witness)
        for center_x in (-65,-16,12):
            obj=panel.copy()
            obj.data=panel.data.copy()
            witness.objects.link(obj)
            obj.name="Front panel anchor section"
            obj["inspection_section_only"]=True
            bpy.ops.mesh.primitive_cube_add(size=1,location=(center_x,-108.5,108))
            cutter=bpy.context.object
            cutter.dimensions=(10,8,210)
            bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
            ns["boolean"](obj,cutter,"INTERSECT")
    bpy.context.window.scene=target
    target.camera.location=camera_position
    target.camera.rotation_euler=(Vector(focal)-target.camera.location).to_track_quat("-Z","Y").to_euler()
    bpy.context.view_layer.update()
    corners=[target.camera.matrix_world.inverted()@(obj.matrix_world@Vector(corner)) for obj in target.objects if obj.type=="MESH" for corner in obj.bound_box]
    scale=max(max(abs(point.x) for point in corners)*2,max(abs(point.y) for point in corners)*2*1800/1500)*1.08
    target.camera.data.ortho_scale=scale
    target["inspection_only"]=True
    target["duct_covers_removed_for_view"]=True

report=json.loads((ns["ROOT"]/"cable-support-check.json").read_text())
report["contact_verification"]=ns["support_graph_report"]
report["inspection_scenes"]=[item[0] for item in specifications]
report["status"]="Supported and connected layout; contact graph verified, not a strength or printability certification"
(ns["ROOT"]/"cable-support-check.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
bpy.context.window.scene=bpy.data.scenes["BATMAN - supported cable cutaway"]
for area in bpy.context.screen.areas:
    if area.type=="VIEW_3D":
        space=area.spaces.active
        space.region_3d.view_location=(0,10,109)
        space.region_3d.view_distance=620
        space.region_3d.view_perspective="ORTHO"
        space.region_3d.view_rotation=bpy.context.scene.camera.rotation_euler.to_quaternion()
        space.shading.color_type="MATERIAL"
        space.overlay.show_extras=False
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.wm.save_as_mainfile(filepath=str(ns["ROOT"]/"cad/assembly-cable-supported.blend"))
result={"saved":bpy.data.filepath,"scenes":report["inspection_scenes"],"ducts_supported":report["contact_verification"]["duct_count"],"failed_joints":report["contact_verification"]["failed_joints"]}