"""Accessible duct junctions, harness references and cable inspection scenes."""

import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


ROOT=Path(__file__).resolve().parent
ns=bpy.app.driver_namespace["batman_cables"]
branch=bpy.app.driver_namespace["batman_cable_branches"]
scene=ns["scene"]
bpy.context.window.scene=scene
if bpy.data.scenes.get("BATMAN - cable open"):
    raise RuntimeError("Cable inspection scenes already exist.")
junctions=[]


def find(name):
    return next(obj for obj in ns["printables"] if obj.get("duct_id")==name)


def port(duct_name,center,size):
    obj=find(duct_name)
    cutter=ns["box"]("Junction cutter",size,center,"Construction",ns["power"])
    branch["subtract"](obj,cutter)
    junctions.append({"duct":duct_name,"center_mm":list(center),"size_mm":list(size)})


for center_y in (-45,17,78):
    port("P0 POWER",(10,center_y,157),(5,18,14.5))
for center_y in (-86,61,73):
    port("P0 POWER",(-10,center_y,157),(5,16,14.5))
for center_y in (10,36):
    port("S1 LOGIC",(14,center_y,68),(4,10,9.5))
for center_y in (-80,43):
    port("S1 LOGIC",(28,center_y,68),(4,10,9.5))
for center_y in (-58,4,61):
    port("S2 CONTROL",(28,center_y,111),(4,10,9.5))
for center_y in (-47,36):
    port("S2 CONTROL",(14,center_y,111),(4,10,9.5))
for center_z in (30,103):
    port("PV REAR POWER",(-17,79.8,center_z),(17,4,14))


def cable(name,points,diameter,owner,mat):
    curve=bpy.data.curves.new(name,"CURVE")
    curve.dimensions="3D"
    curve.resolution_u=16
    curve.bevel_depth=diameter/2
    curve.bevel_resolution=3
    spline=curve.splines.new("POLY")
    spline.points.add(len(points)-1)
    for point,coordinate in zip(spline.points,points):
        point.co=(*coordinate,1)
    obj=bpy.data.objects.new(name,curve)
    ns["collection"](owner).objects.link(obj)
    curve.materials.append(mat)
    obj["cable_group"]=owner
    obj["harness_reference"]=True
    obj["electrical_netlist_verified"]=False
    return obj


for item in ns["ducts"]:
    start,end=(Vector(point) for point in (item["path_mm"][0],item["path_mm"][-1]))
    direction=(end-start).normalized()
    normal=Vector((-direction.y,direction.x,0))
    if normal.length<0.1:
        normal=Vector((1,0,0))
    normal.normalize()
    up=direction.cross(normal).normalized()
    diameter=item["wire_outer_diameter_assumed_mm"]
    column_count=max(1,int((item["inner_mm"][0]-0.6)/(diameter+0.4)+1e-6))
    for index in range(item["conductors_design"]):
        row,column=divmod(index,column_count)
        offset=-(column_count-1)*(diameter+0.4)/2+column*(diameter+0.4)
        height=1.9+diameter/2+row*(diameter+0.4)
        assert height+diameter/2 < item["inner_mm"][1]+1.6,(item["id"],height)
        points=[start+normal*offset+up*height,end+normal*offset+up*height]
        mat=ns["red"] if item["id"].startswith("P") and index%2 else ns["black"]
        cable(item["id"]+" bundle "+str(index+1),points,diameter,item["owner"],mat)

analog_lengths={}
for name,start,trough_start,trough_end,end in (
    ("AN48",(36,-33,53),(34,-29,62),(34,11,62),(29,14,53)),
    ("AN49",(69,-33,53),(73,-29,62),(73,11,62),(77,14,53)),
):
    points=[Vector(point) for point in (start,trough_start,trough_end,end)]
    length=sum((following-previous).length for previous,following in zip(points,points[1:]))+15
    assert length<=100
    analog_lengths[name]=round(length,1)
    cable(name+" short tail route",points,1.2,"L1 analog ducts",ns["analog"])

for index,center_y in ((1,-45),(2,17),(3,78)):
    points=[]
    for step in range(17):
        angle=math.pi-step*math.pi/32
        points.append(Vector((15+15*math.cos(angle),center_y-15+15*math.sin(angle),167.5)))
    cable("P"+str(index)+" R15 service turn reference",points,3.5,"Power bend references",ns["red"])
    ns["label"]("R15 / DISCONNECT",(28,center_y-8,170),"Power bend references")

