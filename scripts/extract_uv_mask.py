"""Rasterize an OBJ's existing UV coordinates into new PNG artifacts.

This module never unwraps a model, edits the source image, or invokes an image
model. All outputs are new files beneath the caller-supplied output directory.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import argparse
import sys

import numpy as np
from PIL import Image, ImageDraw


def _resolution(value: object) -> int:
    if isinstance(value, bool) or str(value) != str(int(value)):
        raise ValueError("resolution must be an integer")
    result = int(value)
    if not 256 <= result <= 2048:
        raise ValueError("resolution must be between 256 and 2048")
    return result


def _write_report(out_dir: Path, report: dict) -> dict:
    with (out_dir / "report.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def _empty_output_directory(out_dir: Path) -> None:
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ValueError("output must be a new or empty directory; existing artifacts are never overwritten")
    if out_dir.is_symlink() and not out_dir.exists():
        raise ValueError("output must not be a dangling symbolic link")


def _clip_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Clip in UV space before drawing, keeping raster coordinates bounded."""
    for axis, boundary, greater in ((0, 0.0, True), (0, 1.0, False),
                                     (1, 0.0, True), (1, 1.0, False)):
        if not points:
            break
        clipped = []
        for start, end in zip(points, points[1:] + points[:1]):
            start_in = start[axis] >= boundary if greater else start[axis] <= boundary
            end_in = end[axis] >= boundary if greater else end[axis] <= boundary
            if start_in:
                clipped.append(start)
            if start_in != end_in:
                ratio = (boundary - start[axis]) / (end[axis] - start[axis])
                crossing = [start[i] + ratio * (end[i] - start[i]) for i in range(2)]
                crossing[axis] = boundary
                clipped.append(tuple(crossing))
        points = clipped
    return points


