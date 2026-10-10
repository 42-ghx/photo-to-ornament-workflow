"""Regression checks for authored 16-bit heights and legacy map sampling."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/build_quad_uv.py'
spec = importlib.util.spec_from_file_location('height_sampling', SCRIPT)
sampling = importlib.util.module_from_spec(spec)
missing_geometry = None
try:
    spec.loader.exec_module(sampling)
except ModuleNotFoundError as error:
    missing_geometry = error.name


@unittest.skipIf(missing_geometry, f'Optional geometry dependency unavailable: {missing_geometry}; see references/workbench.md')
class HeightSamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def read_png(self, data):
        path = self.folder / 'height.png'
        Image.fromarray(data).save(path)
        before = path.read_bytes()
        result = sampling.helper.gray(path)
        self.assertEqual(path.read_bytes(), before)
        return result

    def test_dark_16bit_map_uses_encoded_range(self):
        source = np.array([[0, 1, 127], [128, 254, 255]], dtype=np.uint16)
        result = self.read_png(source)
        np.testing.assert_array_equal(result, source.astype(np.float32) / 65535)
        self.assertLess(result.max(), .004)

    def test_full_range_16bit_map_keeps_fine_values(self):
        source = np.array([[0, 1, 32768], [32769, 65534, 65535]], dtype=np.uint16)
        result = self.read_png(source)
        np.testing.assert_array_equal(result, source.astype(np.float32) / 65535)
        self.assertGreater(result[1, 0], result[0, 2])

    def test_8bit_gray_and_rgb_match_legacy_values(self):
        gray = np.array([[0, 35, 128], [170, 230, 255]], dtype=np.uint8)
        np.testing.assert_array_equal(self.read_png(gray), gray.astype(np.float32) / 255)
        rgb = np.stack([gray, np.fliplr(gray), 255-gray], axis=-1)
        np.testing.assert_array_equal(self.read_png(rgb), rgb.astype(np.float32).mean(axis=2) / 255)

    def test_linear_keeps_dark_points_and_continuous_detail(self):
        height = np.array([[0, .001, .05], [.1, .35, .601234]], dtype=np.float32)
        material = np.ones(height.shape, dtype=bool)
        result, repaired = sampling.prepare_height_field(height, material, 'linear', 5, 2)
        np.testing.assert_array_equal(result, height)
        self.assertFalse(repaired.any())
        self.assertFalse(np.shares_memory(result, height))

    def test_legacy_default_repair_and_mapping_are_retained(self):
        height = np.array([[.05, .5, .75], [.14, .5, .97]], dtype=np.float32)
        field, repaired = sampling.prepare_height_field(height, np.ones(height.shape, bool), median_size=1, height_sigma=0)
        self.assertTrue(repaired[0, 0])
        self.assertEqual(int(repaired.sum()), 1)
        self.assertAlmostEqual(float(field[0, 0]), float(field[0, 1]), places=7)
        self.assertEqual(float(field[1, 0]), 0)
        self.assertEqual(float(field[1, 2]), 1)
        self.assertAlmostEqual(float(field[0, 1]), .4337924339, places=6)

    def test_linear_contours_keep_small_components_at_small_scale(self):
        mask = np.zeros((64, 64), dtype=np.float32)
        mask[8:28, 8:28] = 1
        mask[40:42, 40:43] = 1
        parts, _, _ = sampling.helper.polygons_from_mask(mask, .01, preserve_pixels=True)
        self.assertEqual(len(parts), 2)
        self.assertGreater(min(part.area for part in parts), 0)

    def test_real_mesh_keeps_two_height_levels_and_small_component(self):
        maps = self.folder / 'maps'
        maps.mkdir()
        mask = np.zeros((64, 64), dtype=np.uint8)
        mask[8:28, 8:28] = 255
        mask[40:43, 40:43] = 255
        height = np.zeros((64, 64), dtype=np.uint16)
        height[8:28, 8:28] = round(.6 * 65535)
        height[40:43, 40:43] = round(.1 * 65535)
        Image.fromarray(mask).save(maps / '03_material_mask.png')
        Image.fromarray(height).save(maps / '04_height.png')
        original = {p.name: p.read_bytes() for p in maps.iterdir()}
        out = self.folder / 'mesh'
        run = subprocess.run([sys.executable, str(SCRIPT), '--maps', str(maps), '--out', str(out),
                              '--height-encoding', 'linear', '--min-component-px', '1',
                              '--width-m', '.03', '--base-m', '.001', '--relief-m', '.002',
                              '--area', '0.0000002', '--wall-layers', '2'], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        checks = json.loads((out / 'mesh_checks.json').read_text())
        self.assertEqual(checks['material_components'], 2)
        self.assertTrue(checks['watertight'])
        self.assertFalse(checks['height_peak_normalized'])
        self.assertEqual(checks['height_sampling_repaired_pixels'], 0)
        self.assertEqual(checks['contour_shoulder_width_m'], 0)
        with np.load(out / 'ding_quad_uv.npz') as data:
            peaks = []
            for component in (0, 1):
                faces = (data['face_kind'] == 0) & (data['face_component'] == component)
                peaks.append(float(data['vertices'][np.unique(data['quads'][faces]), 2].max()))
        expected = sorted([.001 + .002 * round(.6 * 65535) / 65535,
                           .001 + .002 * round(.1 * 65535) / 65535])
        np.testing.assert_allclose(sorted(peaks), expected, atol=1e-7)
        self.assertEqual({p.name: p.read_bytes() for p in maps.iterdir()}, original)


if __name__ == '__main__':
    unittest.main()
