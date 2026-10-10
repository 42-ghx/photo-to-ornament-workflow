"""UV extraction and explicit local motif compositing for the node canvas.

This module never unwraps a model, edits the source image, or invokes an image
model. All outputs are new files beneath the caller-supplied output directory.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw


def _resolution(value: object) -> int:
    result = int(value)
    if not 256 <= result <= 2048:
        raise ValueError("resolution must be between 256 and 2048")
    return result


def _write_report(out_dir: Path, report: dict) -> dict:
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def extract_obj_uv(model_path: Path, out_dir: Path, resolution: int = 1024) -> dict:
    """Rasterize the OBJ's existing face-corner UV coordinates in the 0–1 tile.

    OBJ V is flipped for image coordinates. Out-of-tile UVs are clipped, never
    rescaled or wrapped. Missing/invalid corner UVs are errors, not auto unwraps.
    Supports polygons and both absolute and relative OBJ corner indices.
    """
    model_path, out_dir = Path(model_path), Path(out_dir)
    resolution = _resolution(resolution)
    if model_path.suffix.lower() != ".obj":
        raise ValueError("UV extraction currently supports OBJ models only")
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
    for corners in faces:
        uv_points = [texcoords[uv] for _, uv in corners]
        area = abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(uv_points, uv_points[1:] + uv_points[:1]))) / 2
        if area <= 1e-14:
            degenerate_faces += 1
            continue
        points = [(u * (resolution - 1), (1 - v) * (resolution - 1))
                  for u, v in uv_points]
        mask_draw.polygon(points, fill=255)
        layout_draw.polygon(points, fill=(248, 250, 252, 255))
    # Draw edges after every polygon fill, so adjacent faces retain boundaries.
    for corners in faces:
        points = [(texcoords[uv][0] * (resolution - 1),
                   (1 - texcoords[uv][1]) * (resolution - 1)) for _, uv in corners]
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
    out_dir.mkdir(parents=True, exist_ok=True)
    mask.save(out_dir / "mask.png")
    layout.save(out_dir / "uv_layout.png")
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


def uv_extract(obj_path: Path, out_dir: Path, params: dict | None = None) -> dict:
    """Server adapter matching the parameter-dictionary node API."""
    return extract_obj_uv(obj_path, out_dir, (params or {}).get("resolution", 1024))


def generate_pattern(
    motif_path: Path,
    mask_path: Path | None,
    guide_path: Path | None,
    out_dir: Path,
    params: dict,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Repeat an existing motif with independently denser red-painted regions.

    This is deterministic local compositing, not an AI photo-to-map generator.
    Density is repeats per axis. Local density multiplies repeats in red guide
    regions and reduces motif size accordingly. Guide redness times alpha blends
    the normal and dense arrangements; it never changes the valid UV region.
    Only pixels whose mask luminance AND alpha are >= 128 are valid.
    Mask and guide coordinates span the entire normalized UV tile. Their full
    images are resized without cropping; UI letterboxes must not be painted into
    the exported guide. The motif itself keeps its original aspect ratio.
    """
    motif_path, out_dir = Path(motif_path), Path(out_dir)
    input_paths = {Path(path).resolve() for path in (motif_path, mask_path, guide_path) if path}
    if any((out_dir / name).resolve() in input_paths for name in ("pattern.png", "report.json")):
        raise ValueError("output directory would overwrite an input; use a new version directory")
    report_progress = progress or (lambda _percent, _message: None)
    resolution = _resolution(params.get("resolution", 1024))

    def number(name: str, default: float, low: float, high: float) -> float:
        value = float(params.get(name, default))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return value

    density = number("density", 4, 1, 12)
    local_density = number("local_density", 2, 1, 4)
    rotation = number("rotation", 0, -360, 360)
    scale = number("scale", 0.92, 0.1, 1)
    jitter = number("jitter", 0.08, 0, 0.25)
    seed = int(params.get("seed", 0))
    if not 0 <= seed <= 2 ** 32 - 1:
        raise ValueError("seed must be between 0 and 4294967295")
    background = str(params.get("background", "transparent"))
    if background not in {"white", "transparent"}:
        raise ValueError("background must be white or transparent")
    report_progress(3, "读取纹样、UV 遮罩与密度引导")
    with Image.open(motif_path) as source:
        motif = source.convert("RGBA")
    if not np.any(np.asarray(motif)[:, :, 3]):
        raise ValueError("motif contains no visible pixels")
    size = (resolution, resolution)
    allowed = np.ones((resolution, resolution), dtype=bool)
    original_mask_size = None
    if mask_path:
        with Image.open(Path(mask_path)) as source:
            original_mask_size = source.size
            resized = source.convert("RGBA").resize(size, Image.Resampling.NEAREST)
        allowed = ((np.asarray(resized.convert("L")) >= 128)
                   & (np.asarray(resized)[:, :, 3] >= 128))
    if not allowed.any():
        raise ValueError("UV mask has no visible white area (luminance and alpha must be >= 128)")
    guide = np.zeros((resolution, resolution), dtype=np.float32)
    original_guide_size = None
    if guide_path:
        with Image.open(Path(guide_path)) as source:
            original_guide_size = source.size
            resized = source.convert("RGBA").resize(size, Image.Resampling.BILINEAR)
        pixels = np.asarray(resized, dtype=np.float32) / 255.0
        guide = np.clip(pixels[:, :, 0] - np.maximum(pixels[:, :, 1], pixels[:, :, 2]), 0, 1) * pixels[:, :, 3]
    guide *= allowed
    if local_density == 1:
        # The density-neutral setting must exactly match an unpainted guide.
        guide[:] = 0
    report_progress(15, "按整体密度排布纹样")

    def render(repeats: float, influence: np.ndarray, stream: int, start: int, end: int) -> tuple[Image.Image, int]:
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        if not np.any(influence > 0):
            return layer, 0
        cell_size = resolution / repeats
        tile_limit = max(1, int(cell_size * scale))
        # Fit both large and small source motifs to their cell, preserving aspect.
        # Scaling a small input up here also lets red density visibly shrink it.
        fit = tile_limit / max(motif.size)
        tile = motif.resize((max(1, round(motif.width * fit)), max(1, round(motif.height * fit))),
                            Image.Resampling.LANCZOS)
        # Bound rotation work by the destination tile, never rotate a huge input.
        if rotation:
            tile = tile.rotate(rotation, Image.Resampling.BICUBIC, expand=True)
            tile.thumbnail((tile_limit, tile_limit), Image.Resampling.LANCZOS)
        tile_array = np.asarray(tile)
        rng = np.random.default_rng(np.random.SeedSequence([seed, stream]))
        rows = math.ceil(repeats)
        count = 0
        for row in range(rows):
            for column in range(rows):
                offset_x, offset_y = rng.uniform(-jitter, jitter, size=2)
                left = round((column + 0.5 + offset_x) * cell_size - tile.width / 2)
                top = round((row + 0.5 + offset_y) * cell_size - tile.height / 2)
                x0, y0 = max(0, left), max(0, top)
                x1, y1 = min(resolution, left + tile.width), min(resolution, top + tile.height)
                if x0 >= x1 or y0 >= y1:
                    continue
                fragment = tile_array[y0 - top:y1 - top, x0 - left:x1 - left].copy()
                alpha = fragment[:, :, 3].astype(np.float32)
                alpha *= influence[y0:y1, x0:x1]
                alpha *= allowed[y0:y1, x0:x1]
                fragment[:, :, 3] = np.rint(alpha).astype(np.uint8)
                if not np.any(fragment[:, :, 3]):
                    continue
                layer.alpha_composite(Image.fromarray(fragment), (x0, y0))
                count += 1
            report_progress(start + round((end - start) * (row + 1) / rows),
                            "排布局部加密纹样" if stream else "排布整体纹样")
        return layer, count

    base, base_count = render(density, 1 - guide, 0, 15, 45)
    dense, local_count = render(density * local_density, guide, 1, 45, 78)
    composed = Image.alpha_composite(base, dense)
    ornament_pixels = int(np.count_nonzero(np.asarray(composed)[:, :, 3]))
    report_progress(85, "裁切到白色 UV 区域并保存结果")
    if background == "white":
        backing = np.full((resolution, resolution, 4), 255, dtype=np.uint8)
        backing[:, :, 3] = allowed.astype(np.uint8) * 255
        composed = Image.alpha_composite(Image.fromarray(backing), composed)
    # Canonical fully transparent exterior: every output channel outside UV = 0.
    result = np.array(composed)
    result[~allowed] = 0
    result[result[:, :, 3] == 0] = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(result).save(out_dir / "pattern.png")
    valid_pixels = int(np.count_nonzero(allowed))
    report = _write_report(out_dir, {
        "engine": "local_pattern",
        "description": "Deterministic compositing of the supplied motif; no AI generation or photo interpretation",
        "artifacts": {"pattern": "pattern.png", "report": "report.json"},
        "sources": {"motif": motif_path.name,
                    "mask": Path(mask_path).name if mask_path else None,
                    "guide": Path(guide_path).name if guide_path else None},
        "params": {"resolution": resolution, "density": density,
                   "local_density": local_density, "seed": seed,
                   "rotation": rotation, "background": background,
                   "scale": scale, "jitter": jitter},
        "metrics": {"base_placements": base_count, "local_placements": local_count,
                    "total_placements": base_count + local_count,
                    "base_repeats_per_axis": density,
                    "local_repeats_per_axis": density * local_density,
                    "valid_mask_pixels": valid_pixels,
                    "guide_pixels": int(np.count_nonzero(guide > 0)),
                    "guide_mean_strength_in_mask": float(guide.sum() / valid_pixels),
                    "motif_pixels": ornament_pixels,
                    "motif_coverage_in_mask": ornament_pixels / valid_pixels,
                    "output_pixels_outside_mask": int(np.count_nonzero(result[~allowed]))},
        "mask_policy": "luminance >= 128 AND alpha >= 128; nearest resize; all channels zero outside mask including holes",
        "guide_policy": "redness = max(R - max(G,B), 0) × alpha; red blends in smaller motifs with higher repetition",
        "source_mask_size": list(original_mask_size) if original_mask_size else None,
        "source_guide_size": list(original_guide_size) if original_guide_size else None,
        "warnings": [],
    })
    report_progress(100, "纹样已生成")
    return report
