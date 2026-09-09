"""Non-destructive component revision of the existing millimetre assembly."""

import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
SOURCE = bpy.data.scenes["BATMAN - assembly"]
NAME = "BATMAN - detailed assembly"
if bpy.data.scenes.get(NAME):
    raise RuntimeError("Detailed revision already exists; keep it and use a fresh source file.")
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
groups = {}
inventory = []
pad_objects = []


def group(name):
    if name not in groups:
        value = bpy.data.collections.new("Detail | " + name)
        scene.collection.children.link(value)
        groups[name] = value
    return groups[name]


def mat(name, color, metal=0):
    value = bpy.data.materials.new("Detail | " + name)
    value.diffuse_color = (*color, 1)
    value.use_nodes = True
    shader = next(node for node in value.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metal
    shader.inputs["Roughness"].default_value = 0.38
    return value


green = mat("FR4 green", (0.025, 0.24, 0.10))
black = mat("Component black", (0.022, 0.028, 0.032))
silver = mat("Tin and aluminium", (0.65, 0.7, 0.73), 0.8)
gold = mat("Gold contacts", (0.75, 0.48, 0.08), 0.75)
blue = mat("Relay blue", (0.025, 0.20, 0.55))
yellow = mat("XT60 nylon", (0.96, 0.60, 0.015))
copper = mat("Inductor copper", (0.60, 0.22, 0.065), 0.75)
white = mat("Silkscreen", (0.89, 0.93, 0.91))
red = mat("Positive insulation", (0.62, 0.018, 0.012))
ceramic = mat("Ceramic", (0.39, 0.27, 0.12))


def register(obj, name, owner, material, parent=None):
    obj.name = name
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    group(owner).objects.link(obj)
    obj["detail_group"] = owner
    obj["visual_reference"] = True
    if material:
        obj.data.materials.append(material)
    if parent:
        obj.parent = parent
    return obj


def box(name, size, pos, owner, material=black, parent=None):
    mesh = bpy.data.meshes.new(name)
    vertices = [(axis_x * size[0] / 2, axis_y * size[1] / 2, axis_z * size[2] / 2)
                for axis_x, axis_y, axis_z in ((-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),
                                               (1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1))]
    mesh.from_pydata(vertices, [], [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)])
    obj = bpy.data.objects.new(name, mesh)
    register(obj, name, owner, material, parent)
    obj.location = pos
    return obj


def cylinder(name, radius, depth, pos, owner, material=silver, parent=None, axis="Z"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth)
    obj = register(bpy.context.object, name, owner, material, parent)
    obj.location = pos
    if axis == "Y":
        obj.rotation_euler.x = math.pi / 2
    if axis == "X":
        obj.rotation_euler.y = math.pi / 2
    return obj


def text(body, pos, owner, size=2, parent=None, rotation=None):
    curve = bpy.data.curves.new(body, "FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new(body, curve)
    register(obj, body, owner, white, parent)
    obj.location = pos
    if rotation:
        obj.rotation_euler = rotation
    if owner == "Rear XT60 interfaces":
        obj.data.materials.clear()
        obj.data.materials.append(black)
    return obj


def root(name, pos, owner, size, source, kind):
    obj = bpy.data.objects.new(name, None)
    group(owner).objects.link(obj)
    obj.location = pos
    obj["component_id"] = name
    obj["envelope_mm"] = list(size)
    obj["dimension_source"] = source
    obj["detail_source"] = "Package reconstruction; internal dimensions not metrology"
    inventory.append({"id": name, "kind": kind, "size_mm": list(size), "source": source, "group": owner})
    return obj


def wire(name, points, radius, owner, material=black, parent=None):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1)
    obj = bpy.data.objects.new(name, curve)
    return register(obj, name, owner, material, parent)


def drill(obj, point, radius, axis="Z", depth=8):
    cutter = cylinder("construction", radius, depth, point, "Construction", None, axis=axis)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Opening", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def header(name, points, owner, parent=None, base=1.6, socket=False):
    for index, point in enumerate(points):
        box(name + " insulator", (2.45, 2.45, 2.5 if not socket else 8.5),
            (*point, base + (1.25 if not socket else 4.25)), owner, black, parent)
        if socket:
            cylinder(name + " socket", 0.45, 0.12, (*point, base + 8.55), owner, gold, parent)
        else:
            box(name + " pin " + str(index + 1), (0.64, 0.64, 8), (*point, base + 3), owner, gold, parent)


