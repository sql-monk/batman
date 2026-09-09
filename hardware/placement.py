from pathlib import Path
import json
import math
import random

import numpy as np

from circuit import circuit
from pcb import create_part, new_board, position


LAYOUT = Path(__file__).with_name("placement.json")


def optimize():
    parts = [part for part in circuit() if part.board]
    board = new_board(sorted({net or f"unconnected-({part.ref}-{name}-Pad{number})"
                             for part in parts for number, name, net, _ in part.pins}))
    offsets, sizes, net_codes, bodies = [], [], [], []
    for part in parts:
        footprint = create_part(board, part)
        origin = np.array(position(footprint))
        pads = list(footprint.Pads())
        offsets.append(np.array([np.array(position(pad)) - origin for pad in pads]))
        sizes.append(np.array([[pad.GetSize().x / 2e6, pad.GetSize().y / 2e6] for pad in pads]))
        net_codes.extend([pad.GetNetCode() if not pad.GetNetname().startswith("unconnected-") else 0 for pad in pads])
        lower = offsets[-1].min(axis=0) - 1.5
        upper = offsets[-1].max(axis=0) + 1.5
        if part.kind == "C":
            lower, upper = np.array([-4, -3]), np.array([4, 3])
        if part.kind == "terminal":
            lower[1], upper[1] = -4, 4
        if part.ref == "J1":
            lower, upper = np.array([-2, -10]), np.array([28, 49])
        if part.ref == "J2":
            lower, upper = np.array([-2, -17]), np.array([26, 2])
        bodies.append(np.array([lower, upper]))
    net_codes = np.array(net_codes)
    slices = []
    count = 0
    for pads in offsets:
        slices.append(slice(count, count + len(pads)))
        count += len(pads)
    locations = np.array([part.position for part in parts], dtype=float)
    angles = np.zeros(len(parts), dtype=int)
    by_ref = {part.ref: index for index, part in enumerate(parts)}
    if LAYOUT.exists():
        previous_layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
        for index, part in enumerate(parts):
            locations[index] = previous_layout[part.ref]["position"]
            angles[index] = -previous_layout[part.ref]["rotation"] // 90
    for ref, xy in {"J1": (38, 24), "J2": (8, 20), "X3": (8, 74), "NT1": (8, 74)}.items():
        locations[by_ref[ref]] = xy
    fixed = {by_ref[ref] for ref in ["J1", "J2", "X3", "NT1"]}
    movable = [index for index in range(len(parts)) if index not in fixed]
    positions = np.zeros((count, 2))
    radii = np.zeros((count, 2))
    bounds = np.zeros((len(parts), 2, 2))

    def update(index):
        angle = angles[index] * math.pi / 2
        rotation = np.round([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        positions[slices[index]] = offsets[index] @ rotation.T + locations[index]
        radii[slices[index]] = sizes[index] @ np.abs(rotation.T)
        corners = bodies[index] @ rotation.T + locations[index]
        bounds[index] = corners.min(axis=0), corners.max(axis=0)

    for index in range(len(parts)):
        update(index)
    net_members = {net: np.where(net_codes == net)[0] for net in set(net_codes) if net}
    relevant = [{net for net in net_codes[subset] if net} for subset in slices]
    owners = np.concatenate([np.full(len(offset), index) for index, offset in enumerate(offsets)])
    top_side = np.array([part.kind not in ["R", "net_tie"] for part in parts])
    holes = np.array([(3.5, 3.5), (96.5, 3.5), (3.5, 76.5), (96.5, 76.5)])

    def cost(index):
        subset = slices[index]
        points = positions[subset]
        half_sizes = radii[subset]
        distance = np.abs(points[:, None, :] - positions[None, :, :]) - half_sizes[:, None, :] - radii[None, :, :] - 0.7
        overlaps = np.minimum(-distance[:, :, 0], -distance[:, :, 1])
        foreign = owners != index
        pad_penalty = np.maximum(overlaps[:, foreign], 0).sum() * 400
        edge_penalty = (np.maximum(2 - points + half_sizes, 0).sum() + np.maximum(points + half_sizes - [98, 78], 0).sum()) * 400
        hole_distance = np.linalg.norm(points[:, None, :] - holes[None, :, :], axis=2)
        hole_penalty = np.maximum(3.8 - hole_distance, 0).sum() * 400
        antenna_lower, antenna_upper = np.array([34, 10]), np.array([67.8, 22])
        overlap = np.minimum(points + half_sizes - antenna_lower, antenna_upper - points + half_sizes)
        antenna_penalty = np.maximum(np.minimum(overlap[:, 0], overlap[:, 1]), 0).sum() * 500
        lower, upper = bounds[index]
        body_penalty = 0
        if top_side[index]:
            overlap = np.minimum(upper - bounds[:, 0] + 0.5, bounds[:, 1] - lower + 0.5)
            hits = np.maximum(np.minimum(overlap[:, 0], overlap[:, 1]), 0)
            hits[index] = 0
            body_penalty = hits[top_side].sum() * 200
        wiring = 0
        for net in relevant[index]:
            members = positions[net_members[net]]
            if len(members) < 2:
                continue
            extent = np.ptp(members, axis=0).sum()
            distances = np.abs(members[:, None, :] - members[None, :, :]).sum(axis=2)
            np.fill_diagonal(distances, 10000)
            weight = 0.2 if len(members) > 15 else 0.5 if len(members) > 6 else 1
            wiring += weight * (extent + distances.min(axis=1).sum())
        edge_bias = 0
        if parts[index].kind in ["header", "header_h", "terminal"] and parts[index].ref != "J2":
            edge_bias = min(lower[0], lower[1], 100 - upper[0], 80 - upper[1]) * 1.5
        functional_penalty = 0
        if parts[index].ref in ["J3", "J4", "J5", "J6", "J7", "J8", "J11", "Q1", "Q2", "Q3", "C3", "C4", "C5", "C6", "C7", "C8", "C9"]:
            functional_penalty = max(0, upper[0] - 34) * 400
        if parts[index].ref in ["J9", "J10", "J12", "X4"]:
            functional_penalty = max(0, 69 - lower[0]) * 400
        return pad_penalty + edge_penalty + hole_penalty + antenna_penalty + body_penalty + wiring + edge_bias + functional_penalty

    randomizer = random.Random(41)
    for step in range(90000):
        index = randomizer.choice(movable)
        previous = locations[index].copy(), angles[index]
        before = cost(index)
        temperature = 20 * (1 - step / 90000) ** 2 + 0.15
        if randomizer.random() < 0.12:
            angles[index] = randomizer.randrange(4)
        else:
            span = 15 if step < 40000 else 5 if step < 70000 else 1.5
            locations[index] += np.round(np.array([randomizer.uniform(-span, span), randomizer.uniform(-span, span)]) * 2) / 2
        update(index)
        after = cost(index)
        if after > before and randomizer.random() > math.exp(min(0, (before - after) / temperature)):
            locations[index], angles[index] = previous
            update(index)
        if step % 15000 == 0:
            print(f"Placement step {step}: cost {sum(cost(item) for item in movable):.1f}", flush=True)
    result = {part.ref: {"position": locations[index].tolist(), "rotation": int(-angles[index] * 90)}
              for index, part in enumerate(parts)}
    LAYOUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {LAYOUT}", flush=True)


if __name__ == "__main__":
    optimize()