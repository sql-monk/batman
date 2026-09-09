"""Branch ducts, carrier pass-throughs and removable mounting saddles."""

import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
ns = bpy.app.driver_namespace["batman_cables"]
scene = ns["scene"]
bpy.context.window.scene = scene
duct = ns["duct"]
box = ns["box"]
label = ns["label"]
collection = ns["collection"]
power, signal, analog = (ns[key] for key in ("power","signal","analog"))
if any(item["id"] == "PV REAR POWER" for item in ns["ducts"]):
    raise RuntimeError("Branch ducts already exist.")
modifications = []
mounts = []


def subtract(target, cutter):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    modifier = target.modifiers.new("Cable access", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.object = cutter
    bpy.context.view_layer.update()
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def bore(target, point, radius, depth):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=radius,depth=depth,location=point)
    subtract(target,bpy.context.object)


def carrier(name):
    return next(obj for obj in scene.objects if obj.get("source_object") == name+" plate")


def opening(target, size, center, reason):
    cutter=box("Temporary cable cutter",size,center,"Construction",power)
    subtract(target,cutter)
    modifications.append({"part":target.name,"opening_mm":list(size),"center_mm":list(center),"reason":reason})


duct("PV REAR POWER",[(-17,65,17),(-17,65,148)],16,14,power,"Power riser",8,3.5)
for name,height in (("L1 carrier C",41.2),("L2 carrier relay supply",124.2)):
    opening(carrier(name),(25.2,19.5,6),(-14.6,73.7,height),"Open-edge clearance for fixed power riser; remove carrier after disconnecting")
duct("P-IN XT60",[(-80,64,16),(80,64,16)],22,14,power,"L0 power ducts",8,3.5)
duct("PF FUSES",[(-80,92,95),(80,92,95)],16,12,power,"Fuse ducts",8,3.5)
duct("PF RISER LINK",[(-17,81,95),(-17,88,95)],16,12,power,"Fuse ducts",8,3.5)
for index,center_y in ((1,-45),(2,17),(3,78)):
    duct("P"+str(index)+" BRANCH",[(14,center_y,148),(86,center_y,148)],16,12,power,"L2 branch "+str(index)+" ducts",6,3.5)
    label("P"+str(index)+" / POWER",(50,center_y,148+15.4),"L2 branch "+str(index)+" ducts")
duct("PD DPS IN OUT",[(-83,-95.5,148),(-14,-95.5,148)],10,14,power,"L2 DPS ducts",4,3.5)
duct("PR RELAY",[(-78,61,148),(-14,61,148)],14,12,power,"L2 relay ducts",5,3.5)
duct("PL LM2596",[(-80,83,150),(-30,83,150)],8,10,power,"L2 relay ducts",4,2)
duct("S2 DPS UART",[(-11,-47,104),(13,-47,104)],6,6,signal,"L2 control branches",3,1.3)
duct("S2 RELAY",[(-17,36,104),(13,36,104)],8,8,signal,"L2 control branches",5,1.3)
for index,center_y in ((1,-58),(2,4),(3,66)):
    duct("S2 ACS SW "+str(index),[(29,center_y,104),(36.5,center_y,104)],6,6,signal,"L2 control branches",5 if index<3 else 3,1.3)
    duct("SV BRANCH "+str(index),[(36.5,center_y,104),(36.5,center_y,129)],6,4,signal,"Signal feedthroughs",5 if index<3 else 3,1.3,wall=1.2)
    opening(carrier("L2 carrier branch "+str(index)),(9.4,8.7,6),(36.5,center_y+3.35,124.2),"Isolated signal feedthrough; grommet and local detachable tail")