def terminal(name, count, pos, owner, parent=None, pitch=5, height=9):
    for index in range(count):
        center_x = pos[0] + (index - (count - 1) / 2) * pitch
        box(name + " block", (pitch - 0.15, 7, height), (center_x, pos[1], pos[2] + height / 2), owner, blue, parent)
        cylinder(name + " screw", 1.65, 0.3, (center_x, pos[1], pos[2] + height + 0.1), owner, silver, parent)
        box(name + " screw slot", (2.4, 0.4, 0.05), (center_x, pos[1], pos[2] + height + 0.27), owner, black, parent)
        cylinder(name + " wire entry", 1.5, 0.15, (center_x, pos[1] - 3.56, pos[2] + 3), owner, black, parent, "Y")


def capacitor(name, pos, radius, height, owner, parent, material=black):
    cylinder(name, radius, height, (pos[0], pos[1], pos[2] + height / 2), owner, material, parent)
    cylinder(name + " vent", radius * 0.91, 0.15, (pos[0], pos[1], pos[2] + height), owner, silver, parent)
    for angle in (0, math.pi / 2):
        slot = box(name + " vent score", (radius * 1.2, 0.18, 0.05), (pos[0], pos[1], pos[2] + height + 0.1), owner, black, parent)
        slot.rotation_euler.z = angle


for collection in SOURCE.collection.children:
    if collection.name in ("Clearance references", "Construction"):
        continue
    for original in collection.objects:
        keep = original.get("printable_concept") or original.type in ("CAMERA", "LIGHT") or original.name.startswith("Legend L")
        if not keep:
            continue
        obj = original.copy()
        if original.data:
            obj.data = original.data.copy()
        group(collection.name).objects.link(obj)
        obj["source_object"] = original.name
        obj["detail_group"] = collection.name
        if obj.type == "CAMERA":
            scene.camera = obj

pcb_data = json.loads((ROOT / "pcb-components.json").read_text())
centers = {"A": (-49,-47), "B": (49,-51), "C": (-49,64), "D": (49,72)}
for board_name, spec in pcb_data.items():
    owner = "L1 carrier " + board_name
    center_x, center_y = centers[board_name]
    width, length = spec["size"]
    pcb = box("PCB " + board_name + " substrate", (width,length,1.6), (center_x,center_y,48), owner, green)
    root("PCB " + board_name, (center_x,center_y,47.2), owner, (width,length,1.6), "Current KiCad outline; thickness 1.6 assumed", "pcb")
    text("PCB " + board_name, (center_x, center_y + length / 2 - 4,48.85), owner, 3)
    for entry in spec["components"]:
        reference = entry["reference"]
        points = [(center_x - width/2 + pad["xy"][0], center_y + length/2 - pad["xy"][1]) for pad in entry["pads"]]
        position = (center_x - width/2 + entry["xy"][0], center_y + length/2 - entry["xy"][1],48.8)
        node = root(board_name + "." + reference, position, owner, (0,0,0), "Exact KiCad footprint and pad coordinates", "footprint")
        node["kicad_xy"] = entry["xy"]
        node["kicad_rotation"] = entry["rotation"]
        for index, (point, pad) in enumerate(zip(points, entry["pads"])):
            if reference.startswith("H"):
                drill(pcb, (*point,48), pad["drill"][0]/2)
            else:
                land = cylinder(board_name + "." + reference + ".pad" + str(index), min(pad["size"])/2, 0.08, (*point,48.84), owner, silver)
                land["pad_number"] = pad["number"]
                land["net"] = pad["net"]
                pad_objects.append((land, (*point,48.84)))
        if reference.startswith(("H", "aux", "NT")):
            continue
        midpoint = tuple(sum(point[axis] for point in points) / len(points) for axis in (0,1))
        if reference == "J1":
            header("J1 DevKit socket", points, owner, base=48.8, socket=True)
            esp = root("mMCU", (*midpoint,57.3), owner, (28,55,13), "Measured 55 x 28 x 13; position from 38 socket pads", "module")
            box("ESP32 DevKitC PCB", (28,55,1.6), (0,0,0.8), owner, black, esp)
            box("ESP32 WROOM shield", (18,18,2.8), (0,10,3), owner, silver, esp)
            text("ESP32", (0,10,4.5), owner, 2.2, esp)
            for offset in range(6):
                box("ESP antenna trace", (14 if offset % 2 else 10,0.5,0.1), (0,21+offset,1.66), owner, gold, esp)
            box("CH340", (5,8,1.5), (0,-9,2.4), owner, black, esp)
            box("USB-C shield", (9,7,3.2), (0,-24,3.2), owner, silver, esp)
            box("USB-C opening", (7,0.2,1.7), (0,-27.55,3.2), owner, black, esp)
            for side in (-1,1):
                box("BOOT EN switch", (4,5,2), (side*9,-22,2.6), owner, silver, esp)
                box("BOOT EN cap", (2.3,3,0.8), (side*9,-22,4), owner, black, esp)
        elif reference.startswith("J"):
            header(reference, points, owner, base=48.8)
        elif reference.startswith("X"):
            if len(points) == 1:
                cylinder(reference + " solder terminal", 1.1, 3, (*points[0],50.3), owner, silver)
            else:
                terminal_node = bpy.data.objects.new(reference + " terminal root", None)
                group(owner).objects.link(terminal_node)
                terminal_node.location = (*midpoint,48.8)
                terminal_node.rotation_euler.z = math.atan2(points[-1][1]-points[0][1],points[-1][0]-points[0][0])
                terminal(reference,len(points),(0,0,0),owner,terminal_node)
        elif reference.startswith("Q"):
            cylinder(reference + " TO92", 2.4, 4.5, (*midpoint,53), owner, black)
            for point in points:
                cylinder(reference + " lead", 0.23, 3, (*point,50.3), owner, silver)
        elif reference.startswith("VD"):
            body = cylinder(reference + " DO41", 1.35, 5.2, (*midpoint,51), owner, black, axis="X")
            for point in points:
                wire(reference + " lead", [(*point,48.8),(*point,51),(*midpoint,51)],0.25,owner,silver)
            cylinder(reference + " cathode band",1.38,0.5,(midpoint[0]+1.8,midpoint[1],51),owner,silver,axis="X")
        elif reference.startswith(("R","C")):
            body = box(reference + " 1206", (3.2,1.6,0.8), (*midpoint,46.8), owner, black if reference.startswith("R") else ceramic)
            body.rotation_euler.z = -math.radians(entry["rotation"])
            body["mounting_side"] = "B.Cu; SMD option, no duplicate through-hole capacitor"
        text(reference,(position[0],position[1]+2.2,49),owner,1.3)


