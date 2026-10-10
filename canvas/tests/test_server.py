"""Real HTTP integration checks; run with python -m unittest discover -s canvas/tests."""
import base64
import copy
import errno
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import BadRequest, Cancelled, Studio, make_server


class ShippedWorkflowTests(unittest.TestCase):
    def test_default_photo_workflow_has_four_stages_and_resolvable_assets(self):
        root = Path(__file__).resolve().parents[2]
        project = json.loads((root / "canvas/studio.json").read_text("utf-8"))
        nodes = project["nodes"]
        self.assertEqual(len(nodes), 5)
        self.assertEqual(sum(node["type"] == "source" for node in nodes), 1)
        self.assertEqual(sum(node["type"] == "image_generate" for node in nodes), 4)
        studio = Studio.__new__(Studio)
        studio.root = root
        studio.validate_project(project)
        for node in nodes:
            studio.validate_graph(project, node["id"])
            for slot in node.get("inputs", {}):
                self.assertTrue(studio.resolve(project, node, slot).is_file())
            for key in ("source", "preview"):
                if node.get(key):
                    self.assertTrue(studio.asset(node[key]).is_file())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "canvas").mkdir()
        (self.root / "canvas/index.html").write_text("<title>Studio</title>")
        (self.root / "cases").mkdir()
        image = Image.new("RGBA", (64, 64), "white")
        ImageDraw.Draw(image).ellipse((10, 10, 54, 54), fill="black")
        image.save(self.root / "cases/motif.png")
        mask = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(mask).rectangle((8, 8, 55, 55), fill=255)
        mask.save(self.root / "cases/mask.png")
        (self.root / "cases/model.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0.1 0.1\nvt .9 .1\nvt .1 .9\nf 1/1 2/2 3/3\n")
        self.project = {"version": 1, "nodes": [
            {"id": "motif", "type": "source", "title": "Motif", "source": "cases/motif.png", "params": {}, "inputs": {}},
            {"id": "mask", "type": "uv_mask", "source": "cases/mask.png", "params": {}, "inputs": {}},
            {"id": "guide", "type": "density_guide", "params": {}, "inputs": {"image": "motif"}},
            {"id": "uv", "type": "uv_extract", "source": "cases/model.obj", "params": {"resolution": 256}, "inputs": {}},
            {"id": "pattern", "type": "pattern", "params": {"resolution": 256, "density": 4},
             "inputs": {"image": "motif", "mask": "mask", "guide": "guide"}},
            {"id": "ai", "type": "image_generate", "params": {"prompt": "bronze ornamental motifs", "resolution": 256},
             "inputs": {"image": "motif", "mask": "mask"}},
        ]}
        (self.root / "canvas/studio.json").write_text(json.dumps(self.project))
        self.server = make_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        for job_id in list(self.server.studio.jobs):
            self.server.studio.cancel(job_id)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body=None if body is None else json.dumps(body), headers=request_headers)
            response = connection.getresponse()
            data = response.read()
            result = json.loads(data) if response.getheader("Content-Type", "").startswith("application/json") else data
            return response.status, result
        finally:
            connection.close()

    def symlink_or_skip(self, link, target):
        try:
            link.symlink_to(target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314 or exc.errno in {errno.EPERM, errno.ENOSYS}:
                self.skipTest("This OS/account does not permit creating symbolic links")
            raise

    def job(self, node_id, expect="succeeded"):
        status, job = self.request("POST", "/api/jobs", {"node_id": node_id})
        self.assertEqual(status, 202, job)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, job = self.request("GET", "/api/jobs/" + job["id"])
            if job["status"] in {"succeeded", "failed", "cancelled", "awaiting_codex"}:
                self.assertEqual(job["status"], expect, job)
                return job
            time.sleep(.025)
        self.fail("job timeout")

    def test_project_save_upload_and_export(self):
        project = self.request("GET", "/api/project")[1]
        project["nodes"][0]["title"] = "可编辑标题"
        self.assertEqual(self.request("PUT", "/api/project", project)[0], 200)
        self.assertEqual(self.request("GET", "/api/project")[1]["nodes"][0]["title"], "可编辑标题")
        content = base64.b64encode((self.root / "cases/motif.png").read_bytes()).decode()
        status, upload = self.request("POST", "/api/upload", {"name": "paint.png", "data": "data:image/png;base64," + content})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("GET", upload["url"])[0], 200)
        status, data = self.request("GET", "/api/export?node_id=motif")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("project.json", archive.namelist())
            self.assertIn("cases/motif.png", archive.namelist())

    def test_geometry_requires_current_maps_and_rejects_old_case_mode(self):
        studio = self.server.studio
        node = {"id": "geometry", "type": "blender", "inputs": {}, "params": {}}
        with self.assertRaisesRegex(BadRequest, "mask"):
            studio.run_blender("test", node, self.project, self.root / "runs/result")
        node["params"]["mode"] = "approved_before"
        with self.assertRaisesRegex(BadRequest, "from_maps"):
            studio.run_blender("test", node, self.project, self.root / "runs/result")

    def test_geometry_checks_map_dimensions_before_optional_software(self):
        Image.new("L", (32, 64), 128).save(self.root / "cases/mask.png")
        node = {"id": "geometry", "type": "blender", "inputs": {"image": "motif", "mask": "mask"}, "params": {}}
        with self.assertRaisesRegex(BadRequest, "相同像素尺寸"):
            self.server.studio.run_blender("test", node, self.project, self.root / "runs/result")

    def test_geometry_commands_use_current_maps_and_skill_scripts(self):
        studio = self.server.studio
        node = {"id": "geometry", "type": "blender", "inputs": {"image": "motif", "mask": "mask"},
                "params": {"width_m": .1, "base_m": .002, "relief_m": .003, "area": .00001}}
        out = self.root / "runs/result"
        out.mkdir(parents=True)
        commands = []
        def record_process(job_id, command, label, percent):
            commands.append(command)
            if "scale_relief.py" in " ".join(command):
                (out / "mesh").mkdir()
                (out / "mesh/scale_checks.json").write_text('{"status":"passed"}')
            if "build_scene.py" in " ".join(command):
                (out / "result").mkdir()
                (out / "result/fbx_uv_checks.json").write_text('{"status":"passed"}')
        with patch.object(studio, "blender", return_value=Path("blender")), \
             patch.object(studio, "capabilities", return_value={"blender": {"missing_python_modules": []}}), \
             patch.object(studio, "process", side_effect=record_process), \
             patch.dict("os.environ", {"DISPLAY": ":test"}):
            result = studio.run_blender("test", node, self.project, out)
        self.assertEqual(result["engine"], "blender")
        self.assertEqual((out / "maps/04_height.png").read_bytes(), (self.root / "cases/motif.png").read_bytes())
        self.assertEqual((out / "maps/03_material_mask.png").read_bytes(), (self.root / "cases/mask.png").read_bytes())
        self.assertIn(str(self.root / "scripts/build_quad_uv.py"), commands[0])
        self.assertIn("linear", commands[0])
        self.assertNotIn("cases/ding", " ".join(" ".join(command) for command in commands))

    def test_package_download_and_resume(self):
        folder = self.root / "runs/packages"
        folder.mkdir()
        name = "photo-to-ornament-skill.zip"
        payload = b"0123456789"
        (folder / name).write_bytes(payload)
        (folder / "credentials.json").write_text("private")
        code, inventory = self.request("GET", "/api/downloads")
        self.assertEqual(code, 200)
        self.assertEqual([f["name"] for f in inventory["files"]], [name])
        for method, headers, status, expected, content_range in [
            ("GET", {}, 200, payload, None),
            ("HEAD", {}, 200, b"", None),
            ("GET", {"Range": "bytes=3-5"}, 206, b"345", "bytes 3-5/10"),
            ("GET", {"Range": "bytes=7-"}, 206, b"789", "bytes 7-9/10"),
            ("GET", {"Range": "bytes=-2"}, 206, b"89", "bytes 8-9/10"),
            ("GET", {"Range": "bytes=0-100"}, 206, payload, "bytes 0-9/10"),
            ("GET", {"Range": "bytes=3-5", "If-Range": '"changed"'}, 200, payload, None),
            ("GET", {"Range": "bytes=10-"}, 416, b"", "bytes */10"),
            ("GET", {"Range": "bytes=6-2"}, 416, b"", "bytes */10"),
            ("GET", {"Range": "bytes=-0"}, 416, b"", "bytes */10"),
            ("GET", {"Range": "bytes=0-1,4-5"}, 416, b"", "bytes */10"),
        ]:
            connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
            connection.request(method, "/download/" + name, headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, status)
            self.assertEqual(response.getheader("Content-Range"), content_range)
            self.assertEqual(response.read(), expected)
            if status != 416:
                self.assertIn('attachment; filename="' + name + '"', response.getheader("Content-Disposition"))
                self.assertEqual(response.getheader("Accept-Ranges"), "bytes")
            connection.close()
        for path in ("/download/../project.json", "/download/credentials.json"):
            self.assertEqual(self.request("GET", path)[0], 400)
    def test_package_symlink_escape_is_rejected(self):
        folder = self.root / "runs/packages"
        folder.mkdir()
        name = "photo-to-ornament-skill.zip"
        outside = self.root / "cases/elsewhere.zip"
        outside.write_bytes(b"private")
        self.symlink_or_skip(folder / name, outside)
        self.assertEqual(self.request("GET", "/download/" + name)[0], 400)

    def test_path_traversal_and_secret_protection(self):
        for path in ["/files/../../etc/passwd", "/files/runs/../.git/config", "/files/cases/../.env", "/files/canvas/server.py", "/../server.py"]:
            self.assertEqual(self.request("GET", path)[0], 400, path)
        (self.root / "runs/token.json").write_text('{"hidden": true}')
        self.assertEqual(self.request("GET", "/files/runs/token.json")[0], 400)
        status, _ = self.request("PUT", "/api/project", self.project, {"Origin": "https://evil.example"})
        self.assertEqual(status, 400)

    def test_asset_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "outside.png"
            secret.write_bytes(b"private")
            self.symlink_or_skip(self.root / "cases/link.png", secret)
            self.assertEqual(self.request("GET", "/files/cases/link.png")[0], 400)

    def test_http_keep_alive_and_rejected_origin_cannot_mutate_project(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            for _ in range(3):
                connection.request("GET", "/api/project")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.version, 11)
                self.assertEqual(json.loads(response.read())["nodes"][0]["id"], "motif")
                self.assertIsNotNone(connection.sock)
            malicious = copy.deepcopy(self.project)
            malicious["nodes"][0]["title"] = "Cross-site overwrite"
            connection.request("PUT", "/api/project", body=json.dumps(malicious),
                               headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn("error", json.loads(response.read()))
            connection.request("GET", "/api/project")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["nodes"][0]["title"], "Motif")
        finally:
            connection.close()

    def test_upload_rejects_false_images(self):
        status, result = self.request("POST", "/api/upload", {"name": "fake.png", "data": base64.b64encode(b"not an image").decode()})
        self.assertEqual(status, 400, result)
        status, _ = self.request("POST", "/api/upload", {"name": "exploit.html", "data": "YWJj"})
        self.assertEqual(status, 400)

    def test_uv_extract_and_pattern_only_inside_mask(self):
        uv = self.job("uv")
        self.assertEqual(uv["result"]["engine"], "obj_uv")
        self.assertIn("mask", [o["label"] for o in uv["result"]["outputs"]])
        project = self.request("GET", "/api/project")[1]
        next(n for n in project["nodes"] if n["id"] == "pattern")["inputs"]["mask"] = "uv"
        self.request("PUT", "/api/project", project)
        pattern = self.job("pattern")
        path = self.root / pattern["result"]["preview"]
        with Image.open(path) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.getpixel((255, 0))[3], 0)
            self.assertGreater(image.getchannel("A").getbbox()[2], 0)

    def test_restore_and_stale_save_cannot_erase_history(self):
        stale = copy.deepcopy(self.project)
        first = self.job("pattern")
        stale["nodes"][4]["params"]["density"] = 7
        saved = self.request("PUT", "/api/project", stale)[1]
        self.assertEqual(len(saved["nodes"][4]["history"]), 1)
        self.assertTrue(saved["nodes"][4]["output_stale"])
        second = self.job("pattern")
        self.assertNotEqual(first["result"]["preview"], second["result"]["preview"])
        status, restored = self.request("POST", "/api/restore", {"node_id": "pattern", "version_id": first["id"]})
        self.assertEqual(status, 200)
        node = restored["nodes"][4]
        self.assertEqual(node["params"]["density"], 4)
        self.assertEqual(len(node["history"]), 2)
        self.assertEqual(node["preview"], first["result"]["preview"])
        self.assertFalse(node["output_stale"])

    def test_initial_image_and_uploaded_replacement_can_both_be_restored(self):
        project = self.request("GET", "/api/project")[1]
        original = project["nodes"][0]["active_version"]
        self.assertEqual(project["nodes"][0]["history"][0]["origin"], "existing_asset")
        project["nodes"][0]["source"] = "cases/mask.png"
        saved = self.request("PUT", "/api/project", project)[1]
        replacement = saved["nodes"][0]["active_version"]
        self.assertNotEqual(original, replacement)
        self.assertEqual(saved["nodes"][0]["preview"], "cases/mask.png")
        restored = self.request("POST", "/api/restore", {"node_id": "motif", "version_id": original})[1]
        self.assertEqual(restored["nodes"][0]["source"], "cases/motif.png")
        restored = self.request("POST", "/api/restore", {"node_id": "motif", "version_id": replacement})[1]
        self.assertEqual(restored["nodes"][0]["source"], "cases/mask.png")

    def test_pattern_restore_detects_changed_upstream_guide_without_mutating_it(self):
        project = self.request("GET", "/api/project")[1]
        project["nodes"][2]["params"] = {"density": 5, "local_density": 2}
        self.request("PUT", "/api/project", project)
        first = self.job("pattern")
        project = self.request("GET", "/api/project")[1]
        self.assertEqual(project["nodes"][4]["history"][-1]["input_snapshot"]["guide"]["params"]["density"], 5)
        project["nodes"][2]["params"]["density"] = 8
        saved = self.request("PUT", "/api/project", project)[1]
        self.assertTrue(saved["nodes"][4]["output_stale"])
        self.job("pattern")
        restored = self.request("POST", "/api/restore", {"node_id": "pattern", "version_id": first["id"]})[1]
        self.assertEqual(restored["nodes"][2]["params"]["density"], 8)
        self.assertEqual(restored["nodes"][4]["result"]["params"]["density"], 5)
        self.assertTrue(restored["nodes"][4]["output_stale"])
        # Imported legacy records still compare effective density when no full
        # job snapshot remains. Do not mislabel an older density-5 result current.
        legacy = copy.deepcopy(restored["nodes"][4]["history"][0])
        legacy.pop("input_snapshot")
        legacy["id"] = "legacy-without-job"
        self.assertTrue(self.server.studio.version_stale(restored, restored["nodes"][4], legacy))
        restored["nodes"][2]["params"]["density"] = 5
        matching = self.request("PUT", "/api/project", restored)[1]
        self.assertFalse(matching["nodes"][4]["output_stale"])

    def test_fresh_guide_source_and_parameters_used_without_snapshot(self):
        red = self.root / "cases/red.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(red)
        project = copy.deepcopy(self.project)
        project["nodes"][2].update(source="cases/red.png", params={"density": 6, "local_density": 2})
        self.request("PUT", "/api/project", project)
        guide = self.job("guide")
        clear = self.root / "cases/clear.png"
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(clear)
        project = self.request("GET", "/api/project")[1]
        project["nodes"][2]["source"] = "cases/clear.png"
        self.request("PUT", "/api/project", project)
        self.assertEqual(self.server.studio.resolve(self.server.studio.project, self.server.studio.project["nodes"][4], "guide"), clear)
        result = self.job("pattern")["result"]
        self.assertEqual(result["params"]["density"], 6)

    def test_first_unpainted_density_guide_saves_original_extent_and_drives_pattern(self):
        # A first save before drawing has neither a source nor a preview.
        Image.new("RGBA", (80, 40), (180, 150, 120, 255)).save(self.root / "cases/motif.png")
        initial = next(n for n in self.request("GET", "/api/project")[1]["nodes"] if n["id"] == "guide")
        self.assertFalse(initial.get("source"))
        self.assertFalse(initial.get("preview"))
        initial_history_count = len(initial.get("history", []))
        guide_job = self.job("guide")
        guide_output = next(o for o in guide_job["result"]["outputs"] if o["label"] == "guide")
        with Image.open(self.root / guide_output["path"]) as guide:
            self.assertEqual(guide.mode, "RGBA")
            self.assertEqual(guide.size, (80, 40))
            self.assertFalse(np.asarray(guide).any())
        project = self.request("GET", "/api/project")[1]
        node = next(n for n in project["nodes"] if n["id"] == "guide")
        self.assertEqual(node["active_version"], guide_job["id"])
        self.assertEqual(len(node["history"]), initial_history_count + 1)
        guided = self.job("pattern")["result"]
        self.assertEqual(guided["source_guide_size"], [80, 40])
        self.assertEqual(guided["metrics"]["guide_pixels"], 0)
        self.assertEqual(guided["metrics"]["local_placements"], 0)
        self.assertGreater(guided["metrics"]["base_placements"], 0)
        project = self.request("GET", "/api/project")[1]
        next(n for n in project["nodes"] if n["id"] == "pattern")["inputs"].pop("guide")
        self.request("PUT", "/api/project", project)
        unguided = self.job("pattern")["result"]
        self.assertEqual((self.root / guided["preview"]).read_bytes(),
                         (self.root / unguided["preview"]).read_bytes())

    def test_codex_is_pending_until_real_file_completion_and_clips_mask(self):
        job = self.job("ai", "awaiting_codex")
        self.assertEqual(job["progress"], 5)
        self.assertEqual(len(self.request("GET", "/api/codex/requests")[1]["requests"]), 1)
        start = self.request("POST", "/api/codex/start", {"job_id": job["id"]})[1]
        self.assertEqual(start["status"], "running_codex")
        self.assertEqual(start["progress"], 20)
        self.assertEqual(len(self.request("GET", "/api/codex/requests")[1]["requests"]), 0)
        # The test supplies a fixture only to test the bridge, never calls it AI output.
        status, complete = self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png", "notes": "HTTP test fixture"})
        self.assertEqual(status, 200, complete)
        self.assertEqual(complete["status"], "succeeded")
        self.assertEqual(job["request"]["mask_role"], "uv_constraint")
        self.assertEqual(complete["result"]["mask_role"], "uv_constraint")
        self.assertFalse(complete["result"]["original_bytes_preserved"])
        with Image.open(self.root / complete["result"]["preview"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(image.size, (256, 256))
        self.assertIn("raw_generation", [o["label"] for o in complete["result"]["outputs"]])
        self.assertEqual(self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png"})[0], 400)

    def test_height_completion_preserves_16bit_samples_and_bytes_with_material_guidance(self):
        project = copy.deepcopy(self.project)
        # The ordinary fourth stage takes its semantic mask from an image node.
        project["nodes"][1]["type"] = "image_generate"
        self.assertEqual(self.request("PUT", "/api/project", project)[0], 200)
        samples = (np.arange(73 * 37, dtype=np.uint32).reshape(37, 73) * 23).astype(np.uint16)
        source = self.root / "cases/height16.png"
        Image.fromarray(samples).save(source)
        original = source.read_bytes()
        job = self.job("ai", "awaiting_codex")
        self.assertEqual(job["request"]["mask_role"], "material_reference")
        # Later changes to the live graph must not change the queued operation.
        project["nodes"][1]["type"] = "uv_mask"
        self.assertEqual(self.request("PUT", "/api/project", project)[0], 200)
        status, complete = self.request("POST", "/api/codex/complete", {
            "job_id": job["id"], "path": "cases/height16.png", "notes": "16-bit bridge fixture"})
        self.assertEqual(status, 200, complete)
        result = complete["result"]
        self.assertIsNone(result["mask_clip"])
        self.assertEqual(result["mask_role"], "material_reference")
        self.assertEqual(result["native_bit_depth"], 16)
        self.assertTrue(result["original_bytes_preserved"])
        target = self.root / result["preview"]
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        with Image.open(target) as preserved:
            self.assertEqual(preserved.size, (73, 37))
            np.testing.assert_array_equal(np.asarray(preserved), samples)

    def test_explicit_uv_rejects_high_depth_before_creating_output_and_can_retry(self):
        source = self.root / "cases/height16.png"
        Image.fromarray(np.full((64, 64), 12345, dtype=np.uint16)).save(source)
        original = source.read_bytes()
        mask_path = self.root / "cases/mask.png"
        mask_original = mask_path.read_bytes()
        job = self.job("ai", "awaiting_codex")
        status, error = self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/height16.png"})
        self.assertEqual(status, 400)
        self.assertIn("8 位", error["error"])
        Image.fromarray(np.full((64, 64), 65535, dtype=np.uint16)).save(mask_path)
        status, error = self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png"})
        self.assertEqual(status, 400)
        self.assertIn("高位深", error["error"])
        out = self.server.studio.state / "nodes" / "ai" / job["id"]
        self.assertFalse((out / "codex-raw.png").exists())
        self.assertFalse((out / "codex-image.png").exists())
        self.assertEqual(source.read_bytes(), original)
        mask_path.write_bytes(mask_original)
        status, complete = self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png"})
        self.assertEqual(status, 200, complete)
        self.assertEqual(complete["result"]["mask_clip"]["output_bit_depth"], 8)

    def test_codex_non_square_mask_preserves_aspect_at_requested_long_edge(self):
        mask = Image.new("L", (64, 32), 0)
        ImageDraw.Draw(mask).rectangle((8, 4, 55, 27), fill=255)
        mask.save(self.root / "cases/mask.png")
        mask_bytes = (self.root / "cases/mask.png").read_bytes()
        raw_bytes = (self.root / "cases/motif.png").read_bytes()
        job = self.job("ai", "awaiting_codex")
        status, complete = self.request("POST", "/api/codex/complete", {
            "job_id": job["id"], "path": "cases/motif.png", "notes": "Non-square HTTP test fixture"})
        self.assertEqual(status, 200, complete)
        self.assertEqual(complete["status"], "succeeded")
        self.assertEqual(complete["result"]["native_dimensions"], [64, 64])
        self.assertEqual(complete["result"]["mask_clip"]["output_dimensions"], [256, 128])
        expected_allowed = np.asarray(mask.resize((256, 128), Image.Resampling.NEAREST)) >= 128
        with Image.open(self.root / complete["result"]["preview"]) as image:
            self.assertEqual(image.size, (256, 128))
            result = np.asarray(image)
            self.assertFalse(result[~expected_allowed].any())
            self.assertTrue((result[expected_allowed, 3] == 255).all())
        raw_output = next(o for o in complete["result"]["outputs"] if o["label"] == "raw_generation")
        self.assertEqual((self.root / raw_output["path"]).read_bytes(), raw_bytes)
        self.assertEqual((self.root / "cases/mask.png").read_bytes(), mask_bytes)

    def test_pending_job_survives_restart_and_cancel_rejects_completion(self):
        job = self.job("ai", "awaiting_codex")
        recovered = Studio(self.root)
        self.assertEqual(recovered.public_job(job["id"])["status"], "awaiting_codex")
        self.assertEqual(self.request("POST", "/api/jobs/" + job["id"] + "/cancel", {})[1]["status"], "cancelled")
        self.assertEqual(self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png"})[0], 400)

    def test_subprocess_cancellation_stops_actual_process(self):
        studio = self.server.studio
        job_id = "cancel-process"
        studio.jobs[job_id] = {"id": job_id, "node_id": "motif", "status": "running", "logs": []}
        studio.cancellations[job_id] = threading.Event()
        outcome = []
        def run():
            try:
                studio.process(job_id, [sys.executable, "-u", "-c", "import time; print('ready', flush=True); time.sleep(30)"], "process", 10)
            except Cancelled:
                outcome.append("cancelled")
        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.monotonic() + 3
        while not any(log["message"] == "ready" for log in studio.jobs[job_id]["logs"]) and time.monotonic() < deadline:
            time.sleep(.01)
        process = studio.processes[job_id]
        self.assertEqual(self.request("POST", "/api/jobs/" + job_id + "/cancel", {})[1]["status"], "cancelled")
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertIsNotNone(process.poll())
        self.assertEqual(outcome, ["cancelled"])

    def test_cycles_and_missing_inputs_fail_clearly(self):
        project = copy.deepcopy(self.project)
        project["nodes"][4]["inputs"]["image"] = "pattern"
        self.request("PUT", "/api/project", project)
        status, error = self.request("POST", "/api/jobs", {"node_id": "pattern"})
        self.assertEqual(status, 400)
        self.assertIn("循环", error["error"])
        project["nodes"][4]["inputs"] = {}
        self.request("PUT", "/api/project", project)
        self.assertIn("image", self.job("pattern", "failed")["message"])


if __name__ == "__main__":
    unittest.main()