duct("SV DPS",[(-11,-47,104),(-11,-47,139)],4,6,signal,"Signal feedthroughs",3,1.3,wall=1.2)
opening(carrier("L2 carrier DPS"),(8.4,10.7,6),(-11,-42.65,124.2),"UART beside DPS board edge")
duct("SV RELAY",[(-17,36,104),(-17,36,140)],6,6,signal,"Signal feedthroughs",5,1.3,wall=1.2)
opening(carrier("L2 carrier relay supply"),(9.4,10.7,6),(-17,40.35,124.2),"Relay control feedthrough")
duct("SV LOGIC LINK",[(21,10,61),(21,10,104)],12,10,signal,"Signal riser",22,1.3)
duct("S1 A",[(-73,10,61),(12,10,61)],8,8,signal,"L1 signal branches",12,1.3)
duct("S1 C",[(-62,36,61),(12,36,61)],8,8,signal,"L1 signal branches",7,1.3)
duct("S1 D",[(30,43,61),(84,43,61)],10,8,signal,"L1 signal branches",13,1.3)
duct("S1 B",[(30,-88,61),(86,-88,61)],8,8,signal,"L1 signal branches",12,1.3)
duct("AN48 B TO ADS",[(34,-29,59),(34,11,59)],6,6,analog,"L1 analog ducts",5,1.3)
duct("AN49 B TO ADS",[(73,-29,59),(73,11,59)],6,6,analog,"L1 analog ducts",3,1.3)
duct("UI FRONT RISER",[(-9.6,-100,61),(-9.6,-100,182)],4,7,signal,"Front UI ducts",6,1.3,wall=1.2)
opening(carrier("L2 carrier DPS"),(12.4,12,6),(-8.3,-96,124.2),"UI loom open-edge notch, clear of DPS outline and central rail")
duct("UI OLED BUTTON",[(-50,-92,182),(4,-92,182)],6,6,signal,"Front UI ducts",6,1.3)
duct("UI LOGIC FEED",[(-10,-97.5,61),(21,-97.5,61)],6,6,signal,"Front UI ducts",6,1.3)


def pedestal(name, point, bottom, top, target, owner, mat):
    obj=box(name,(7,7,top-bottom),(point[0],point[1],(bottom+top)/2),owner,mat,True)
    bore(obj,(point[0],point[1],(bottom+top)/2),1.7,top-bottom+4)
    bore(target,(point[0],point[1],target.location.z),1.7,10)
    obj["mount_target"]=target.name
    mounts.append({"id":name,"target":target.name,"hole_mm":3.4,"fastener":"M3 through bolt; confirm length", "xy_mm":list(point)})
    return obj


for index,center_y in ((1,-45),(2,17),(3,78)):
    target=carrier("L2 carrier branch "+str(index))
    for center_x in (35,76):
        pedestal("P"+str(index)+" support",(center_x,center_y),125.25,148,target,"L2 branch "+str(index)+" ducts",power)
for center_y in (-90,45):
    target=carrier("L1 carrier B" if center_y<0 else "L1 carrier D")
    pedestal("S1 carrier support",(21,center_y),42.25,61,target,"L1 signal supports",signal)
for center_y in (-88,58):
    target=carrier("L2 carrier branch 1" if center_y<0 else "L2 carrier branch 3")
    pedestal("S2 suspension",(33,center_y),104,123.15,target,"L2 signal supports",signal)
    box("S2 saddle foot",(20,7,1.6),(25,center_y,103.2),"L2 signal supports",signal,True)
frame=next(obj for obj in scene.objects if obj.get("source_object")=="L2 power frame grooved frame")
for center_y in (-75,10,80):
    pedestal("Power spine M3 support",(0,center_y),128.45,148,frame,"L2 power ducts",power)
base=next(obj for obj in scene.objects if obj.get("source_object")=="base")
for center_x in (-68,68):
    pedestal("XT60 duct support",(center_x,64),3.05,16,base,"L0 power ducts",power)


for item in ns["ducts"]:
    start,end=(Vector(item["path_mm"][index]) for index in (0,-1))
    if abs(end.z-start.z)>1:
        continue
    if item["length_mm"]<30:
        continue
    center=(start+end)/2
    height=item["inner_mm"][1]
    angle=0 if abs(end.x-start.x)>abs(end.y-start.y) else math.pi/2
    label(item["id"],(center.x,center.y,center.z+height+3.35),item["owner"],angle)
    for fraction in (0.2,0.8):
        point=start+(end-start)*fraction
        width=item["inner_mm"][0]+3.2
        along=(end-start).normalized()
        normal=Vector((-along.y,along.x,0))
        for side in (-1,1):
            position=point+normal*side*(width/2+2.4)
            lug=box(item["id"]+" strap ear",(4.8,7,2) if abs(along.x)<0.5 else (7,4.8,2),
                    (position.x,position.y,point.z+1),item["owner"],ns["power"] if item["id"].startswith("P") else ns["signal"],True)
            slot_size=(1.4,4.2,5) if abs(along.x)<0.5 else (4.2,1.4,5)
            opening(lug,slot_size,(position.x,position.y,point.z+1),"Reusable 3 mm strap slot")
            lug["strap_slot_mm"]=[4.2,1.4]

