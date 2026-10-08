"""Real HTTP integration checks; run with python -m unittest discover -s canvas/tests."""
import base64
import copy
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import zipfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Cancelled, Studio, make_server


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
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        result = json.loads(data) if response.getheader("Content-Type", "").startswith("application/json") else data
        code = response.status
        connection.close()
        return code, result

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

    def test_package_download_and_resume(self):
        folder = self.root / "runs/packages"
        folder.mkdir()
        name = "photo-to-ornament-workflow-full.zip"
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
        outside = self.root / "cases/elsewhere.zip"
        outside.write_bytes(payload)
        (folder / name).unlink()
        (folder / name).symlink_to(outside)
        self.assertEqual(self.request("GET", "/download/" + name)[0], 400)

    def test_path_traversal_and_secret_protection(self):
        for path in ["/files/../../etc/passwd", "/files/runs/../.git/config", "/files/cases/../.env", "/files/canvas/server.py", "/../server.py"]:
            self.assertEqual(self.request("GET", path)[0], 400, path)
        (self.root / "runs/token.json").write_text('{"hidden": true}')
        self.assertEqual(self.request("GET", "/files/runs/token.json")[0], 400)
        (self.root / "cases/link.png").symlink_to("/etc/passwd")
        self.assertEqual(self.request("GET", "/files/cases/link.png")[0], 400)
        status, _ = self.request("PUT", "/api/project", self.project, {"Origin": "https://evil.example"})
        self.assertEqual(status, 400)

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
        with Image.open(self.root / complete["result"]["preview"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(image.size, (256, 256))
        self.assertIn("raw_generation", [o["label"] for o in complete["result"]["outputs"]])
        self.assertEqual(self.request("POST", "/api/codex/complete", {"job_id": job["id"], "path": "cases/motif.png"})[0], 400)

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
