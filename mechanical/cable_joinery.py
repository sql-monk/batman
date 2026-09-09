"""Complete duct junctions and brace every independent wiring assembly."""

import bpy
import math
from mathutils import Vector


ns=bpy.app.driver_namespace["batman_supported"]
scene=ns["scene"]
bpy.context.window.scene=scene
box,bridge,boolean,bore,post=(ns[name] for name in ("box","bridge","boolean","bore","post"))
power,signal,analog=(ns[name] for name in ("power","signal","analog"))
connections=ns["connections"]
anchors=ns["anchors"]
named_source=ns["named_source"]
if any(item["first"]=="P1 BRANCH" for item in connections):
    raise RuntimeError("Joinery already exists.")


def curved_bridge(name,first,second,center,radius,angle_start,angle_end,start_extra,end_extra,width,height,owner,mat):
    path=[]
    if start_extra:
        path.append(start_extra)
    for step in range(17):
        angle=angle_start+(angle_end-angle_start)*step/16
        path.append((center[0]+radius*math.cos(angle),center[1]+radius*math.sin(angle),center[2]))
    if end_extra:
        path.append(end_extra)
    return bridge(name,first,second,path,width,height,owner,mat)


for index,center_y in ((1,-45),(2,17),(3,78)):
    curved_bridge("P"+str(index)+" continuous R15 tee","P"+str(index)+" BRANCH","P0 POWER",
                  (15,center_y-15,148),15,math.pi,math.pi/2,None,(19,center_y,148),16,12,"L2 supported joints",power)
curved_bridge("DPS continuous R15 elbow","PD DPS IN OUT","P0 POWER",(-15,-80.5,148),15,
              -math.pi/2,0,(-21,-95.5,148),(0,-77,148),10,14,"L2 supported joints",power)
curved_bridge("Relay continuous elbow","PR RELAY","P0 POWER",(-12,49,148),12,0,math.pi/2,
              None,(-19,61,148),14,12,"L2 supported joints",power)


def chamber(name,first,second,center,size,owner,mat):
    outer=box(name,size,center,owner,mat)
    inner=box("Chamber void",(size[0]-3.2,size[1]-3.2,size[2]+2),
              (center[0],center[1],center[2]+2.6),"Construction",mat)
    boolean(outer,inner)
    for endpoint in (first,second):
        boolean(outer,ns["interior"](endpoint))
        cutter=box("Chamber connection void",(size[0]-3.2,size[1]-3.2,size[2]+2),
                   (center[0],center[1],center[2]+2.6),"Construction",mat)
        boolean(ns["duct"](endpoint),cutter)
    lid=box(name+" removable cover",(size[0],size[1],1.4),(center[0],center[1],center[2]+size[2]/2+1),owner,mat)
    lid["duct_lid"]=True
    outer["duct_joint"]=True
    connections.append({"first":first,"second":second,"bridge":outer.name,"gap_mm":0,"joint":"covered open-bore chamber"})
    return outer


chamber("Power riser upper plenum","PV REAR POWER","P0 POWER",(-11.6,74.25,155),(31.2,19.5,17.2),"Power riser supported joints",power)
ns["extend"]("PL LM2596",0,-80,-86)
bridge("LM2596 to riser ramp","PL LM2596","PV REAR POWER",[(-34,83,150),(-17,79,148)],8,10,"L2 supported joints",power)
connections[-1]["via_joint"]="Power riser upper plenum"
ns["extend"]("PF RISER LINK",1,81,79)
connections.extend([
    {"first":"PV REAR POWER","second":"P-IN XT60","bridge":None,"gap_mm":0,"joint":"opened intersecting bores"},
    {"first":"PV REAR POWER","second":"PF RISER LINK","bridge":None,"gap_mm":0,"joint":"opened intersecting bores"},
    {"first":"PF RISER LINK","second":"PF FUSES","bridge":None,"gap_mm":0,"joint":"opened intersecting bores"},
])
ns["extend"]("S2 CONTROL",1,-85,-90)
ns["extend"]("S2 CONTROL",1,65,70)
for index,center_y in ((1,-58),(2,4),(3,66)):
    name="S2 ACS SW "+str(index)
    bridge("Joined "+name,name,"S2 CONTROL",[(21,center_y,104),(33,center_y,104)],6,6,"L2 supported signal joints",signal)
    connections.append({"first":name,"second":"SV BRANCH "+str(index),"bridge":None,"gap_mm":0,"joint":"opened riser inlet"})
for name,center_y in (("S2 DPS UART",-47),("S2 RELAY",36)):
    bridge("Joined "+name,name,"S2 CONTROL",[(10,center_y,104),(21,center_y,104)],ns["duct_specs"][name]["inner_mm"][0],6,"L2 supported signal joints",signal)
connections.extend([
    {"first":"S2 DPS UART","second":"SV DPS","bridge":None,"gap_mm":0,"joint":"opened riser inlet"},
    {"first":"S2 RELAY","second":"SV RELAY","bridge":None,"gap_mm":0,"joint":"opened riser inlet"},
    {"first":"S1 LOGIC","second":"SV LOGIC LINK","bridge":None,"gap_mm":0,"joint":"opened riser inlet"},
    {"first":"S2 CONTROL","second":"SV LOGIC LINK","bridge":None,"gap_mm":0,"joint":"opened riser outlet"},
    {"first":"S1 LOGIC","second":"UI LOGIC FEED","bridge":None,"gap_mm":0,"joint":"opened tee"},
    {"first":"UI LOGIC FEED","second":"UI FRONT RISER","bridge":None,"gap_mm":0,"joint":"opened riser inlet"},
    {"first":"UI FRONT RISER","second":"UI OLED BUTTON","bridge":None,"gap_mm":0,"joint":"opened riser outlet"},
])