ns["routes"].extend([
    {"id":"INPUT OUTPUT","from":"XT60 BAT1/BAT2/PSU/LOAD","via":["P-IN XT60","PV REAR POWER","PF FUSES","P0 POWER"],"to":"F1/F2/Fchg/Fout and power branches","type":"power"},
    {"id":"BRANCH 1","from":"F1","via":["PV REAR POWER","P0 POWER","P1 BRANCH"],"to":"mACS1/B1/mSW1/mDIO1","type":"power"},
    {"id":"BRANCH 2","from":"F2","via":["PV REAR POWER","P0 POWER","P2 BRANCH"],"to":"mACS2/B2/mSW2/mDIO2","type":"power"},
    {"id":"LOAD","from":"mDIO1/mDIO2","via":["P0 POWER","P3 BRANCH","PV REAR POWER"],"to":"LOAD node/mACS3/Fout/XT60 LOAD/C1/C2","type":"power"},
    {"id":"CHARGE","from":"PSU IN/mDPS","via":["PD DPS IN OUT","P0 POWER","PR RELAY","P3 BRANCH"],"to":"mDIO3/Fchg/mREL2/B1/B2","type":"power"},
    {"id":"5V SUPPLY","from":"PCB D/mDC5","via":["PL LM2596","PV REAR POWER"],"to":"PCB D supply OR, LM2596 IN/OUT","type":"power"},
    {"id":"ACS SW","from":"PCB A J6/J7 and PCB B J3/J4/J5","via":["S1 LOGIC","SV LOGIC LINK","S2 CONTROL","S2 ACS SW 1","S2 ACS SW 2","S2 ACS SW 3"],"to":"mACS1/2/3 and mSW1/2 control","type":"signal"},
    {"id":"RELAY CONTROL","from":"PCB D J8","via":["S1 D","S1 LOGIC","SV LOGIC LINK","S2 RELAY","SV RELAY"],"to":"mREL2 control and coil supply","type":"signal"},
    {"id":"UART","from":"PCB A DPS_TX/DPS_RX/GND","via":["S1 A","S1 LOGIC","SV LOGIC LINK","S2 DPS UART","SV DPS"],"to":"mDPS UART","type":"signal","note":"J9 absent in actual PCB; confirm actual pickup pads before wiring"},
    {"id":"CB2 CB3 CB4 CB5 CB6","from":"PCB A/B/C/D","via":["S1 A","S1 B","S1 C","S1 D","S1 LOGIC"],"to":"Actual interboard-cables.csv endpoints","type":"signal"},
    {"id":"UI","from":"PCB A J10/J11","via":["UI LOGIC FEED","UI FRONT RISER","UI OLED BUTTON"],"to":"OLED and button","type":"signal"},
    {"id":"TEMPERATURE","from":"PCB A X4","via":["S1 A","S1 LOGIC","S1 D"],"to":"Rear T1/T2 cable exits; separate low-current tail","type":"signal"},
    {"id":"ADS I2C","from":"PCB A J20/J21","via":["S1 A","S1 LOGIC"],"to":"ADS 0x48/0x49 power and I2C","type":"signal","maximum_cable_mm":200},
    {"id":"AN48","from":"B.J32","via":["AN48 B TO ADS"],"to":"ADS 0x48 analog header","type":"analog","maximum_cable_mm":100},
    {"id":"AN49","from":"B.J33","via":["AN49 B TO ADS"],"to":"ADS 0x49 analog header","type":"analog","maximum_cable_mm":100},
])
ns["carrier_modifications"]=modifications
ns["mounts"]=mounts
result=ns["validate"]()
result["carrier_modifications"]=modifications
result["mounts"]=mounts
(ROOT/"cable-check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"cad/assembly-cable-routing.blend"))