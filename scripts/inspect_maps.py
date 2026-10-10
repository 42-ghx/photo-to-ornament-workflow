"""Read-only numerical inspection of the four photo-to-ornament PNG stages.

Dependencies: NumPy and Pillow. PNG uint16 samples retain their full precision,
including RGB/RGBA PNGs that Pillow would otherwise reduce to eight bits.
These checks do not validate subject identity, reconstruction quality, artistic
intent, engraved details, lighting, or any other visual/semantic property.
Exit status: 0 = no structural errors (warnings may remain); 1 = errors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

import numpy as np
from PIL import Image


STAGES = {
    "stage1": ("01_cutout.png", "01_reconstructed.png"),
    "stage2": ("02_soft_delight.png",),
    "material_mask": ("03_material_mask.png",),
    "height": ("04_height.png",),
}
MAX_PIXELS = 32 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024


def _png_chunks(path: Path) -> tuple[dict, list[bytes], bytes | None]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("PNG exceeds the 256 MiB file limit")
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("input is not a PNG")
    offset, header, compressed, transparency = 8, None, [], None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if offset + 12 + length > len(data):
            raise ValueError("truncated PNG chunk data")
        checksum = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != checksum:
            raise ValueError(f"PNG checksum mismatch in {kind!r}")
        if header is None and kind != b"IHDR":
            raise ValueError("PNG must begin with an IHDR chunk")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise ValueError("invalid PNG IHDR")
            width, height, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise ValueError("PNG dimensions exceed the 32 megapixel limit or are empty")
            if compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise ValueError("unsupported PNG encoding")
            header = dict(width=width, height=height, bit_depth=bits, color_type=color, interlace=interlace)
        elif kind == b"IDAT":
            compressed.append(payload)
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"acTL":
            raise ValueError("animated PNG is not a single stage map")
        elif kind == b"IEND":
            if length != 0 or offset + 12 != len(data):
                raise ValueError("invalid PNG ending")
            if not compressed:
                raise ValueError("PNG has no image data")
            return header, compressed, transparency
        offset += length + 12
    raise ValueError("PNG has no IEND chunk")


def _unfilter(row: bytearray, previous: bytearray, bpp: int, kind: int) -> bytearray:
    if kind == 0:
        return row
    if kind == 1:
        groups = np.frombuffer(row, dtype=np.uint8).reshape(-1, bpp)
        return bytearray((np.cumsum(groups, axis=0, dtype=np.uint32) & 255).astype(np.uint8).tobytes())
    if kind == 2:
        current = np.frombuffer(row, dtype=np.uint8).astype(np.uint16)
        above = np.frombuffer(previous, dtype=np.uint8)
        return bytearray(((current + above) & 255).astype(np.uint8).tobytes())
    if kind not in (3, 4):
        raise ValueError("invalid PNG filter")
    for index in range(len(row)):
        left = row[index - bpp] if index >= bpp else 0
        above = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if kind == 3:
            predictor = (left + above) // 2
        else:
            estimate = left + above - upper_left
            a, b, c = abs(estimate - left), abs(estimate - above), abs(estimate - upper_left)
            predictor = left if a <= b and a <= c else above if b <= c else upper_left
        row[index] = (row[index] + predictor) & 255
    return row


def _decode_16bit(header: dict, chunks: list[bytes]) -> np.ndarray:
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(header["color_type"])
    if channels is None:
        raise ValueError("invalid color type for a 16-bit PNG")
    width, height = header["width"], header["height"]
    passes = [(0, 0, 1, 1)] if not header["interlace"] else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8),
        (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    ]
    pass_sizes = [(x, y, dx, dy, max(0, (width - x + dx - 1) // dx),
                   max(0, (height - y + dy - 1) // dy)) for x, y, dx, dy in passes]
    expected = sum((pw * channels * 2 + 1) * ph for _, _, _, _, pw, ph in pass_sizes if pw and ph)
    if expected > MAX_DECODED_BYTES:
        raise ValueError("16-bit PNG exceeds the 256 MiB decoded-data limit")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(b"".join(chunks), expected + 1)
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG decompressed length does not match its dimensions")
    output = np.empty((height, width, channels), dtype=np.uint16)
    offset, bpp = 0, channels * 2
    for x, y, dx, dy, pw, ph in pass_sizes:
        if not pw or not ph:
            continue
        stride = pw * bpp
        previous = bytearray(stride)
        for row_index in range(ph):
            kind = raw[offset]
            row = _unfilter(bytearray(raw[offset + 1:offset + 1 + stride]), previous, bpp, kind)
            output[y + row_index * dy, x::dx] = np.frombuffer(row, dtype=">u2").reshape(pw, channels)
            previous = row
            offset += stride + 1
    return output


def read_png(path: Path) -> dict:
    """Return unscaled color and optional alpha samples with source precision."""
    header, compressed, transparency = _png_chunks(path)
    bits, color_type = header["bit_depth"], header["color_type"]
    if bits == 16:
        array = _decode_16bit(header, compressed)
        maximum = 65535
        if color_type in (4, 6):
            colors, alpha = array[:, :, :-1], array[:, :, -1]
        else:
            colors, alpha = array, None
            if transparency is not None:
                count = colors.shape[2]
                if len(transparency) != count * 2:
                    raise ValueError("invalid PNG transparency key")
                key = np.frombuffer(transparency, dtype=">u2")
                alpha = np.where(np.all(colors == key, axis=2), 0, maximum).astype(np.uint16)
        mode = {0: "L16", 2: "RGB16", 4: "LA16", 6: "RGBA16"}[color_type]
    else:
        # Pillow safely expands low-bit-depth and palette PNGs to uint8. The
        # separate decoder above is mandatory for ALL 16-bit source modes.
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("input is not a PNG")
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            mode = image.mode
            array = np.asarray(image.convert("RGBA" if has_alpha else "RGB"), dtype=np.uint8)
        colors = array[:, :, :3]
        alpha = array[:, :, 3] if has_alpha else None
        maximum = 255
    return dict(path=str(path), width=header["width"], height=header["height"],
                source_bit_depth=bits, mode=mode, sample_dtype=str(colors.dtype),
                colors=colors, alpha=alpha, maximum=maximum)


def _statistics(values: np.ndarray, maximum: int) -> dict | None:
    if values.size == 0:
        return None
    scaled = values.astype(np.float64) / maximum
    minimum, peak = int(values.min()), int(values.max())
    return {
        "pixels": int(values.size), "raw_min": minimum, "raw_max": peak,
        "raw_range": peak - minimum, "unique_levels": int(np.unique(values).size),
        "normalized_min": minimum / maximum, "normalized_max": peak / maximum,
        "normalized_range": (peak - minimum) / maximum,
        "normalized_mean": float(scaled.mean()), "normalized_std": float(scaled.std()),
        "normalized_percentiles_1_50_99": [float(x) for x in np.percentile(scaled, [1, 50, 99])],
    }


def inspect_maps(maps_dir: Path) -> dict:
    maps_dir = Path(maps_dir)
    report = {
        "validation_scope": "Numerical file checks only; visual/semantic quality requires human inspection.",
        "thresholds": {"near_binary_tolerance": 0.02, "foreground_threshold": 0.5,
                       "near_binary_warning_fraction": 0.99, "outside_height_warning_threshold": 0.01},
        "maps": {}, "errors": [], "warnings": [],
    }
    errors, warnings, loaded = report["errors"], report["warnings"], {}
    if not maps_dir.is_dir():
        errors.append("maps path is not an existing directory")
    else:
        for stage, filenames in STAGES.items():
            candidates = [maps_dir / name for name in filenames if (maps_dir / name).exists()]
            if len(candidates) != 1:
                errors.append(f"{stage}: expected exactly one of {', '.join(filenames)}; found {len(candidates)}")
                continue
            try:
                item = read_png(candidates[0])
            except (OSError, ValueError, SyntaxError, zlib.error, Image.DecompressionBombError) as error:
                errors.append(f"{stage}: {error}")
                continue
            loaded[stage] = item
            metadata = {key: value for key, value in item.items() if key not in {"colors", "alpha", "path"}}
            metadata["file"] = candidates[0].name
            alpha = item["alpha"]
            metadata["has_alpha_or_transparency_key"] = alpha is not None
            if alpha is not None:
                metadata["alpha"] = {
                    "transparent_fraction": float(np.mean(alpha == 0)),
                    "partial_fraction": float(np.mean((alpha > 0) & (alpha < item["maximum"]))),
                    "opaque_fraction": float(np.mean(alpha == item["maximum"])),
                    "visible_fraction": float(np.mean(alpha > 0)),
                    "raw_min": int(alpha.min()), "raw_max": int(alpha.max()),
                }
            if stage in {"stage1", "stage2"}:
                if alpha is None or not np.any(alpha < item["maximum"]):
                    errors.append(f"{stage}: no actual alpha transparency; an opaque background does not pass")
                elif not np.any(alpha > 0):
                    errors.append(f"{stage}: image is fully transparent and has no visible subject")
                elif not np.any(alpha == 0):
                    warnings.append(f"{stage}: partial transparency exists but no pixel is fully transparent")
            else:
                colors = item["colors"]
                grayscale = bool(np.all(colors == colors[:, :, :1]))
                metadata["grayscale"] = grayscale
                if not grayscale:
                    errors.append(f"{stage}: color channels differ; map must be grayscale")
                else:
                    item["gray"] = colors[:, :, 0]
                    metadata["tone"] = _statistics(item["gray"], item["maximum"])
                if alpha is not None and np.any(alpha < item["maximum"]):
                    warnings.append(f"{stage}: map contains transparency; confirm downstream alpha handling")
            report["maps"][stage] = metadata
    sizes = {(item["width"], item["height"]) for item in loaded.values()}
    report["dimensions_consistent"] = len(loaded) == 4 and len(sizes) == 1
    if len(sizes) > 1:
        errors.append("map dimensions differ; maps must share the same width and height")
    mask, height = loaded.get("material_mask"), loaded.get("height")
    foreground = None
    if mask is not None and "gray" in mask:
        normalized = mask["gray"].astype(np.float64) / mask["maximum"]
        foreground = normalized >= 0.5
        if mask["alpha"] is not None:
            foreground &= mask["alpha"] >= mask["maximum"] * 0.5
        binary_fraction = float(np.mean((normalized <= 0.02) | (normalized >= 0.98)))
        report["maps"]["material_mask"].update(
            foreground_pixels=int(np.count_nonzero(foreground)), foreground_coverage=float(foreground.mean()),
            near_binary_fraction=binary_fraction,
            exactly_binary_fraction=float(np.mean((normalized == 0) | (normalized == 1))))
        if not foreground.any():
            errors.append("material_mask: no white foreground pixels")
        elif foreground.all():
            warnings.append("material_mask: foreground covers the entire image; no background remains")
        if binary_fraction < 0.99:
            warnings.append("material_mask: more than 1% of pixels are between near-black and near-white")
    if height is not None and "gray" in height:
        gray, maximum = height["gray"], height["maximum"]
        if foreground is not None and gray.shape == foreground.shape:
            inside, outside = gray[foreground], gray[~foreground]
            metrics = report["maps"]["height"]
            metrics["inside_material_mask"] = _statistics(inside, maximum)
            metrics["outside_material_mask"] = _statistics(outside, maximum)
            metrics["outside_nonzero_fraction"] = float(np.mean(outside > 0)) if outside.size else None
            metrics["outside_above_1percent_fraction"] = float(np.mean(outside > maximum * 0.01)) if outside.size else None
            if inside.size and int(inside.max()) == int(inside.min()):
                warnings.append("height: foreground has no tonal variation")
            elif inside.size and int(inside.max()) - int(inside.min()) < maximum * 0.02:
                warnings.append("height: foreground uses less than 2% of the available tonal range")
            if outside.size and np.any(outside > maximum * 0.01):
                warnings.append("height: non-black heights occur outside the material mask")
        else:
            warnings.append("height: inside/outside statistics unavailable without a matching grayscale material mask")
    report["ok"] = not errors
    return report


def _check_report_destination(path: Path, maps_dir: Path) -> None:
    # lexists behavior also protects dangling symbolic links. Resolving the
    # path detects an alias of a missing expected input name, too.
    input_paths = {(maps_dir / name).resolve() for names in STAGES.values() for name in names}
    if path.resolve() in input_paths:
        raise ValueError("report path must not alias a stage input")
    if path.exists() or path.is_symlink():
        raise ValueError("report path already exists; choose a new file")
    if not path.parent.is_dir():
        raise ValueError("report parent directory must already exist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", required=True, type=Path, help="Directory containing the four named stage PNGs")
    parser.add_argument("--report", type=Path, help="Optional new JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.report:
            _check_report_destination(args.report, args.maps)
        report = inspect_maps(args.maps)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        print(serialized, end="")
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