def module(name, source_name, source_note):
    envelope = SOURCE.objects[source_name + " envelope"]
    owner = envelope.get("group")
    bottom = envelope.location.z - envelope.dimensions.z/2
    node = root(name, (envelope.location.x,envelope.location.y,bottom), owner, envelope.dimensions, source_note, "module")
    box(name + " PCB", (envelope.dimensions.x,envelope.dimensions.y,1.6), (0,0,0.8), owner, green, node)
    text(name, (0,envelope.dimensions.y/2-3,1.7), owner, 2, node)
    return node, owner


dps, owner = module("mDPS", "DPS5015", "Measured 67 x 91 x 40; visual reference joy-it JT-DPS5015-01.png")
box("DPS heatsink base", (31,38,3), (-12,0,3.1), owner, silver,dps)
for offset in range(8):
    box("DPS heatsink fin", (1.1,38,15), (-26+offset*4,0,12), owner,silver,dps)
fan = box("DPS fan frame",(32,32,8),(-12,0,23.5),owner,black,dps)
drill(fan, (dps.location.x-12,dps.location.y,dps.location.z+23.5),14,depth=12)
cylinder("DPS fan hub",5,8,(-12,0,23.5),owner,black,dps)
for index in range(7):
    angle = index*math.tau/7
    blade = box("DPS fan blade",(10,4,1.4),(-12+9*math.cos(angle),9*math.sin(angle),24),owner,black,dps)
    blade.rotation_euler = (0,0.3,angle+0.45)
bpy.ops.mesh.primitive_torus_add(major_radius=11,minor_radius=4,major_segments=48,minor_segments=16)
toroid = register(bpy.context.object,"DPS toroidal inductor",owner,black,dps)
toroid.location = (13,24,18)
toroid.rotation_euler.x = math.pi/2
for index in range(26):
    angle = index*math.tau/26
    points=[]
    for step in range(17):
        cross=step*math.tau/16
        radius=11+4.5*math.cos(cross)
        points.append((13+radius*math.cos(angle),24+4.5*math.sin(cross),18+radius*math.sin(angle)))
    wire("DPS copper winding",points,0.55,owner,copper,dps)