def join_interiors():
    for link in connections:
        for endpoint,other in ((link["first"],link["second"]),(link["second"],link["first"])):
            spec=ns["duct_specs"][other]
            path=[Vector(point) for point in spec["path_mm"]]
            direction=(path[-1]-path[0]).normalized()
            path[0]-=direction*3
            path[-1]+=direction*3
            width,height=spec["inner_mm"]
            wall=1.2 if other.startswith("SV ") and other!="SV LOGIC LINK" or other=="UI FRONT RISER" else 1.6
            cutter=ns["rectangle_sweep"]("Open intersecting lumen",path,[(-width/2,wall),(width/2,wall),
                        (width/2,height+wall+2),(-width/2,height+wall+2)],"Construction",signal)
            boolean(ns["duct"](endpoint),cutter)


join_interiors()
for center_x in (-65,-32):
    post("DPS duct anchored post",(center_x,-94.4),125.2,148,named_source("L2 carrier DPS plate"),"L2 supported ducts",power,(7,5))
for center_x in (-68,-35):
    post("Relay duct anchored post",(center_x,64),125.2,148,named_source("L2 carrier relay supply plate"),"L2 supported ducts",power)
post("LM2596 outer anchored post",(-83,83),125.2,150,named_source("L2 carrier relay supply plate"),"L2 supported ducts",power)
logic_frame=named_source("L1 logic frame grooved frame")
analog_beam=box("ADS duct frame crossmember",(101,6,3),(48,0,46.9),"L1 analog supports",analog)
for center_x in (0,96):
    bore(analog_beam,(center_x,0,46.9),3.4,8)
    bore(logic_frame,(center_x,0,44),3.4,12)
anchors.append({"support":analog_beam.name,"target":logic_frame.name,"fastener":"2 x M3 through bolts","xy_mm":[[0,0],[96,0]]})
for name,center_x in (("AN48 B TO ADS",34),("AN49 B TO ADS",73)):
    post(name+" anchored saddle",(center_x,0),48.4,59,analog_beam,"L1 analog supports",analog)


def panel_bracket(name,target,center_x,center_z,front=False):
    panel_y=-106.9 if front else 106.9
    inward=1 if front else -1
    foot_height=6 if name=="Power riser rear brace" and center_z>100 else 12
    ear=box(name+" panel foot",(8,3,foot_height),(center_x,panel_y+inward*1.5,center_z),"Panel duct anchors",signal if front else power)
    bore(ear,(center_x,panel_y+inward*1.5,center_z),3.4,8,"Y")
    bore(target,(center_x,target.location.y,center_z),3.4,10,"Y")
    anchors.append({"support":ear.name,"target":target.name,"fastener":"M3 through panel bolt + nut","axis":"Y","center_mm":[center_x,panel_y,center_z]})
    ear["mount_target"]=target.name
    return ear


back=named_source("panel back - interface blanks")
front=named_source("panel front")
for center_z in (88,115):
    foot=panel_bracket("Power riser rear brace",back,-30,center_z)
    arm=box("Power riser brace arm",(7,27,4),(-30,91.9,center_z),"Panel duct anchors",power)
    shoe=box("Power riser side shoe",(5.4,7,8),(-27.3,78,center_z),"Panel duct anchors",power)
    connections.append({"first":"PV REAR POWER","second":"@rear panel","bridge":shoe.name,"via_supports":[arm.name,foot.name],"gap_mm":0.1})
for center_x in (-50,50):
    foot=panel_bracket("Fuse duct wall bracket",back,center_x,88)
    arm=box("Fuse duct wall shelf",(8,20,3),(center_x,95.4,93.5),"Panel duct anchors",power)
    connections.append({"first":"PF FUSES","second":"@rear panel","bridge":arm.name,"via_supports":[foot.name],"gap_mm":0.1})
for center_z in (94,174):
    foot=panel_bracket("UI riser front bracket",front,-16,center_z,True)
    arm=box("UI riser bracket arm",(7,8,4),(-16,-102.9,center_z),"Panel duct anchors",signal)
    shoe=box("UI riser side shoe",(3,3,8),(-12.6,-99.5,center_z),"Panel duct anchors",signal)
    connections.append({"first":"UI FRONT RISER","second":"@front panel","bridge":shoe.name,"via_supports":[arm.name,foot.name],"gap_mm":0.1})
for center_x,end_x in ((-65,-45),(12,1)):
    foot=panel_bracket("OLED duct front bracket",front,center_x,176,True)
    stem=box("OLED duct bracket stem",(7,15,3),(center_x,-99.4,180.5),"Panel duct anchors",signal)
    arm=box("OLED duct bracket arm",(abs(end_x-center_x)+7,7,3),((center_x+end_x)/2,-92,180.5),"Panel duct anchors",signal)
    connections.append({"first":"UI OLED BUTTON","second":"@front panel","bridge":arm.name,"via_supports":[stem.name,foot.name],"gap_mm":0.1})


for item in anchors:
    if item["support"].startswith("A duct post"):
        beam=scene.objects[item["target"]]
        bore(beam,(*item["xy_mm"],46.9),3.4,8)
ns["joinery_namespace"]=globals()
result=ns["validation"]()
bpy.ops.wm.save_as_mainfile(filepath=str(ns["ROOT"]/"cad/assembly-cable-supported.blend"))