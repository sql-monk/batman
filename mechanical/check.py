"""Focused dimensional checks for the concept; not manufacturing sign-off."""

import json
from pathlib import Path


def check(root):
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    for part in data["parts"]:
        if max(part["size_mm"]) > 226.001:
            failures.append("Print envelope: " + part["name"])
    clearance = data["groove_height_mm"] - data["carrier_thickness_mm"]
    if not 0.3 <= clearance <= 0.6:
        failures.append("Vertical sliding clearance")
    for slide in data["slides"]:
        if abs(slide["center_x"]) + slide["width"] / 2 > 95:
            failures.append("Withdrawal past front posts: " + slide["name"])
        if slide["min_y"] < -103 or slide["max_y"] > 103:
            failures.append("End stop interference: " + slide["name"])
        for other in data["slides"]:
            if other["name"] <= slide["name"]:
                continue
            if (slide["lane"], slide["level"]) != (other["lane"], other["level"]):
                continue
            gap = max(slide["min_y"], other["min_y"]) - min(slide["max_y"], other["max_y"])
            if gap < 3 - 1e-6:
                failures.append("Carrier spacing: " + slide["name"] + " / " + other["name"])
    for envelope in data["envelopes"]:
        center = envelope["center_mm"]
        size = envelope["size_mm"]
        if any(abs(center[axis]) + size[axis] / 2 > 107 for axis in (0, 1)):
            failures.append("Wall envelope: " + envelope["name"])
        if center[2] + size[2] / 2 > 198:
            failures.append("Top air clearance: " + envelope["name"])
        if envelope["name"].startswith("PCB "):
            inner_post = abs(center[0]) - (size[0] - 7) / 2
            outer_post = abs(center[0]) + (size[0] - 7) / 2
            if inner_post - 4 < 4 or outer_post + 4 > 93:
                failures.append("PCB standoff versus upper rail lip: " + envelope["name"])
    result = {
        "status": "PASS" if not failures else "FAIL",
        "parts_checked": len(data["parts"]),
        "carriers_checked": len(data["slides"]),
        "vertical_slide_clearance_mm": round(clearance, 3),
        "failures": failures,
        "not_checked": ["mesh intersections", "rail fastening", "clip retention", "actual connector and harness fit", "print bed contact", "thermal performance"],
    }
    (root / "check-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = check(Path(__file__).resolve().parent)
    print(json.dumps(result, indent=2))
    if result["failures"]:
        raise SystemExit(1)