for position,radius,height in (((-24,-28,1.6),5,24),((-11,-28,1.6),5,24),((2,-28,1.6),5,20),((17,-15,1.6),5,18),((27,-15,1.6),5,18),((14,-32,1.6),3.5,11)):
    capacitor("DPS capacitor",position,radius,height,owner,dps)
for index, label in enumerate(("IN+","IN-","OUT+","OUT-")):
    center_x=-23+index*14
    box("DPS " + label + " terminal",(10,9,3),(center_x,-39,3.1),owner,silver,dps)
    cylinder("DPS " + label + " screw",2.4,2,(center_x,-39,5.5),owner,silver,dps)
    text(label,(center_x,-44,1.7),owner,1.5,dps)
header("DPS UART",[(25,-4),(25,-1.46),(25,1.08)],owner,dps)
for center_y in (-17,8):
    box("DPS control IC",(8,8,1.2),(16,center_y,2.2),owner,black,dps)

relay,owner=module("mREL2","mREL2","Measured 50 x 40 x 19; relay packages reconstructed")
for center_x in (-12,12):
    box("FL-3FF-S-Z relay",(19,15.5,15.4),(center_x,-2,9.3),owner,blue,relay)
    text("FL-3FF",(center_x,-2,17.1),owner,2,relay)
    terminal("COM NO NC",3,(center_x,-15,1.6),owner,relay)
    box("Relay optocoupler",(6,4,2.5),(center_x,11,2.85),owner,black,relay)
header("Relay VCC GND IN1 IN2",[(-5+index*2.54,17) for index in range(4)],owner,relay)
header("Relay JD-VCC",[(20,13)],owner,relay)

dc,owner=module("mDC5","LM2596","Supplier 44 x 22 x 15; HW-411 package layout approximate")
for center_x in (-15,15):
    capacitor("LM2596 electrolytic",(center_x,-3,1.6),4,11,owner,dc)
cylinder("470 inductor",5,7,(2,0,5.1),owner,black,dc)
text("470",(2,0,8.7),owner,2.5,dc)
box("LM2596 trimmer",(9,4,7),(-6,6,5.1),owner,blue,dc)
cylinder("LM2596 adjustment",1.3,0.5,(-8,6,8.8),owner,gold,dc)
box("LM2596 regulator",(8,6,3),(-7,-3,3.1),owner,black,dc)
for center_x in (-20,20):
    for center_y in (-7,7):
        cylinder("LM2596 solder pad",1.3,0.1,(center_x,center_y,1.7),owner,silver,dc)

for index in (1,2,3):
    sensor,owner=module("mACS"+str(index),"mACS"+str(index),"17.8 x 20.3 from original Pololu specification; actual 3-pin variant UNCONFIRMED")
    box("ACS Hall package",(5,5,1.5),(0,1,2.35),owner,black,sensor)
    for center_x in (-5,5):
        box("ACS current pad",(6,8,0.15),(center_x,-4,1.7),owner,silver,sensor)
        cylinder("ACS current solder",1.7,0.25,(center_x,-4,1.9),owner,gold,sensor)
    header("ACS VCC GND VOUT",[(-2.54,8),(0,8),(2.54,8)],owner,sensor)
    diode,owner=module("mDIO"+str(index),"mDIO"+str(index),"Measured 17 x 10; height 5 estimated; XL74610 topology from components.md")
    box("XL74610 MOSFET",(5,6,1.2),(2,0,2.2),owner,black,diode)
    box("LM74610 driver",(3,3,0.9),(-3,1,2.05),owner,black,diode)
    for center_x in (-7,7):
        box("XL74610 solder end",(2.5,8,0.1),(center_x,0,1.7),owner,silver,diode)
    if index < 3:
        switch,owner=module("mSW"+str(index),"mSW"+str(index),"Pololu 2815: 20.3 x 25.4 x 4 PCB assembly; terminals on reverse per manufacturer")
        for center_x in (-5,5):
            box("HP power MOSFET",(7,9,2),(center_x,2,2.6),owner,black,switch)
        box("Pololu slide casing",(7,3,2),(0,-10,2.6),owner,silver,switch)
        box("Pololu slide actuator",(2,3,1.4),(1.5,-11,4),owner,black,switch)
        terminal("Pololu VIN GND VOUT GND",4,(0,0,0),owner,switch,height=8)
        terminal_objects=[obj for obj in group(owner).objects if obj.parent == switch and obj.name.startswith("Pololu VIN")]
        for obj in terminal_objects:
            obj.location.y += 8
            obj.location.z = 1.6 - obj.location.z
        switch.location.z += 5
        for side in (-1,1):
            header("Pololu control",[(side*8,-7),(side*8,-4.46)],owner,switch)
        for obj in group(owner).objects:
            if obj.get("source_object", "").startswith(("module edge support", "provisional adjustable saddle")) and abs(obj.location.x-51)<15:
                obj.location.y -= 10
                obj.dimensions.y = 6
                obj.dimensions.z += 5
                obj.location.z += 2.5

