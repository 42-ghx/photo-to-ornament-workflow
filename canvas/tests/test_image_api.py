"""Offline provider + real studio HTTP tests; no paid calls or user credentials."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_api as api
from server import make_server

TEST_KEY = "unit-test-" + "credential"


class ImageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        buffer = io.BytesIO()
        Image.new("RGBA", (64, 64), (255, 128, 30, 180)).save(buffer, "PNG")
        self.png = buffer.getvalue()
        self.requests = []
        self.reply = {"data": [{"b64_json": base64.b64encode(self.png).decode()}], "model": "mock-image-v1"}
        self.status = 200
        self.location = None
        owner = self

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.requests.append((self.path, dict(self.headers), data))
                self.send_response(owner.status)
                if owner.location:
                    self.send_header("Location", owner.location)
                self.end_headers()
                self.wfile.write(json.dumps(owner.reply).encode())

            def log_message(self, *args):
                pass

        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        self.provider_thread = threading.Thread(target=self.provider.serve_forever, daemon=True)
        self.provider_thread.start()
        self.url = f"http://127.0.0.1:{self.provider.server_port}/v1"
        self.config = api.Config(self.url, "mock-image-v1", TEST_KEY)

    def tearDown(self):
        self.provider.shutdown()
        self.provider.server_close()
        self.provider_thread.join()
        self.temp.cleanup()

    def test_generation_json_and_metadata(self):
        image, metadata = api.generate(self.config, "A bronze ornament", [])
        self.assertEqual(image, self.png)
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/v1/images/generations")
        self.assertEqual(headers["Authorization"], "Bearer " + TEST_KEY)
        self.assertNotIn(TEST_KEY, body.decode())
        self.assertEqual(json.loads(body)["output_format"], "png")
        self.assertEqual(metadata["requested_model"], "mock-image-v1")
        self.assertEqual(metadata["reported_model"], "mock-image-v1")
        self.assertNotIn(TEST_KEY, repr(self.config))
        self.assertNotIn(self.url, repr(self.config))

    def test_edit_multipart_references_are_not_inpainting_mask(self):
        api.generate(self.config, "Preserve material; derive height", [self.png, self.png], background="transparent")
        path, headers, body = self.requests[0]
        self.assertEqual(path, "/v1/images/edits")
        self.assertIn("multipart/form-data", headers["Content-Type"])
        self.assertEqual(body.count(b'name="image[]"'), 2)
        self.assertNotIn(b'name="mask"', body)
        self.assertNotIn(TEST_KEY.encode(), body)

    def test_error_body_and_redirect_never_leak_key(self):
        self.status = 401
        self.reply = {"error": TEST_KEY + self.url}
        with self.assertRaises(api.SafeError) as result:
            api.generate(self.config, "test", [])
        self.assertNotIn(TEST_KEY, str(result.exception))
        self.assertNotIn(self.url, str(result.exception))
        self.status = 307
        self.location = self.url + "/unexpected"
        with self.assertRaises(api.SafeError):
            api.generate(self.config, "test", [])
        self.assertEqual(len(self.requests), 2)  # no redirect or automatic retry

    def test_url_credentials_and_remote_studio_rejected(self):
        for url in ("http://example.com/v1", "https://user:password@example.com/v1", "https://example.com/v1?key=hidden", "https://example.com/v1#fragment"):
            with self.assertRaises(api.SafeError):
                api.base_url(url)
        with self.assertRaises(api.SafeError):
            api.base_url("https://example.com", local_only=True)

    def test_no_output_url_download_or_invalid_image(self):
        self.reply = {"data": [{"url": self.url + "/do-not-fetch"}]}
        with self.assertRaises(api.SafeError):
            api.generate(self.config, "test", [])
        self.assertEqual(len(self.requests), 1)
        self.reply = {"data": [{"b64_json": base64.b64encode(b"not a PNG").decode()}]}
        with self.assertRaises(api.SafeError):
            api.generate(self.config, "test", [])

    def test_prompt_with_current_credential_rejected_before_network(self):
        with self.assertRaises(api.SafeError):
            api.generate(self.config, "accidental " + TEST_KEY, [])
        self.assertEqual(self.requests, [])

    def test_environment_check_is_offline_and_redacted(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"ORNAMENT_IMAGE_API_KEY": TEST_KEY, "ORNAMENT_IMAGE_MODEL": "mock-image-v1", "ORNAMENT_IMAGE_BASE_URL": self.url}), patch("sys.stdout", output):
            self.assertEqual(api.main(["--check"]), 0)
        self.assertNotIn(TEST_KEY, output.getvalue())
        self.assertNotIn(self.url, output.getvalue())
        self.assertEqual(self.requests, [])

    def test_one_studio_job_roundtrip_and_no_duplicate_charge(self):
        (self.root / "canvas").mkdir()
        (self.root / "cases").mkdir()
        (self.root / "cases/input.png").write_bytes(self.png)
        project = {"nodes": [
            {"id": "source", "type": "source", "source": "cases/input.png", "params": {}, "inputs": {}},
            {"id": "edit", "type": "image_generate", "params": {"prompt": "a faithful height map"}, "inputs": {"image": "source"}},
        ]}
        (self.root / "canvas/studio.json").write_text(json.dumps(project))
        studio = make_server(self.root, port=0)
        thread = threading.Thread(target=studio.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{studio.server_port}"
        try:
            job = api.studio_json(url, "/api/jobs", {"node_id": "edit"})
            deadline = time.monotonic() + 5
            while studio.studio.jobs[job["id"]]["status"] != "awaiting_codex":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            api.run_job(self.config, url, job["id"])
            result = studio.studio.public_job(job["id"])
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["result"]["engine"], "openai_compatible_image")
            self.assertEqual(result["result"]["requested_model"], "mock-image-v1")
            with self.assertRaises(api.SafeError):
                api.run_job(self.config, url, job["id"])
            self.assertEqual(len(self.requests), 1)
            for file in (self.root / "runs").rglob("*.json"):
                content = file.read_text()
                self.assertNotIn(TEST_KEY, content)
                self.assertNotIn(self.url, content)
        finally:
            studio.shutdown()
            studio.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
