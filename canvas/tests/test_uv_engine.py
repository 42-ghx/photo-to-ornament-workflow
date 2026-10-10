"""Behavior checks for existing UV extraction and guided local compositing."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

from canvas.uv_engine import extract_obj_uv, generate_pattern, uv_extract


class UVEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def obj(self, contents):
        path = self.root / "model.obj"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_polygon_negative_indices_and_v_orientation(self):
        model = self.obj("""
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 .0
vt .5 .0
vt .5 .5
vt 0 .5
f -4/-4 -3/-3 -2/-2 -1/-1
v 2 2 0
vt 1 1
""")
        report = uv_extract(model, self.root / "result", {"resolution": 256})
        mask = np.asarray(Image.open(self.root / "result/mask.png"))
        self.assertEqual(mask[200, 30], 255)
        self.assertEqual(mask[30, 30], 0)
        self.assertEqual(mask[200, 200], 0)
        self.assertEqual(report["counts"]["faces"], 1)
        self.assertEqual(report["counts"]["vertices"], 5)

    def test_missing_corner_uv_and_invalid_indices_fail(self):
        prefix = "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        for body in ("f 1 2 3", "vt 0 0\nf 1/1 2//1 3/1",
                     "vt 0 0\nf 1/1 2/2 3/1", "vt 0 0\nf 1/1 2/1 4/1",
                     "vt 0 0\nf 0/1 2/1 3/1"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                extract_obj_uv(self.obj(prefix + body), self.root / "invalid", 256)
        self.assertFalse((self.root / "invalid/mask.png").exists())

    def test_out_of_tile_uv_is_clipped_not_rescaled(self):
        model = self.obj("""
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt -.25 .25
vt .25 .25
vt .25 .75
vt -.25 .75
f 1/1 2/2 3/3 4/4
""")
        report = extract_obj_uv(model, self.root / "result", 256)
        mask = np.asarray(Image.open(self.root / "result/mask.png"))
        self.assertEqual(report["counts"]["uv_coordinates_outside_unit_tile"], 2)
        self.assertTrue(report["warnings"])
        self.assertLess(np.flatnonzero(mask.any(axis=0)).max(), 65)
        self.assertEqual(mask[128, 20], 255)
        self.assertEqual(mask[20, 20], 0)

    def test_uv_seams_preserve_per_corner_indices(self):
        model = self.obj("""
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt .0 .0
vt .4 .0
vt .4 .4
vt .6 .6
vt 1 1
vt .6 1
f 1/1 2/2 3/3
f 1/4 3/5 4/6
""")
        report = extract_obj_uv(model, self.root / "result", 256)
        self.assertEqual(report["counts"]["seam_edges"], 1)
        self.assertEqual(report["counts"]["uv_islands"], 2)

    def test_real_uploaded_cylinderpipe_uv(self):
        package_root = Path(__file__).resolve().parents[2]
        packaged_model = package_root / "runs/canvas-studio/uploads/CylinderPipe.obj"
        attachments = Path("/workspace/attachments")
        candidates = ([packaged_model] if packaged_model.is_file() else [])
        if attachments.exists():
            candidates.extend(sorted(attachments.glob("*/CylinderPipe.obj")))
        if not candidates:
            self.skipTest("CylinderPipe.obj is absent from both the package uploads and attachments")
        source = candidates[0]
        original = source.read_bytes()
        report = extract_obj_uv(source, self.root / "cylinder", 256)
        self.assertEqual(report["counts"]["vertices"], 145)
        self.assertEqual(report["counts"]["uv_coordinates"], 145)
        self.assertEqual(report["counts"]["faces"], 120)
        self.assertEqual(report["counts"]["uv_coordinates_outside_unit_tile"], 0)
        self.assertGreater(report["mask_coverage"], .48)
        self.assertLess(report["mask_coverage"], .54)
        self.assertEqual(source.read_bytes(), original)
        motif, guide = self.pattern_inputs()
        mask_path = self.root / "cylinder/mask.png"
        allowed = np.asarray(Image.open(mask_path)) >= 128
        for background in ("white", "transparent"):
            output = self.root / ("cylinder-pattern-" + background)
            pattern_report = generate_pattern(motif, mask_path, guide, output, {
                "resolution": 256, "density": 5, "local_density": 3,
                "background": background, "seed": 204,
            })
            pixels = np.asarray(Image.open(output / "pattern.png"))
            self.assertFalse(pixels[~allowed].any())
            self.assertTrue(pixels[:, :, 3][allowed].any())
            self.assertEqual(pattern_report["metrics"]["output_pixels_outside_mask"], 0)
            self.assertEqual(pattern_report["metrics"]["valid_mask_pixels"], int(allowed.sum()))

    def pattern_inputs(self):
        motif = Image.new("RGBA", (40, 40), (23, 45, 87, 255))
        ImageDraw.Draw(motif).rectangle((4, 4, 16, 32), fill=(201, 88, 47, 255))
        motif.save(self.root / "motif.png")
        guide = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(guide).rectangle((0, 0, 127, 255), fill=(255, 0, 0, 255))
        guide.save(self.root / "guide.png")
        return self.root / "motif.png", self.root / "guide.png"

    def test_strict_uv_clipping_including_holes_and_alpha(self):
        motif, guide = self.pattern_inputs()
        pixels = np.zeros((256, 256, 4), dtype=np.uint8)
        pixels[20:236, 20:236] = 255
        pixels[96:160, 96:160, :3] = 0
        pixels[20:50, 20:50, 3] = 0  # Invisible white is not valid UV area.
        mask = self.root / "mask.png"
        Image.fromarray(pixels).save(mask)
        allowed = (pixels[:, :, 0] >= 128) & (pixels[:, :, 3] >= 128)
        report = generate_pattern(motif, mask, guide, self.root / "pattern", {
            "resolution": 256, "density": 4, "local_density": 2,
            "background": "white", "jitter": 0, "scale": 1,
        })
        result = np.asarray(Image.open(self.root / "pattern/pattern.png"))
        self.assertFalse(result[~allowed].any())
        self.assertTrue((result[:, :, 3][allowed] == 255).all())
        self.assertEqual(report["metrics"]["output_pixels_outside_mask"], 0)

    def test_red_guide_actually_increases_local_repeat_count(self):
        motif, guide = self.pattern_inputs()
        report = generate_pattern(motif, None, guide, self.root / "pattern", {
            "resolution": 256, "density": 4, "local_density": 2,
            "jitter": 0, "scale": 1,
        })
        # Equal-area halves have 8 large placements vs. 32 smaller placements.
        self.assertEqual(report["metrics"]["base_placements"], 8)
        self.assertEqual(report["metrics"]["local_placements"], 32)
        self.assertEqual(report["metrics"]["guide_pixels"], 256 * 128)

    def test_seed_determinism_and_sources_preserved(self):
        motif, guide = self.pattern_inputs()
        original = {path: path.read_bytes() for path in (motif, guide)}
        params = {"resolution": 256, "density": 4, "local_density": 3,
                  "seed": 21, "rotation": 25}
        progress = []
        reports = [generate_pattern(motif, None, guide, self.root / f"result{i}", params,
                                    lambda p, m: progress.append((p, m))) for i in range(2)]
        first = (self.root / "result0/pattern.png").read_bytes()
        self.assertEqual(first, (self.root / "result1/pattern.png").read_bytes())
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(progress[-1][0], 100)
        generate_pattern(motif, None, guide, self.root / "different", dict(params, seed=22))
        self.assertNotEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(
            (self.root / "different/pattern.png").read_bytes()).hexdigest())
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)

    def test_density_neutral_guide_and_global_density(self):
        motif, guide = self.pattern_inputs()
        params = {"resolution": 256, "density": 3, "local_density": 1}
        base = generate_pattern(motif, None, None, self.root / "base", params)
        generate_pattern(motif, None, guide, self.root / "guided", params)
        self.assertEqual((self.root / "base/pattern.png").read_bytes(),
                         (self.root / "guided/pattern.png").read_bytes())
        denser = generate_pattern(motif, None, None, self.root / "dense", dict(params, density=6))
        self.assertGreater(denser["metrics"]["total_placements"], base["metrics"]["total_placements"])

    def test_non_square_motif_preserves_aspect_and_guide_uses_normalized_extent(self):
        motif = self.root / "wide.png"
        Image.new("RGBA", (80, 20), (20, 40, 60, 255)).save(motif)
        params = {"resolution": 256, "density": 1, "local_density": 2,
                  "scale": .5, "jitter": 0, "background": "transparent"}
        generate_pattern(motif, None, None, self.root / "aspect", params)
        output = Image.open(self.root / "aspect/pattern.png")
        x0, y0, x1, y1 = output.getchannel("A").getbbox()
        self.assertEqual((x1 - x0, y1 - y0), (128, 32))
        # A rectangular guide still paints exactly the normalized left half.
        guide = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
        ImageDraw.Draw(guide).rectangle((0, 0, 199, 99), fill=(255, 0, 0, 255))
        guide.save(self.root / "wide-guide.png")
        report = generate_pattern(motif, None, self.root / "wide-guide.png", self.root / "wide-guided",
                                  dict(params, density=4, scale=.8))
        self.assertEqual(report["source_guide_size"], [400, 100])
        self.assertGreater(report["metrics"]["local_placements"], report["metrics"]["base_placements"])

    def test_generator_refuses_to_overwrite_its_input(self):
        input_path = self.root / "pattern.png"
        Image.new("RGBA", (16, 16), (50, 60, 70, 255)).save(input_path)
        original = input_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            generate_pattern(input_path, None, None, self.root, {"resolution": 256})
        self.assertEqual(input_path.read_bytes(), original)

    def test_invalid_and_empty_mask_fail_before_outputs(self):
        motif, _ = self.pattern_inputs()
        for params in ({"density": 0}, {"local_density": 5}, {"resolution": 4096},
                       {"background": "black"}, {"rotation": float("nan")}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                generate_pattern(motif, None, None, self.root / "invalid", params)
        Image.new("L", (256, 256), 0).save(self.root / "empty.png")
        with self.assertRaisesRegex(ValueError, "no visible white area"):
            generate_pattern(motif, self.root / "empty.png", None, self.root / "invalid", {})
        self.assertFalse((self.root / "invalid/pattern.png").exists())


if __name__ == "__main__":
    unittest.main()
