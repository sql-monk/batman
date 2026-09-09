from pathlib import Path
import json
import math

import pymupdf


ROOT = Path(__file__).resolve().parent / "batman"
OUTPUT = ROOT / "output"
PREVIEWS = ROOT / "reports" / "previews"
LAYOUT = json.loads(Path(__file__).with_name("modular-layout.json").read_text(encoding="utf-8"))


def main():
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    summary = {}
    schematic = pymupdf.open(OUTPUT / "schematic.pdf")
    assert len(schematic) == 7
    for index, page in enumerate(schematic):
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        pixmap.save(PREVIEWS / f"schematic-{index + 1}.png")
        assert len(page.get_drawings()) > 10
    summary["schematic_pages"] = len(schematic)
    views = ["copper-mirrored", "copper-top-view", "assembly", "wiring", "component-labels"]
    targets = [(name, [settings["size"] for settings in LAYOUT.values()]) for name in views]
    targets += [(key + "/" + name, [settings["size"]]) for key, settings in LAYOUT.items() for name in views[:-1]]
    for name, sizes in targets:
        document = pymupdf.open(OUTPUT / (name + ".pdf"))
        assert len(document) == 1
        page = document[0]
        drawings = page.get_drawings()
        lengths = []
        bounds = pymupdf.Rect()
        for drawing in drawings:
            bounds |= drawing["rect"]
            for item in drawing["items"]:
                if item[0] == "l":
                    lengths.append(math.dist(item[1], item[2]) * 25.4 / 72)
        assert all(sum(abs(length - target) < 0.1 for length in lengths) >= 2 for size in sizes for target in size), (name, lengths)
        bounds = pymupdf.Rect(bounds.x0 - 8, bounds.y0 - 8, bounds.x1 + 8, bounds.y1 + 8) & page.rect
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=bounds, alpha=False)
        pixmap.save(PREVIEWS / (name.replace("/", "-") + ".png"))
        summary[name] = {"scale": "1:1", "outlines_mm": sizes, "drawing_count": len(drawings)}
    drill = pymupdf.open(OUTPUT / "drill" / "batman-drl_map.pdf")
    assert len(drill) >= 1
    drill[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(PREVIEWS / "drill-map.png")
    (ROOT / "reports" / "pdf-validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()