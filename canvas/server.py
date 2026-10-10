"""Local node studio: persisted projects, real jobs and an explicit Codex bridge.

Run from any directory with ``.venv/bin/python canvas/server.py``. The web server
never claims access to the conversation's image tool: those jobs remain pending
until Codex creates a real image and calls the completion endpoint.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import importlib.util
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, quote, unquote, urlparse
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 32 * 1024 * 1024
MAX_BODY = 46 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ASSET_SUFFIXES = IMAGE_SUFFIXES | {".obj", ".fbx", ".blend", ".svg", ".npz", ".json", ".txt", ".zip", ".canvas"}
NODE_TYPES = {"source", "image_generate", "density_guide", "uv_extract", "uv_mask", "pattern", "blender"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
PACKAGE_NAME = re.compile(r"^photo-to-ornament-skill\.zip(?:\.sha256)?$")
TERMINAL = {"succeeded", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class BadRequest(ValueError):
    pass


class Cancelled(Exception):
    pass


def stop_process(process):
    """Stop the whole Blender/Xvfb group, escalating only if it ignores TERM."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


class Studio:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.state = self.root / "runs/canvas-studio"
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.cancellations = {}
        self.processes = {}
        self.workers = threading.Semaphore(2)
        self.blender_slot = threading.Semaphore(1)
        self.project_file = self.state / "project.json"
        source = self.project_file if self.project_file.exists() else self.root / "canvas/studio.json"
        self.project = json.loads(source.read_text("utf-8")) if source.exists() else {"version": 1, "nodes": []}
        self.validate_project(self.project)
        seed_path = self.root / "canvas/studio.json"
        seed_project = json.loads(seed_path.read_text("utf-8")) if seed_path.exists() else {"nodes": []}
        seed_nodes = {n["id"]: n for n in seed_project["nodes"]}
        baseline_added = False
        for node in self.project["nodes"]:
            if not node.get("history") and (node.get("source") or node.get("preview") or node.get("outputs") or node["type"] == "density_guide"):
                baseline_added = self.snapshot_asset(node, "existing_asset", "初始资料") or baseline_added
            elif node.get("history") and not any(v.get("origin") == "existing_asset" for v in node["history"]):
                seed = copy.deepcopy(seed_nodes.get(node["id"]))
                if seed and self.snapshot_asset(seed, "existing_asset", "初始资料"):
                    node["history"].insert(0, seed["history"][-1])
                    baseline_added = True
        if baseline_added:
            atomic_json(self.project_file, self.project)
        for path in sorted((self.state / "jobs").glob("*.json")):
            try:
                job = json.loads(path.read_text("utf-8"))
                if job["status"] in {"running", "queued"}:
                    job.update(status="failed", message="服务已重启；此任务已停止，请重新生成。")
                elif job["status"] == "running_codex":
                    job.update(status="awaiting_codex", progress=5, message="服务重启；请由 Codex 对话核实外部调用状态再继续。")
                self.jobs[job["id"]] = job
                self.cancellations[job["id"]] = threading.Event()
            except (ValueError, KeyError):
                continue
        before_staleness = [node.get("output_stale") for node in self.project["nodes"]]
        self.refresh_staleness(self.project)
        if before_staleness != [node.get("output_stale") for node in self.project["nodes"]]:
            atomic_json(self.project_file, self.project)

    def asset(self, value, *, must_exist=True):
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            raise BadRequest("无效资料路径")
        if value.startswith("/files/"):
            value = unquote(value[7:])
        path = Path(value)
        if path.is_absolute() or any(part.startswith(".") or part in {"..", "."} for part in path.parts):
            raise BadRequest("资料路径必须位于仓库允许的目录内")
        if not path.parts or path.parts[0] not in {"canvas", "cases", "assets", "runs"}:
            raise BadRequest("此目录不能作为画板资料读取")
        if path.suffix.lower() not in ASSET_SUFFIXES:
            raise BadRequest("不支持的资料类型")
        if any(re.search(r"(?:credential|secret|auth(?:\.|$)|private.?key|token)", p, re.I) for p in path.parts):
            raise BadRequest("此文件不能作为画板资料读取")
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root / path.parts[0]):
            raise BadRequest("资料路径越界")
        if must_exist and not resolved.is_file():
            raise BadRequest("资料不存在：" + value)
        return resolved

    def relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def output(self, label, path):
        relative = self.relative(path)
        return {"label": label, "path": relative, "url": "/files/" + quote(relative)}

    def validate_project(self, project):
        if not isinstance(project, dict) or not isinstance(project.get("nodes"), list):
            raise BadRequest("项目必须包含 nodes 数组")
        if len(project["nodes"]) > 300:
            raise BadRequest("节点数量超过 300")
        ids = set()
        for node in project["nodes"]:
            if not isinstance(node, dict) or not IDENTIFIER.fullmatch(str(node.get("id", ""))):
                raise BadRequest("节点 ID 无效")
            if node["id"] in ids or node.get("type") not in NODE_TYPES:
                raise BadRequest("节点重复或类型不支持")
            ids.add(node["id"])
            if not isinstance(node.get("params", {}), dict) or not isinstance(node.get("inputs", {}), dict):
                raise BadRequest("节点参数或输入格式无效")
            for key in ("source", "preview"):
                if node.get(key):
                    self.asset(node[key], must_exist=False)
            for output in node.get("outputs", []):
                if output.get("path"):
                    self.asset(output["path"], must_exist=False)
        try:
            json.dumps(project, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise BadRequest("项目包含不可保存的数值") from exc

    def save_project(self, project):
        self.validate_project(project)
        with self.lock:
            incoming = copy.deepcopy(project)
            previous = {n["id"]: n for n in self.project["nodes"]}
            for node in incoming["nodes"]:
                current = previous.get(node["id"])
                if not current:
                    if node.get("source"):
                        self.snapshot_asset(node, "uploaded_asset", "导入资料", incoming)
                    continue
                if node.get("source") != current.get("source") and node.get("source"):
                    uploaded = self.asset(node["source"])
                    label = "guide" if node["type"] == "density_guide" else "model" if uploaded.suffix.lower() == ".obj" else "mask" if node["type"] == "uv_mask" else "image"
                    node["history"] = copy.deepcopy(current.get("history", []))
                    node["outputs"] = [self.output(label, uploaded)]
                    node["preview"] = node["source"] if uploaded.suffix.lower() in IMAGE_SUFFIXES else None
                    node["result"] = {"engine": "uploaded_asset"}
                    self.snapshot_asset(node, "uploaded_asset", "密度绘制" if label == "guide" else "导入资料", incoming)
                    continue
                if not current.get("history"):
                    continue
                # Jobs and restore own versions. A stale browser autosave may edit
                # parameters, but must never erase a finished job or undo restore.
                node["history"] = copy.deepcopy(current["history"])
                for key in ("outputs", "preview", "active_version", "result"):
                    if key in current:
                        node[key] = copy.deepcopy(current[key])
            self.refresh_staleness(incoming)
            incoming["revision"] = int(self.project.get("revision", 0)) + 1
            self.project = incoming
            self.project["updated_at"] = now()
            atomic_json(self.project_file, self.project)
            return copy.deepcopy(self.project)

    def dependency_snapshot(self, project, node):
        snapshots = {}
        for slot, source_id in node.get("inputs", {}).items():
            if not source_id:
                continue
            try:
                source = self.node(project, source_id)
            except BadRequest:
                snapshots[slot] = {"id": source_id, "missing": True}
                continue
            snapshots[slot] = {key: copy.deepcopy(source.get(key)) for key in
                               ("id", "type", "source", "preview", "active_version", "params")}
        return snapshots

    def version_stale(self, project, node, version):
        if any(node.get(key) != version.get(key) for key in ("params", "inputs", "source")):
            return True
        baseline = version.get("input_snapshot")
        legacy_snapshot = baseline is None
        if baseline is None:
            # Early saved versions have the same immutable submission in their job.
            old_job = self.jobs.get(version.get("id"), {})
            old_project = old_job.get("snapshot")
            if old_project:
                try:
                    baseline = self.dependency_snapshot(old_project, self.node(old_project, node["id"]))
                except BadRequest:
                    pass
        if baseline is not None:
            current_inputs = self.dependency_snapshot(project, node)
            if legacy_snapshot:
                # An administrative initial-asset version added during migration
                # does not change the actual legacy input file or parameters.
                for slot, expected in baseline.items():
                    actual = current_inputs.get(slot)
                    if not actual or expected.get("active_version") is not None or not actual.get("active_version"):
                        continue
                    upstream = self.node(project, actual["id"])
                    active = next((v for v in upstream.get("history", []) if v.get("id") == actual["active_version"]), {})
                    if active.get("origin") == "existing_asset":
                        actual["active_version"] = None
            return baseline != current_inputs
        # Older imported pattern reports retain effective guide parameters even
        # when no submitted project is available. They must not appear current
        # after restoring an image made with different guide density settings.
        if node["type"] == "pattern":
            effective = (version.get("result") or {}).get("params", {})
            guide_id = node.get("inputs", {}).get("guide")
            if guide_id:
                try:
                    guide_params = self.node(project, guide_id).get("params", {})
                except BadRequest:
                    return True
                for key in ("density", "local_density"):
                    if key in guide_params and effective.get(key) != guide_params[key]:
                        return True
        return False

    def refresh_staleness(self, project):
        for node in project["nodes"]:
            active = next((v for v in node.get("history", []) if v.get("id") == node.get("active_version")), None)
            if active:
                node["output_stale"] = self.version_stale(project, node, active)

    def snapshot_asset(self, node, engine, label, project=None):
        """Version existing files without inventing a generation or copying models."""
        outputs = []
        for item in node.get("outputs", []):
            try:
                outputs.append(self.output(item.get("label", "资料"), self.asset(item["path"])))
            except (BadRequest, KeyError):
                continue
        if not outputs:
            candidate = node.get("source") or node.get("preview")
            if candidate:
                try:
                    path = self.asset(candidate)
                    outputs = [self.output("model" if path.suffix.lower() == ".obj" else "guide" if node["type"] == "density_guide" else "image", path)]
                except BadRequest:
                    pass
        if not outputs and node["type"] != "density_guide":
            return False
        version_id = "asset-" + uuid.uuid4().hex
        preview = node.get("preview")
        if not preview or not any(o["path"] == preview for o in outputs):
            preview = next((o["path"] for o in outputs if Path(o["path"]).suffix.lower() in IMAGE_SUFFIXES), None)
        version = {"id": version_id, "label": label, "origin": engine, "created_at": now(),
                   "params": copy.deepcopy(node.get("params", {})), "inputs": copy.deepcopy(node.get("inputs", {})),
                   "input_snapshot": self.dependency_snapshot(project or self.project, node),
                   "source": node.get("source"), "outputs": outputs, "preview": preview,
                   "result": copy.deepcopy(node.get("result") or {"engine": engine})}
        atomic_json(self.state / "nodes" / node["id"] / version_id / "version.json", version)
        node.setdefault("history", []).append(copy.deepcopy(version))
        node.update(active_version=version_id, outputs=outputs, preview=preview, output_stale=False)
        return True

    def get_project(self):
        with self.lock:
            return copy.deepcopy(self.project)

    def node(self, project, node_id):
        for node in project["nodes"]:
            if node["id"] == node_id:
                return node
        raise BadRequest("找不到节点：" + str(node_id))

    def validate_graph(self, project, node_id, stack=None):
        stack = set() if stack is None else stack
        if node_id in stack:
            raise BadRequest("输入连接形成循环")
        stack = stack | {node_id}
        node = self.node(project, node_id)
        for source_id in node.get("inputs", {}).values():
            if source_id:
                if not isinstance(source_id, str):
                    raise BadRequest("输入必须引用节点 ID")
                self.validate_graph(project, source_id, stack)

    def resolve(self, project, node, slot, optional=False):
        source_id = node.get("inputs", {}).get(slot)
        if not source_id:
            if optional:
                return None
            raise BadRequest("请连接「" + slot + "」输入")
        source = self.node(project, source_id)
        candidates = [source.get("source")] if source.get("type") in {"source", "uv_mask", "density_guide"} else []
        outputs = source.get("outputs", [])
        aliases = {"mask": {"mask", "uv_mask"}, "region": {"mask", "uv_mask"}, "model": {"model", "obj"}, "guide": {"guide", "density_guide"}}
        for item in outputs:
            if item.get("label") in aliases.get(slot, {"pattern", "image", "preview"}):
                candidates.append(item.get("path"))
        candidates.append(source.get("source"))
        candidates.append(source.get("preview"))
        candidates += [item.get("path") for item in outputs]
        suffixes = {".obj"} if slot == "model" else IMAGE_SUFFIXES
        for candidate in candidates:
            if candidate and Path(candidate).suffix.lower() in suffixes:
                return self.asset(candidate)
        if optional and source.get("type") in {"density_guide", "uv_mask"} and not any(candidates):
            return None
        raise BadRequest("上游节点「" + source.get("title", source_id) + "」没有可用输出，请先生成或上传")

    def blender(self):
        candidates = []
        configured = os.environ.get("ORNAMENT_BLENDER")
        if configured:
            candidates.append(Path(configured))
        candidates.append(self.root / ".tools/blender-5.2.2-linux-x64/blender")
        if os.name == "nt":
            candidates.extend(sorted(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob("Blender Foundation/Blender */blender.exe"), reverse=True))
        found = shutil.which("blender")
        if found:
            candidates.append(Path(found))
        return next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)

    def capabilities(self):
        geometry_missing = [name for name in ("scipy", "skimage", "shapely", "triangle", "trimesh")
                            if importlib.util.find_spec(name) is None]
        return {"image_generation": {"provider": "Codex image tool", "requested_provider": "Codex image 2", "mode": "codex_bridge", "available": True,
                  "requires_agent": True, "automatic": False,
                  "message": "图片任务保存为 Codex 请求；由当前对话调用真实图像工具后回填，服务自身不具备图像工具调用权限。"},
                "blender": {"available": self.blender() is not None and not geometry_missing,
                            "modes": ["from_maps"], "missing_python_modules": geometry_missing,
                            "requires_current_maps": True},
                "uv": {"formats": ["obj"], "requires_existing_uv": True},
                "pattern": {"available": True, "mode": "local_pattern", "ai_generation": False},
                "max_upload_bytes": MAX_UPLOAD}

    def upload(self, body):
        name = re.sub(r"[^\w. -]", "_", str(body.get("name", "upload")))[:140]
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES | {".obj"}:
            raise BadRequest("上传支持 PNG / JPG / WebP 图片和带 UV 的 OBJ")
        encoded = body.get("data", "")
        if not isinstance(encoded, str):
            raise BadRequest("上传内容必须是 base64")
        if encoded.startswith("data:"):
            encoded = encoded.partition(",")[2]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise BadRequest("上传内容不是有效 base64") from exc
        if not data or len(data) > MAX_UPLOAD:
            raise BadRequest("上传文件必须介于 1 byte 与 32 MiB")
        if Path(name).suffix.lower() in IMAGE_SUFFIXES:
            from PIL import Image
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
            except Exception as exc:
                raise BadRequest("上传图片无法解析") from exc
        else:
            try:
                data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise BadRequest("OBJ 必须为 UTF-8 文本") from exc
        path = self.state / "uploads" / uuid.uuid4().hex / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {**self.output(name, path), "name": name}

    def persist_job(self, job):
        atomic_json(self.state / "jobs" / (job["id"] + ".json"), job)

    def progress(self, job_id, percent, message):
        with self.lock:
            if self.cancellations[job_id].is_set():
                raise Cancelled()
            job = self.jobs[job_id]
            job.update(progress=max(0, min(100, int(percent))), message=str(message), updated_at=now())
            job["logs"].append({"time": now(), "message": str(message)})
            job["logs"] = job["logs"][-160:]
            self.persist_job(job)

    def public_job(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise BadRequest("找不到任务")
            job = copy.deepcopy(self.jobs[job_id])
            job.pop("snapshot", None)
            if job["status"] in TERMINAL:
                job["project"] = copy.deepcopy(self.project)
            return job

    def submit(self, body):
        if body.get("project") is not None:
            self.save_project(body["project"])
        with self.lock:
            project = copy.deepcopy(self.project)
            node = self.node(project, body.get("node_id"))
            self.validate_graph(project, node["id"])
            if any(j["node_id"] == node["id"] and j["status"] not in TERMINAL for j in self.jobs.values()):
                raise BadRequest("此节点已有进行中的任务")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "node_id": node["id"], "type": node["type"], "status": "queued",
                   "progress": 0, "message": "已进入任务队列", "logs": [], "result": None,
                   "created_at": now(), "updated_at": now(), "snapshot": project}
            self.jobs[job_id] = job
            self.cancellations[job_id] = threading.Event()
            self.persist_job(job)
        threading.Thread(target=self.run, args=(job_id,), daemon=True).start()
        return self.public_job(job_id)

    def run(self, job_id):
        try:
            with self.workers:
                self.progress(job_id, 1, "读取节点参数与输入")
                with self.lock:
                    self.jobs[job_id]["status"] = "running"
                job = self.jobs[job_id]
                project = job["snapshot"]
                node = self.node(project, job["node_id"])
                params = node.get("params", {})
                out = self.state / "nodes" / node["id"] / job_id
                out.mkdir(parents=True, exist_ok=True)
                kind = node["type"]
                if kind == "image_generate":
                    self.queue_codex(job_id, node, project, out)
                    return
                if kind in {"source", "uv_mask", "density_guide"}:
                    if kind == "density_guide" and not (node.get("source") or node.get("preview")):
                        from PIL import Image
                        reference = self.resolve(project, node, "image", True) or self.resolve(project, node, "mask", True)
                        size = (1024, 1024)
                        if reference:
                            with Image.open(reference) as supplied:
                                size = supplied.size
                        if size[0] * size[1] > 16_777_216:
                            raise BadRequest("密度引导底图超过像素上限")
                        target = out / "source.png"
                        Image.new("RGBA", size, (0, 0, 0, 0)).save(target)
                    else:
                        source = self.asset(node.get("source") or node.get("preview"))
                        target = out / ("source" + source.suffix.lower())
                        shutil.copy2(source, target)
                    result = {"engine": "source", "artifacts": {"guide" if kind == "density_guide" else "mask" if kind == "uv_mask" else "image": target.name}}
                elif kind == "uv_extract":
                    from uv_engine import uv_extract
                    model = self.asset(node["source"]) if node.get("source") else self.resolve(project, node, "model")
                    if model.suffix.lower() != ".obj":
                        raise BadRequest("UV 提取目前支持带 UV 的 OBJ")
                    self.progress(job_id, 15, "读取 OBJ 顶点、面与 UV")
                    result = uv_extract(model, out, params)
                elif kind == "pattern":
                    from uv_engine import generate_pattern
                    effective_params = copy.deepcopy(params)
                    guide_id = node.get("inputs", {}).get("guide")
                    if guide_id:
                        guide_params = self.node(project, guide_id).get("params", {})
                        effective_params.update({k: guide_params[k] for k in ("density", "local_density") if k in guide_params})
                    result = generate_pattern(self.resolve(project, node, "image"), self.resolve(project, node, "mask", True),
                        self.resolve(project, node, "guide", True), out, effective_params,
                        progress=lambda p, m: self.progress(job_id, min(95, max(5, p)), m))
                elif kind == "blender":
                    with self.blender_slot:
                        result = self.run_blender(job_id, node, project, out)
                else:
                    raise BadRequest("不支持此节点类型")
                self.finish(job_id, result, out)
        except Cancelled:
            with self.lock:
                self.jobs[job_id].update(status="cancelled", message="已取消", updated_at=now())
                self.persist_job(self.jobs[job_id])
        except Exception as exc:
            with self.lock:
                cancelled = self.cancellations[job_id].is_set()
                self.jobs[job_id].update(status="cancelled" if cancelled else "failed", message="已取消" if cancelled else str(exc), updated_at=now())
                self.jobs[job_id]["logs"].append({"time": now(), "message": str(exc)})
                self.persist_job(self.jobs[job_id])

    def queue_codex(self, job_id, node, project, out):
        params = node.get("params", {})
        effective_params = copy.deepcopy(params)
        input_parameters = {}
        guide_id = node.get("inputs", {}).get("guide")
        if guide_id:
            input_parameters["guide"] = copy.deepcopy(self.node(project, guide_id).get("params", {}))
            effective_params.update({key: input_parameters["guide"][key] for key in ("density", "local_density") if key in input_parameters["guide"]})
        references = {}
        for slot in ("image", "mask", "guide"):
            value = self.resolve(project, node, slot, True)
            if value:
                references[slot] = self.relative(value)
        prompt = str(params.get("prompt", "")).strip()
        if not prompt:
            raise BadRequest("请填写图片生成提示词")
        descriptor = {"job_id": job_id, "node_id": node["id"], "provider": "Codex image tool", "requested_provider": "Codex image 2",
                      "prompt": prompt, "params": effective_params, "submitted_params": copy.deepcopy(params),
                      "input_parameters": input_parameters, "references": references,
                      "mask_role": self.codex_mask_role(project, node),
                      "output_directory": self.relative(out), "created_at": now(),
                      "instructions": "由 Codex 对话查看参考图并调用真实 image_gen 工具；将生成 PNG 放入输出目录，然后 POST /api/codex/complete {job_id,path}。若工具不能控制 seed/strength/精确尺寸，应如实注明；不得用本地图像运算冒充生成。"}
        atomic_json(out / "codex-request.json", descriptor)
        self.progress(job_id, 5, "等待 Codex image 2：请求已保存，请让当前对话处理待生成任务。服务不会自行调用对话工具。")
        with self.lock:
            if self.cancellations[job_id].is_set():
                raise Cancelled()
            self.jobs[job_id].update(status="awaiting_codex", request=descriptor)
            self.persist_job(self.jobs[job_id])

    def codex_mask_role(self, project, node):
        """Only an explicitly typed UV input authorizes destructive clipping."""
        mask_id = node.get("inputs", {}).get("mask")
        if not mask_id:
            return None
        mask_node = self.node(project, mask_id)
        return "uv_constraint" if mask_node["type"] in {"uv_mask", "uv_extract"} else "material_reference"

    @staticmethod
    def png_bit_depth(path):
        with Path(path).open("rb") as source:
            header = source.read(25)
        if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) == 25 and header[12:16] == b"IHDR":
            return header[24]
        return None

    def complete_codex(self, body):
        job_id = body.get("job_id")
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["status"] not in {"awaiting_codex", "running_codex"}:
                raise BadRequest("此任务不在等待 Codex 图片状态")
            path = self.asset(body.get("path"))
            if path.suffix.lower() != ".png":
                raise BadRequest("Codex 完成接口需要真实 PNG")
            from PIL import Image, ImageChops
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise BadRequest("结果必须为 PNG 内容")
                size = list(image.size)
                image.verify()
            bit_depth = self.png_bit_depth(path)
            snapshot_node = self.node(job["snapshot"], job["node_id"])
            mask_role = self.codex_mask_role(job["snapshot"], snapshot_node)
            mask_ref = job["request"]["references"].get("mask")
            uv_mask_path = None
            if mask_ref and mask_role == "uv_constraint":
                # The current UV path uses Pillow RGBA8. Reject higher precision
                # inputs before copying results rather than silently quantizing.
                uv_mask_path = self.asset(mask_ref)
                mask_depth = self.png_bit_depth(uv_mask_path)
                with Image.open(uv_mask_path) as supplied:
                    unsupported_mode = supplied.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}
                if bit_depth != 8 or (mask_depth is not None and mask_depth > 8) or unsupported_mode:
                    raise BadRequest("严格 UV 裁切目前只支持 8 位生成 PNG 和不高于 8 位的 UV 遮罩；高位深图片未转换，请另行执行保真 UV 处理")
            out = self.state / "nodes" / job["node_id"] / job_id
            resolution = job["request"]["params"].get("resolution")
            if resolution is not None:
                resolution = int(resolution)
                if not 256 <= resolution <= 2048:
                    raise BadRequest("输出分辨率须为 256 至 2048")
            raw = out / "codex-raw.png"
            if raw.exists() and path != raw:
                raise BadRequest("已存在结果，不能覆盖历史版本")
            if path != raw:
                shutil.copy2(path, raw)
            target = raw
            artifacts = {"image": raw.name, "request": "codex-request.json"}
            clip_report = None
            if uv_mask_path is not None:
                with Image.open(uv_mask_path) as supplied:
                    mask = supplied.convert("RGBA")
                output_size = mask.size
                if resolution is not None:
                    scale = resolution / max(mask.size)
                    output_size = tuple(max(1, round(edge * scale)) for edge in mask.size)
                mask = mask.resize(output_size, Image.Resampling.NEAREST)
                threshold = lambda p: 255 if p >= 128 else 0
                mask_alpha = ImageChops.multiply(mask.convert("L").point(threshold), mask.getchannel("A").point(threshold))
                with Image.open(raw) as generated:
                    clipped = generated.convert("RGBA").resize(output_size, Image.Resampling.LANCZOS)
                clipped.putalpha(ImageChops.multiply(clipped.getchannel("A"), mask_alpha))
                clipped = Image.composite(clipped, Image.new("RGBA", output_size, (0, 0, 0, 0)), mask_alpha)
                target = out / "codex-image.png"
                clipped.save(target)
                artifacts = {"image": target.name, "raw_generation": raw.name, "request": "codex-request.json"}
                clip_report = {"mask": mask_ref, "mask_threshold": 128, "outside_mask_alpha": 0,
                               "output_dimensions": list(output_size), "mask_aspect_preserved": True,
                               "resampled_from_native": size != list(output_size), "output_bit_depth": 8}
            self.finish(job_id, {"engine": "codex_image", "provider": "Codex image tool", "requested_provider": "Codex image 2",
                        "native_dimensions": size, "native_bit_depth": bit_depth, "mask_role": mask_role,
                        "original_bytes_preserved": uv_mask_path is None, "mask_clip": clip_report,
                        "native_parameter_support": {"seed": False, "strength": False, "exact_resolution": False},
                        "notes": str(body.get("notes", "")), "artifacts": artifacts}, out)
        return self.public_job(job_id)

    def codex_stage(self, body, failed=False):
        job_id = body.get("job_id")
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["status"] not in {"awaiting_codex", "running_codex"}:
                raise BadRequest("此任务不在等待或执行 Codex 图片状态")
            if failed:
                message = str(body.get("message") or "Codex 图像工具调用失败，请查看对话。")
                job.update(status="failed", message=message, updated_at=now())
            else:
                job.update(status="running_codex", progress=20, message="Codex 图像工具正在生成", updated_at=now())
            job["logs"].append({"time": now(), "message": job["message"]})
            self.persist_job(job)
        return self.public_job(job_id)

    def finish(self, job_id, result, out):
        self.progress(job_id, 98, "保存生成结果与独立历史版本")
        job = self.jobs[job_id]
        node = self.node(job["snapshot"], job["node_id"])
        outputs = []
        for label, filename in result.get("artifacts", {}).items():
            path = (out / filename).resolve()
            if not path.is_relative_to(out.resolve()) or not path.is_file():
                raise BadRequest("生成器返回了无效文件路径")
            outputs.append(self.output(label, path))
        preview = next((o["path"] for o in outputs if Path(o["path"]).suffix.lower() in IMAGE_SUFFIXES), None)
        version = {"id": job_id, "created_at": now(), "params": copy.deepcopy(node.get("params", {})),
                   "inputs": copy.deepcopy(node.get("inputs", {})), "source": node.get("source"),
                   "input_snapshot": self.dependency_snapshot(job["snapshot"], node),
                   "outputs": outputs, "preview": preview, "result": result}
        with self.lock:
            if self.cancellations[job_id].is_set():
                raise Cancelled()
            atomic_json(out / "version.json", version)
            try:
                current = self.node(self.project, job["node_id"])
            except BadRequest:
                current = None
            if current:
                current.setdefault("history", []).append(copy.deepcopy(version))
                current.update(outputs=outputs, preview=preview, active_version=job_id)
                current["result"] = result
                self.refresh_staleness(self.project)
                self.project["updated_at"] = now()
                self.project["revision"] = int(self.project.get("revision", 0)) + 1
                atomic_json(self.project_file, self.project)
            job.update(status="succeeded", progress=100, message="生成完成", result={**result, "outputs": outputs, "preview": preview, "version_id": job_id}, updated_at=now())
            self.persist_job(job)

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise BadRequest("找不到任务")
            if job["status"] in TERMINAL:
                return self.public_job(job_id)
            self.cancellations[job_id].set()
            process = self.processes.get(job_id)
            if process and process.poll() is None:
                threading.Thread(target=stop_process, args=(process,), daemon=True).start()
            message = "已取消结果回填；外部已开始的 Codex 调用无法由此服务停止。" if job["status"] == "running_codex" else "已取消任务"
            job.update(status="cancelled", message=message, updated_at=now())
            self.persist_job(job)
            return self.public_job(job_id)

    def restore(self, body):
        node_id, version_id = body.get("node_id", ""), body.get("version_id", "")
        if not IDENTIFIER.fullmatch(str(node_id)) or not IDENTIFIER.fullmatch(str(version_id)):
            raise BadRequest("无效历史版本")
        with self.lock:
            node = self.node(self.project, node_id)
            path = self.state / "nodes" / node_id / version_id / "version.json"
            if path.is_file():
                version = json.loads(path.read_text("utf-8"))
            else:
                version = next((v for v in node.get("history", []) if v.get("id") == version_id), None)
                if not version:
                    raise BadRequest("历史版本不存在")
            for output in version.get("outputs", []):
                self.asset(output["path"])
            for key in ("params", "inputs", "source", "outputs", "preview", "result"):
                node[key] = copy.deepcopy(version.get(key, {} if key in {"params", "inputs", "result"} else [] if key == "outputs" else None))
            node.update(active_version=version_id)
            self.refresh_staleness(self.project)
            self.project["revision"] = int(self.project.get("revision", 0)) + 1
            atomic_json(self.project_file, self.project)
            return copy.deepcopy(self.project)

    def process(self, job_id, command, label, percent):
        self.progress(job_id, percent, label)
        process_env = {**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"}
        local_xvfb = self.root / ".tools/xvfb/usr"
        if (local_xvfb / "bin").is_dir():
            process_env["PATH"] = str(local_xvfb / "bin") + os.pathsep + process_env.get("PATH", "")
        local_lib = local_xvfb / "lib/x86_64-linux-gnu"
        if local_lib.is_dir():
            process_env["LD_LIBRARY_PATH"] = str(local_lib) + os.pathsep + process_env.get("LD_LIBRARY_PATH", "")
        for variable, folder in (("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
            path = self.root / ".tools" / folder
            path.mkdir(parents=True, exist_ok=True)
            process_env[variable] = str(path)
        process = subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", start_new_session=os.name == "posix",
                                   env=process_env)
        with self.lock:
            self.processes[job_id] = process
        try:
            for line in process.stdout:
                self.progress(job_id, percent, line.strip()[-1600:])
            code = process.wait()
            if self.cancellations[job_id].is_set():
                raise Cancelled()
            if code:
                raise RuntimeError(label + "失败，退出码 " + str(code))
        finally:
            if process.poll() is None:
                stop_process(process)
            if process.stdout is not None:
                process.stdout.close()
            with self.lock:
                self.processes.pop(job_id, None)

    def run_blender(self, job_id, node, project, out):
        params = node.get("params", {})
        mode = params.get("mode", "from_maps")
        if mode != "from_maps":
            raise BadRequest("几何仅支持当前连接的高度图与材料遮罩；请设置 from_maps 模式")
        # Validate required current inputs before looking for optional software.
        # Missing inputs must never select an old case or a bundled model.
        mask = self.resolve(project, node, "mask")
        height = self.resolve(project, node, "image")
        if mask.suffix.lower() != ".png" or height.suffix.lower() != ".png":
            raise BadRequest("建模输入须为已确认且布局相同的 PNG 高度图与材料遮罩")
        from PIL import Image
        with Image.open(mask) as mask_image, Image.open(height) as height_image:
            if mask_image.size != height_image.size:
                raise BadRequest("高度图与材料遮罩必须具有相同像素尺寸和布局")
        factor = float(params.get("factor", 1.0))
        if not math.isfinite(factor) or not 0 < factor <= 3:
            raise BadRequest("浮雕系数须为 0 至 3 之间的正数")
        blender = self.blender()
        if not blender:
            raise BadRequest("环境没有可运行的 Blender")
        missing = self.capabilities()["blender"]["missing_python_modules"]
        if missing:
            raise BadRequest("可选几何依赖未安装：" + ", ".join(missing))
        scripts = self.root / "scripts"
        python = sys.executable
        if mode == "from_maps":
            numbers = {}
            for key in ("width_m", "base_m", "relief_m", "area"):
                if key not in params:
                    raise BadRequest("从图建模需要明确设置 " + key)
                value = float(params[key])
                if not math.isfinite(value) or value <= 0:
                    raise BadRequest("建模尺寸和采样面积须为有限正数")
                numbers[key] = value
            if numbers["width_m"] ** 2 / numbers["area"] > 2_000_000:
                raise BadRequest("当前采样面积预计超过资源上限，请增大 area（面积）")
            wall_layers = int(params.get("wall_layers", 16))
            if not 1 <= wall_layers <= 64:
                raise BadRequest("循环边层数须为 1 至 64")
            maps = out / "maps"
            maps.mkdir()
            shutil.copy2(mask, maps / "03_material_mask.png")
            shutil.copy2(height, maps / "04_height.png")
            source = out / "rebuilt_before"
            command = [python, str(scripts / "build_quad_uv.py"), "--maps", str(maps), "--out", str(source),
                       "--wall-layers", str(wall_layers), "--median-size", "1", "--height-sigma", "0",
                       "--height-encoding", "linear", "--shoulder-m", str(numbers["width_m"] * 0.004)]
            for key, value in numbers.items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
            self.process(job_id, command, "从已连接高度 / 遮罩建立独立平面浮雕与 UV", 5)
        self.process(job_id, [python, str(scripts / "scale_relief.py"), "--source", str(source),
                     "--out", str(out / "mesh"), "--factor", str(factor)], "调整正面浮雕，校验底面 / 侧壁 / UV", 10)
        command = [str(blender), "--threads", "4", "--factory-startup", "-b", "--python", str(scripts / "build_scene.py"),
                   "--", "--source", str(out / "mesh"), "--out", str(out / "result")]
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            local_xvfb = self.root / ".tools/xvfb/usr/bin/xvfb-run"
            xvfb = str(local_xvfb) if local_xvfb.is_file() and os.access(local_xvfb, os.X_OK) else shutil.which("xvfb-run")
            if not xvfb:
                raise BadRequest("后台渲染需要 xvfb-run")
            command = [xvfb, "-a", *command]
        self.process(job_id, command, "Blender 渲染、FBX 导出与重导入校验", 30)
        checks = json.loads((out / "result/fbx_uv_checks.json").read_text("utf-8"))
        scale = json.loads((out / "mesh/scale_checks.json").read_text("utf-8"))
        if checks.get("status") != "passed" or scale.get("status") != "passed":
            raise RuntimeError("几何或 FBX 校验没有通过")
        return {"engine": "blender", "checks": checks, "scale_checks": scale,
                "artifacts": {p.stem: p.relative_to(out).as_posix() for p in sorted((out / "result").iterdir())
                              if p.suffix.lower() in ASSET_SUFFIXES} | {"scale_checks": "mesh/scale_checks.json"}}

    def export(self, node_id=None):
        project = self.get_project()
        nodes = project["nodes"]
        if node_id:
            selected = set()
            def include(source_id):
                if source_id in selected:
                    return
                source = self.node(project, source_id)
                selected.add(source_id)
                for upstream in source.get("inputs", {}).values():
                    if upstream:
                        include(upstream)
            include(node_id)
            nodes = [n for n in project["nodes"] if n["id"] in selected]
        manifest = {**project, "nodes": nodes}
        if node_id:
            manifest["exported_node"] = node_id
        paths = set()
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"path", "source", "preview"} and isinstance(item, str) and item:
                        try:
                            paths.add(self.asset(item))
                        except BadRequest:
                            pass
                    else:
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(nodes)
        archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=2) as bundle:
            bundle.writestr("project.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path in sorted(paths):
                bundle.write(path, self.relative(path))
        archive.seek(0)
        return archive


class Handler(BaseHTTPRequestHandler):
    # Every response is length-delimited. Keep ordinary requests alive so fast
    # Windows loopback clients can read the response before either peer closes.
    protocol_version = "HTTP/1.1"
    timeout = 30
    server_version = "OrnamentStudio/1.0"

    def __init__(self, *args, studio, **kwargs):
        self.studio = studio
        super().__init__(*args, **kwargs)

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # A browser closing an idle keep-alive socket is not a server fault.
            self.close_connection = True

    def headers_for(self, code, content_type, length=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        if length is not None:
            self.send_header("Content-Length", str(length))

    def json_response(self, value, status=200):
        content = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.headers_for(status, "application/json; charset=utf-8", len(content))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def read_body(self):
        self.request_body_consumed = False
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BadRequest("请求长度无效") from exc
        if not 0 < length <= MAX_BODY:
            raise BadRequest("请求过大或为空")
        # Consume a bounded body even when its origin or format is rejected.
        # Closing a Windows socket with unread data can discard the 400 reply.
        raw_body = self.rfile.read(length)
        self.request_body_consumed = len(raw_body) == length
        if not self.request_body_consumed:
            raise BadRequest("请求内容不完整")
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise BadRequest("不允许跨站修改项目")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise BadRequest("不允许跨站修改项目")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise BadRequest("请求必须使用 application/json")
        try:
            body = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadRequest("JSON 无效") from exc
        if not isinstance(body, dict):
            raise BadRequest("JSON 必须为对象")
        return body

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/api/downloads":
                folder = self.studio.root / "runs/packages"
                files = [{"name": p.name, "bytes": p.stat().st_size, "url": "/download/" + p.name}
                         for p in sorted(folder.glob("*")) if PACKAGE_NAME.fullmatch(p.name)
                         and p.is_file() and p.resolve().parent == folder.resolve()]
                return self.json_response({"files": files})
            if path.startswith("/download/"):
                return self.download_package(path.removeprefix("/download/"))
            if path == "/api/project":
                return self.json_response(self.studio.get_project())
            if path == "/api/capabilities":
                return self.json_response(self.studio.capabilities())
            if path == "/api/jobs":
                with self.studio.lock:
                    ids = list(self.studio.jobs)
                return self.json_response({"jobs": [self.studio.public_job(i) for i in ids]})
            if path == "/api/codex/requests":
                with self.studio.lock:
                    requests = [copy.deepcopy(j["request"]) for j in self.studio.jobs.values() if j["status"] == "awaiting_codex"]
                return self.json_response({"requests": requests})
            if path.startswith("/api/jobs/"):
                return self.json_response(self.studio.public_job(path.rsplit("/", 1)[-1]))
            if path == "/api/export":
                query = parse_qs(parsed.query)
                archive = self.studio.export(query.get("node_id", [None])[0])
                with archive:
                    archive.seek(0, io.SEEK_END)
                    size = archive.tell()
                    archive.seek(0)
                    self.headers_for(200, "application/zip", size)
                    self.send_header("Content-Disposition", 'attachment; filename="ornament-studio.zip"')
                    self.end_headers()
                    shutil.copyfileobj(archive, self.wfile)
                return
            if path.startswith("/files/"):
                asset = self.studio.asset(path[7:])
            else:
                relative = "index.html" if path in {"/", "/canvas", "/canvas/"} else path.removeprefix("/canvas/").lstrip("/")
                asset = (self.studio.root / "canvas" / relative).resolve()
                if not asset.is_relative_to(self.studio.root / "canvas") or any(p.startswith(".") for p in Path(relative).parts):
                    raise BadRequest("静态文件路径无效")
                if asset.suffix.lower() not in {".html", ".js", ".css", ".png", ".jpg", ".svg", ".ico", ".json", ".canvas", ".md"}:
                    raise BadRequest("静态文件类型不允许")
                if not asset.is_file():
                    return self.json_response({"error": "文件不存在"}, 404)
            mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self.headers_for(200, mime, asset.stat().st_size)
            if asset.suffix.lower() in {".svg", ".json", ".txt"}:
                self.send_header("Content-Security-Policy", "sandbox")
            self.end_headers()
            with asset.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile)
        except (BadRequest, ValueError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/download/"):
            return self.json_response({"error": "此接口不支持 HEAD"}, 405)
        try:
            self.download_package(path.removeprefix("/download/"), head=True)
        except (BadRequest, ValueError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def download_package(self, name, head=False):
        if not PACKAGE_NAME.fullmatch(name):
            raise BadRequest("下载文件名无效")
        folder = (self.studio.root / "runs/packages").resolve()
        asset = (folder / name).resolve()
        if asset.parent != folder:
            raise BadRequest("下载路径无效")
        if not asset.is_file():
            return self.json_response({"error": "文件不存在"}, 404)
        with asset.open("rb") as source:
            stat = os.fstat(source.fileno())
            size = stat.st_size
            etag = '"%x-%x"' % (size, stat.st_mtime_ns)
            start, end, status = 0, size - 1, 200
            requested = None if head else self.headers.get("Range")
            if requested and self.headers.get("If-Range", etag) == etag:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                valid = bool(match and any(match.groups()) and size)
                if valid:
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    else:
                        count = int(last)
                        start = max(0, size - count)
                        valid = count > 0
                    valid = valid and start <= end and start < size
                if not valid:
                    self.headers_for(416, "application/octet-stream", 0)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    return
                status = 206
            length = max(0, end - start + 1)
            mime = "application/zip" if name.endswith(".zip") else "application/octet-stream"
            self.headers_for(status, mime, length)
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_PUT(self):
        self.mutate("PUT")

    def do_POST(self):
        self.mutate("POST")

    def mutate(self, method):
        try:
            body = self.read_body()
            path = urlparse(self.path).path
            if method == "PUT" and path == "/api/project":
                return self.json_response(self.studio.save_project(body))
            if method == "POST" and path == "/api/upload":
                return self.json_response(self.studio.upload(body), 201)
            if method == "POST" and path == "/api/jobs":
                return self.json_response(self.studio.submit(body), 202)
            if method == "POST" and path == "/api/restore":
                return self.json_response(self.studio.restore(body))
            if method == "POST" and path == "/api/codex/complete":
                return self.json_response(self.studio.complete_codex(body))
            if method == "POST" and path in {"/api/codex/start", "/api/codex/fail"}:
                return self.json_response(self.studio.codex_stage(body, failed=path.endswith("/fail")))
            if method == "POST" and re.fullmatch(r"/api/jobs/[^/]+/cancel", path):
                return self.json_response(self.studio.cancel(path.split("/")[3]))
            return self.json_response({"error": "未知接口"}, 404)
        except (BadRequest, ValueError, TypeError, KeyError) as exc:
            # Invalid/oversized lengths are never drained or reused. A bounded
            # rejected body has already been consumed and may safely keep alive.
            if not getattr(self, "request_body_consumed", False):
                self.close_connection = True
            self.json_response({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.json_response({"error": "操作失败：" + str(exc)}, 500)


def make_server(root=ROOT, host="127.0.0.1", port=8001):
    studio = Studio(root)
    server = ThreadingHTTPServer((host, port), partial(Handler, studio=studio))
    server.daemon_threads = True
    server.studio = studio
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    server = make_server(host=args.host, port=args.port)
    print(f"节点画板：http://{args.host}:{server.server_port}/", flush=True)
    print("Codex 图片桥接：等待真实对话工具回填；Blender 与 UV 任务由此服务执行。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job_id in list(server.studio.jobs):
            server.studio.cancel(job_id)
        server.server_close()


if __name__ == "__main__":
    main()