for address in ("0x48","0x49"):
    adc,owner=module("ADS "+address,"ADS "+address,"Supplier/photo estimate 28 x 17; second module procurement unresolved")
    box("ADS1115 TSSOP",(5,4.4,1.2),(0,1,2.2),owner,black,adc)
    for side in (-1,1):
        for index in range(5):
            box("ADS IC lead",(0.35,1.2,0.3),(-1.3+index*0.65,1+side*2.6,1.9),owner,silver,adc)
    header("ADS module header",[(-11.43+index*2.54,-6) for index in range(10)],owner,adc)
    box("ADS local 100n",(1.6,0.8,0.7),(6,2,1.95),owner,ceramic,adc)
    text(address,(0,5,1.75),owner,2.2,adc)

owner="L2 carrier branch 3"
node=root("LOAD distribution",(51,54,130.2),owner,(22,20,15),"Terminal node capacity and dimensions provisional", "distribution")
terminal("LOAD bus",4,(0,0,0),owner,node)
for index,center_y in ((1,-48),(2,14)):
    owner="L2 carrier branch "+str(index)
    node=root("B"+str(index)+" distribution",(49,center_y,130.2),owner,(20,8,10),"Required branch junction; terminal type provisional", "distribution")
    terminal("Branch junction",4,(0,0,0),owner,node)

owner="Rear XT60 interfaces"
back=next(obj for obj in scene.objects if obj.get("source_object", "").startswith("panel back"))
for center_x,name in zip((-75,-25,25,75),("BAT1","BAT2","PSU IN","LOAD OUT")):
    connector=root("XT60 "+name,(center_x,109,20),owner,(16,20,9),"XT60 family selected by user; generic 16 x 9 face, exact variant and gender TBD", "xt60")
    profile=[(-8,-4.5),(8,-4.5),(8,2),(5.5,4.5),(-5.5,4.5),(-8,2)]
    vertices=[(coord_x,coord_y,coord_z) for coord_y in (-10,10) for coord_x,coord_z in profile]
    faces=[tuple(reversed(range(6))),tuple(range(6,12))]+[(index,(index+1)%6,(index+1)%6+6,index+6) for index in range(6)]
    mesh=bpy.data.meshes.new("XT60 keyed shell")
    mesh.from_pydata(vertices,[],faces)
    housing=bpy.data.objects.new("XT60 "+name+" keyed shell",mesh)
    register(housing,housing.name,owner,yellow,connector)
    for side in (-1,1):
        drill(housing,(center_x+side*3.5,109,20),2.2,"Y",24)
        cylinder("XT60 contact sleeve",1.75,10,(side*3.5,1,0),owner,gold,connector,"Y")
        cylinder("XT60 contact recess",1.2,0.1,(side*3.5,6.1,0),owner,black,connector,"Y")
        cylinder("XT60 solder cup",1.75,4,(side*3.5,-11,0),owner,gold,connector,"Y")
        wire("XT60 insulated tail",[(side*3.5,-13,0),(side*3.5,-23,0),(side*3.5,-33,8)],1.4,owner,red if side==1 else black,connector)
    cutter=box("XT60 clearance cutter",(17,12,10),(center_x,108.5,20),"Construction",None)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    back.select_set(True)
    bpy.context.view_layer.objects.active=back
    modifier=back.modifiers.new("Provisional XT60 clearance","BOOLEAN")
    modifier.operation="DIFFERENCE"
    modifier.object=cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter,do_unlink=True)
    text(name,(center_x,110.2,31),owner,3,rotation=(math.pi/2,0,math.pi))
    text("XT60",(center_x,110.2,10),owner,2,rotation=(math.pi/2,0,math.pi))
    fuse_id={"BAT1":"F1","BAT2":"F2","PSU IN":"Fchg","LOAD OUT":"Fout"}[name]
    fuse=root(fuse_id,(center_x,94,72),"Rear fuse holders",(30,15,20),"ATO holder estimated 30 x 15 x 20; exact retention TBD", "fuse")
    box(fuse_id+" insulated holder",(30,15,12),(0,0,-4),"Rear fuse holders",black,fuse)
    box(fuse_id+" ATO 15A",(19,5,12),(0,0,4),"Rear fuse holders",blue,fuse)
    text(fuse_id+" 15A",(0,-2,10.1),"Rear fuse holders",2,fuse)