def extract_obj_uv(model_path: Path, out_dir: Path, resolution: int = 1024) -> dict:
    """Rasterize the OBJ's existing face-corner UV coordinates in the 0–1 tile.

    OBJ V is flipped for image coordinates. Out-of-tile UVs are clipped, never
    rescaled or wrapped. Missing/invalid corner UVs are errors, not auto unwraps.
    Supports polygons and both absolute and relative OBJ corner indices.
    """
    model_path, out_dir = Path(model_path), Path(out_dir)
    resolution = _resolution(resolution)
    _empty_output_directory(out_dir)
    if model_path.suffix.lower() != ".obj":
        raise ValueError("UV extraction currently supports OBJ models only")
    if not model_path.is_file():
        raise ValueError("OBJ input does not exist or is not a regular file")
    if model_path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("OBJ exceeds the 64 MiB UV extraction limit")
    vertices: list[tuple[float, ...]] = []
    texcoords: list[tuple[float, float]] = []
    normals = 0
    raw_faces: list[tuple[int, list[str], int, int, int]] = []
    with model_path.open(encoding="utf-8-sig", errors="strict") as source:
        for line_number, line in enumerate(source, 1):
            values = line.partition("#")[0].split()
            if not values:
                continue
            kind, coordinates = values[0], values[1:]
            try:
                if kind in {"v", "vt", "vn"}:
                    required = 2 if kind == "vt" else 3
                    if len(coordinates) < required:
                        raise ValueError(f"{kind} needs at least {required} coordinates")
                    numbers = tuple(float(x) for x in coordinates)
                    if not all(math.isfinite(x) for x in numbers):
                        raise ValueError("coordinates must be finite")
                    if kind == "v":
                        vertices.append(numbers[:3])
                    elif kind == "vt":
                        if any(abs(x) > 1e9 for x in numbers[:2]):
                            raise ValueError("UV coordinate magnitude must not exceed 1e9")
                        texcoords.append(numbers[:2])
                    else:
                        normals += 1
                elif kind == "f":
                    if len(coordinates) < 3:
                        raise ValueError("a face needs at least three corners")
                    raw_faces.append(
                        (line_number, coordinates, len(vertices), len(texcoords), normals)
                    )
            except ValueError as error:
                raise ValueError(f"OBJ line {line_number}: {error}") from error
    if not vertices or not raw_faces:
        raise ValueError("OBJ contains no mesh faces")
    if not texcoords:
        raise ValueError("OBJ has no UV coordinates (vt); export the model with UVs")

    def resolve(raw: str, final_count: int, current_count: int, label: str) -> int:
        number = int(raw)
        index = number - 1 if number > 0 else current_count + number
        if number == 0 or index < 0 or index >= (final_count if number > 0 else current_count):
            raise ValueError(f"{label} index {raw} is out of range")
        return index

    faces: list[list[tuple[int, int]]] = []
    edge_uses: dict[tuple[int, int], list[tuple[tuple[int, int], int]]] = {}
    for line_number, tokens, vertex_count, uv_count, normal_count in raw_faces:
        corners: list[tuple[int, int]] = []
        try:
            for token in tokens:
                pieces = token.split("/")
                if len(pieces) not in {2, 3} or not pieces[0] or not pieces[1]:
                    raise ValueError("every face corner must include an existing UV index")
                vertex = resolve(pieces[0], len(vertices), vertex_count, "vertex")
                uv = resolve(pieces[1], len(texcoords), uv_count, "UV")
                if len(pieces) == 3 and pieces[2]:
                    resolve(pieces[2], normals, normal_count, "normal")
                corners.append((vertex, uv))
            if len({v for v, _ in corners}) < 3:
                raise ValueError("face contains fewer than three distinct vertices")
        except ValueError as error:
            raise ValueError(f"OBJ line {line_number}: {error}") from error
        face_index = len(faces)
        faces.append(corners)
        for first, second in zip(corners, corners[1:] + corners[:1]):
            # Canonical vertex order preserves UV corner assignments at seams.
            ordered = (first, second) if first[0] < second[0] else (second, first)
            edge_uses.setdefault((ordered[0][0], ordered[1][0]), []).append(
                ((ordered[0][1], ordered[1][1]), face_index)
            )

    mask = Image.new("L", (resolution, resolution), 0)
    mask_draw = ImageDraw.Draw(mask)
    layout = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    layout_draw = ImageDraw.Draw(layout)
    degenerate_faces = 0
    clipped_faces = []
    for corners in faces:
        uv_points = [texcoords[uv] for _, uv in corners]
        area = abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(uv_points, uv_points[1:] + uv_points[:1]))) / 2
        if area <= 1e-14:
            degenerate_faces += 1
            continue
        uv_points = _clip_polygon(uv_points)
        if len(uv_points) < 3:
            continue
        clipped_area = abs(sum(a[0] * b[1] - b[0] * a[1]
                               for a, b in zip(uv_points, uv_points[1:] + uv_points[:1]))) / 2
        if clipped_area <= 1e-14:
            continue
        points = [(u * (resolution - 1), (1 - v) * (resolution - 1))
                  for u, v in uv_points]
        clipped_faces.append(points)
        mask_draw.polygon(points, fill=255)
        layout_draw.polygon(points, fill=(248, 250, 252, 255))
    # Draw edges after every polygon fill, so adjacent faces retain boundaries.
    for points in clipped_faces:
        layout_draw.line(points + points[:1], fill=(42, 55, 74, 255), width=1)
    valid_pixels = int(np.count_nonzero(np.asarray(mask)))
    if not valid_pixels:
        raise ValueError("OBJ has no non-degenerate UV face area inside the 0–1 tile")

    parent = list(range(len(faces)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seam_edges = 0
    for uses in edge_uses.values():
        if len(uses) > 1:
            if len({uv_edge for uv_edge, _ in uses}) > 1:
                seam_edges += 1
            by_uv: dict[tuple[int, int], int] = {}
            for uv_edge, face in uses:
                if uv_edge in by_uv:
                    parent[find(face)] = find(by_uv[uv_edge])
                else:
                    by_uv[uv_edge] = face
    coords = np.asarray(texcoords, dtype=np.float64)
    outside = int(np.count_nonzero(np.any((coords < 0) | (coords > 1), axis=1)))
    warnings = []
    if outside:
        warnings.append(f"{outside} UV coordinates lie outside 0–1; faces are clipped to tile 1001 without wrapping or rescaling")
    if degenerate_faces:
        warnings.append(f"{degenerate_faces} zero-area UV faces contribute no mask area")
    # Check again immediately before writing. Exclusive creation protects each
    # artifact if another process writes into this directory concurrently.
    _empty_output_directory(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "mask.png").open("xb") as stream:
        mask.save(stream, format="PNG")
    with (out_dir / "uv_layout.png").open("xb") as stream:
        layout.save(stream, format="PNG")
    return _write_report(out_dir, {
        "engine": "obj_uv",
        "source": model_path.name,
        "resolution": resolution,
        "artifacts": {"mask": "mask.png", "uv_layout": "uv_layout.png", "report": "report.json"},
        "counts": {"vertices": len(vertices), "uv_coordinates": len(texcoords),
                   "faces": len(faces), "uv_islands": len({find(i) for i in range(len(faces))}),
                   "seam_edges": seam_edges, "degenerate_uv_faces": degenerate_faces,
                   "uv_coordinates_outside_unit_tile": outside},
        "bounds": {"u_min": float(coords[:, 0].min()), "u_max": float(coords[:, 0].max()),
                   "v_min": float(coords[:, 1].min()), "v_max": float(coords[:, 1].max())},
        "uv_policy": "existing face-corner UVs; clip to 0–1 tile; no unwrap, wrap, or rescale; image top is V=1",
        "valid_pixels": valid_pixels,
        "mask_coverage": valid_pixels / resolution ** 2,
        "warnings": warnings,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obj", type=Path, required=True, help="OBJ model with existing face-corner UVs")
    parser.add_argument("--out", type=Path, required=True, help="New or empty output directory")
    parser.add_argument("--resolution", type=int, default=1024, help="Square output resolution, 256–2048")
    args = parser.parse_args(argv)
    try:
        report = extract_obj_uv(args.obj, args.out, args.resolution)
    except (OSError, ValueError, OverflowError, UnicodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