source_report=ns["validate"]()
source_report["carrier_modifications"]=branch["modifications"]
source_report["mounts"]=branch["mounts"]
source_report["junction_ports"]=junctions
source_report["analog_cable_allowance_mm"]=analog_lengths
source_report["bulk_separation_mm"]={"upper_power_to_control_vertical":148-(104+10+3.3),
                                      "power_riser_to_signal_spine_horizontal":(21-7.6)-(-17+9.6),
                                      "fuse_power_to_lower_signal_vertical":95-(61+10+3.3)}
assert all(value>=20 for value in source_report["bulk_separation_mm"].values())
source_report["limitations"].extend([
    "Local endpoint tails may approach power; cross at right angles and do not bundle together",
    "R15 service turns shown above open junctions; not a validated enclosed bend fitting",
    "Harness curves represent duct occupancy and topology, not individual electrical net continuity",
    "Disconnect labelled cassette tails before withdrawing; no live hot-swap or drag chain",
    "Rear riser, fuse and UI ducts still need final wall attachment hardware",
    "Short analog lengths use low-profile dressed tails, verify with actual headers",
    "J9 missing in actual PCB: UART pickup must be confirmed",
])

views=(
    ("BATMAN - cable open","open",(350,-480,390),(0,8,108)),
    ("BATMAN - cable power","power",(130,-240,550),(0,0,138)),
    ("BATMAN - cable logic","logic",(110,-230,450),(0,0,62)),
    ("BATMAN - cable rear","rear",(-310,490,350),(0,30,106)),
)
for name,mode,position,target in views:
    target_scene=bpy.data.scenes.new(name)
    target_scene.unit_settings.system="METRIC"
    target_scene.unit_settings.scale_length=scene.unit_settings.scale_length
    target_scene.unit_settings.length_unit="MILLIMETERS"
    target_scene.world=scene.world
    target_scene.render.engine="CYCLES"
    target_scene.cycles.samples=24
    target_scene.render.resolution_x=1800
    target_scene.render.resolution_y=1500
    target_scene.render.resolution_percentage=100
    target_scene.view_settings.view_transform="AgX"
    mapping={}
    for source_collection in scene.collection.children:
        category=source_collection.name.removeprefix("Cable | ")
        if category.startswith(("Shell","Lid","Construction")):
            continue
        if mode in ("power","logic"):
            level="L2" if mode=="power" else "L1"
            if not (category.startswith(level) or category=="Studio" or mode=="power" and category in ("Signal feedthroughs","Power bend references")):
                continue
        copied=bpy.data.collections.new(name+" | "+category)
        target_scene.collection.children.link(copied)
        for original in source_collection.objects:
            if original.hide_render or original.get("duct_lid"):
                continue
            obj=original.copy()
            copied.objects.link(obj)
            mapping[original]=obj
            if obj.type=="CAMERA":
                obj.data=obj.data.copy()
                target_scene.camera=obj
    for original,obj in mapping.items():
        if original.parent:
            obj.parent=mapping[original.parent]
    target_scene.camera.location=position
    target_scene.camera.rotation_euler=(Vector(target)-target_scene.camera.location).to_track_quat("-Z","Y").to_euler()
    bpy.context.window.scene=target_scene
    bpy.context.view_layer.update()
    points=[target_scene.camera.matrix_world.inverted()@(obj.matrix_world@Vector(corner))
            for obj in target_scene.objects if obj.type=="MESH" for corner in obj.bound_box]
    horizontal=max(abs(point.x) for point in points)
    vertical=max(abs(point.y) for point in points)
    target_scene.camera.data.ortho_scale=max(horizontal*2,vertical*2*1800/1500)*1.12
    target_scene["inspection_only"]=True
    target_scene["duct_lids_omitted"]=True
source_report["inspection_scenes"]=[item[0] for item in views]
(ROOT/"cable-check.json").write_text(json.dumps(source_report,indent=2),encoding="utf-8")
scene["cable_routing_status"]="Segregated cable ducts; measured component coordinates preserved; attachment and harness fit prototype"
bpy.context.window.scene=bpy.data.scenes["BATMAN - cable open"]
for area in bpy.context.screen.areas:
    if area.type=="VIEW_3D":
        space=area.spaces.active
        space.region_3d.view_location=(0,8,108)
        space.region_3d.view_distance=620
        space.region_3d.view_perspective="ORTHO"
        space.region_3d.view_rotation=bpy.context.scene.camera.rotation_euler.to_quaternion()
        space.shading.color_type="MATERIAL"
        space.overlay.show_extras=False
        space.clip_end=5000
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-cable-routing.blend"))
result={"ducts":len(ns["ducts"]),"parts":len(ns["printables"]),"junctions":len(junctions),
        "analog_mm":analog_lengths,"separation_mm":source_report["bulk_separation_mm"],"collisions":source_report["surface_collisions_with_existing_geometry"]}