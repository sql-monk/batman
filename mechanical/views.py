"""Add inspection scenes without changing the assembled geometry."""

import bpy
import bmesh
import json
from pathlib import Path
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
source = bpy.data.scenes["BATMAN - assembly"]
created = []
for name, exploded in (("BATMAN - open", False), ("BATMAN - levels", True)):
    if bpy.data.scenes.get(name):
        raise RuntimeError("Inspection scene already exists: " + name)
    target = bpy.data.scenes.new(name)
    target.unit_settings.system = "METRIC"
    target.unit_settings.scale_length = 0.001
    target.unit_settings.length_unit = "MILLIMETERS"
    target.render.engine = "CYCLES"
    target.cycles.samples = 32
    target.render.resolution_x = 1500
    target.render.resolution_y = 1500
    target.render.resolution_percentage = 100
    target.world = source.world
    target.view_settings.view_transform = "AgX"
    bpy.context.window.scene = target
    for group in source.collection.children:
        if group.name.startswith(("Shell", "Lid", "Front instruments", "Clearance references", "Construction")):
            continue
        target_group = bpy.data.collections.new(name + " | " + group.name)
        target.collection.children.link(target_group)
        for original in group.objects:
            obj = original.copy()
            target_group.objects.link(obj)
            if original.get("reference_only"):
                obj.hide_set(True)
            if original.type == "CAMERA":
                obj.data = original.data.copy()
                target.camera = obj
            if exploded:
                if group.name.startswith("L1"):
                    obj.location.z += 75
                if group.name.startswith("L2"):
                    obj.location.z += 165
                if group.name in ("L1 carrier A", "L2 carrier DPS"):
                    obj.location.y -= 45
                if "removable retainer" in original.name:
                    obj.location.y -= 72
            if original.type == "LIGHT" and exploded:
                obj.location.z += 140
    focal = Vector((0, -10, 175 if exploded else 105))
    target.camera.location = (350, -530, 440 if exploded else 360)
    target.camera.rotation_euler = (focal - target.camera.location).to_track_quat("-Z", "Y").to_euler()
    target.camera.data.ortho_scale = 475 if exploded else 365
    target["inspection_only"] = True
    target["description"] = "Exploded level layout; offsets are illustrative, not assembly dimensions" if exploded else "Assembled internals with shell panels omitted"
    created.append(target.name)

mesh_results = []
for obj in source.objects:
    if not obj.get("printable_concept"):
        continue
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    volume = abs(mesh.calc_volume(signed=True))
    manifold = all(edge.is_manifold for edge in mesh.edges)
    mesh_results.append({"name": obj.name, "dimensions_mm": [round(value, 3) for value in obj.dimensions], "volume_cm3": round(volume / 1000, 3), "closed_manifold": manifold})
    mesh.free()
result = {"created_scenes": created, "meshes_checked": len(mesh_results), "non_manifold": [entry["name"] for entry in mesh_results if not entry["closed_manifold"]]}
(ROOT / "mesh-check.json").write_text(json.dumps({"summary": result, "parts": mesh_results}, indent=2), encoding="utf-8")
lines = ["# Concept Part Report", "", "Status: layout study, NOT released for manufacturing.", "", "Assembly: 220 x 220 x 216 mm. Units: mm; Blender scale_length = 0.001.", "", "Carrier plates: 2 mm; grooves: 2.4 mm; nominal vertical play: 0.4 mm.", "", "Every modelled part fits a 226 mm bounding cube. This is not a slicer or bed-contact check.", "", "Original Blender Scene is preserved. BATMAN - assembly is dimensionally authoritative; BATMAN - open and BATMAN - levels are inspection scenes.", "", "## Unresolved Before Printing", "", "- C1 D12 x 22 mm and C2 6 x 4 x 7 mm are placeholders, not measured values. Confirm quantity, sizes and terminal clearance before choosing lower-level height.", "- Module envelopes are simplified; mounting heights and connectors need physical measurements.", "- Adjustable supports need final retaining clips/strap slots and fastener attachment. They are not complete holders yet.", "- Rear terminal/fuse/DS18B20 openings, OLED bracket and USB alignment remain to be measured. Rear panel is an interface blank.", "- Corner posts currently illustrate pilot holes, not final heat-set insert pockets or validated screw depths.", "- Frame print orientation, support-free geometry and >=70% bed contact are not verified. Slice and redesign joints before STL release.", "- No detailed harness routing or thermal verification. Preserve >=20 mm separation of signal and power harnesses, short ADS cables and ESP antenna clearance.", "- The capacitor buffer must remain next to LOAD terminals; the nominal placeholders do not approve long leads.", "- Rear carriers require removal of front carriers in the same lane; disconnect harnesses first.", "- Final linked per-subassembly files and STL exports are intentionally withheld pending these fit checks.", "", "## Part Geometry", "", "Volume is model geometry only, not filament consumption. Print orientation, bed contact and slicer time: TBD for all parts.", "", "| Part | Bounding box, mm | Volume, cm3 | Closed manifold |", "|---|---|---:|---|"]
for entry in mesh_results:
    dimensions = " x ".join(str(value) for value in entry["dimensions_mm"])
    lines.append(f"| {entry['name']} | {dimensions} | {entry['volume_cm3']} | {entry['closed_manifold']} |")
(ROOT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
bpy.context.window.scene = bpy.data.scenes["BATMAN - levels"]
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.region_3d.view_distance = 950
        area.spaces.active.region_3d.view_perspective = "ORTHO"
        area.spaces.active.region_3d.view_location = (0, -10, 175)
        area.spaces.active.region_3d.view_rotation = bpy.context.scene.camera.rotation_euler.to_quaternion()
        area.spaces.active.overlay.show_floor = False
        area.spaces.active.overlay.show_axis_x = False
        area.spaces.active.overlay.show_axis_y = False
        area.spaces.active.overlay.show_extras = False
        area.spaces.active.clip_end = 5000
        area.spaces.active.shading.color_type = "MATERIAL"
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "cad" / "assembly.blend"))