owner="L0 capacitors - PROVISIONAL"
buffer=root("C1 LOAD buffer",(75,91,12),owner,(12,12,22),"100uF 50V required; D12 H22 remains unmeasured", "capacitor")
capacitor("C1 100uF 50V",(0,0,0),6,22,owner,buffer,blue)
cer=root("C2 LOAD buffer",(64,96,19),owner,(6,4,7),"100nF required; package dimensions unmeasured", "capacitor")
box("C2 ceramic",(6,4,7),(0,0,0),owner,ceramic,cer)
for side in (-1,1):
    wire("C1 short terminal lead",[(75+side*2.5,91,12),(75+side*3.5,96,20)],0.35,owner,silver)
    wire("C2 short terminal lead",[(64+side*2.5,96,15.5),(75+side*3.5,96,20)],0.25,owner,silver)
for obj in list(group(owner).objects):
    if obj.get("printable_concept"):
        obj.hide_render=True
        obj.hide_set(True)

owner="Front instruments"
oled=root("mOLED",(-43,-104,193),owner,(28,4,28),"Supplier PCB 28 x 28; active area 24.8 x 16.8", "module")
box("OLED PCB",(28,1.6,28),(0,0,0),owner,blue,oled)
box("OLED glass",(26,1.5,19),(0,-1.55,0),owner,black,oled)
screen=box("OLED active display",(24.8,0.1,16.8),(0,-2.35,0),owner,black,oled)
text("BATMAN",(0,-2.5,1),owner,3,oled,(math.pi/2,0,0))
text("28.4 V",(0,-2.5,-5),owner,3,oled,(math.pi/2,0,0))
for index in range(4):
    box("OLED pin",(0.64,6,0.64),(-3.81+index*2.54,3,11),owner,gold,oled)
button=root("Button",(0,-109,193),owner,(12,10,12),"12 mm panel requirement; actual switch depth TBD", "button")
cylinder("Button bezel",7,2,(0,0,0),owner,silver,button,"Y")
cylinder("Button plunger",5.5,3,(0,-2,0),owner,black,button,"Y")
cylinder("Button barrel",5.8,8,(0,5,0),owner,silver,button,"Y")

for index,center_x in ((1,-12),(2,12)):
    owner="External temperature probes"
    probe=root("T"+str(index),(center_x,152,44),owner,(6,6,50),"Supplier DS18B20 D6 x 50; probes outside at batteries", "external_probe")
    cylinder("DS18B20 stainless probe",3,50,(0,0,0),owner,silver,probe)
    wire("T"+str(index)+" cable",[(center_x,152,19),(center_x,138,12),(center_x,120,44),(center_x,100,44)],2,owner)
    drill(back,(center_x,108.5,44),3,"Y",10)
    cylinder("DS18B20 grommet",4.5,4,(center_x,108.5,44),owner,black,axis="Y")

scene["design_status"]="Detailed component layout; not manufacturing release. Purchased-module internals reconstructed, unmeasured interfaces flagged."
scene["source_scene"] = SOURCE.name
scene["xt60_ports"] = "BAT1, BAT2, PSU IN, LOAD OUT; variant/gender requires confirmation"
bpy.context.view_layer.update()
assert len([item for item in inventory if item["kind"]=="xt60"])==4
assert len([item for item in inventory if item["kind"]=="footprint"])==sum(len(value["components"]) for value in pcb_data.values())
assert all((obj.matrix_world.translation-Vector(expected)).length < 0.001 for obj,expected in pad_objects)
assert len(SOURCE.objects)==255, "Source scene changed unexpectedly"
result={"scene":scene.name,"source_objects_preserved":len(SOURCE.objects),"footprints":sum(len(value["components"]) for value in pcb_data.values()),"pad_coordinates_verified":len(pad_objects),"inventory":inventory,
        "unverified":["Exact XT60 variant, gender and panel retention", "ACS three-pin module identity", "Purchased-module internal package dimensions", "Module mounting and PCB component heights", "Full harness routing, thermal and assembly collision clearance", "ATO access and OLED/USB mounting", "C1/C2 package sizes", "Optional enclosure fan not installed"]}
(ROOT/"detail-check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-detailed.blend"))