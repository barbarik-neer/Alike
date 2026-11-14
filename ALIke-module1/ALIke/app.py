"""ALIke — Module 1: Flask application.

This file orchestrates only: uploads, background jobs, status, and result pages.
All pose / maths / analysis work happens in modules/ via pipeline.py.

Run:  python app.py      then open http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from werkzeug.exceptions import HTTPException

import config
import pipeline
import sample_data

try:  # used only to sanity-check uploads; the app still runs without it
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

log = logging.getLogger("alike")

JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")
STAGE_KEYS = [s["key"] for s in config.STAGES]
SLOT_LABELS = {"reference": "reference tutorial", "learner": "performance"}

BODY_ORDER = ("left_arm", "right_arm", "left_leg", "right_leg", "upper_body", "lower_body")
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


# ------------------------------------------------------------------ helpers
class UploadError(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message, self.field = message, field


def region_of(joint: str) -> str:
    """Map a joint / body-part name to a dashboard region."""
    j = (joint or "").lower()
    side = "left" if "left" in j else "right" if "right" in j else None
    if side and any(k in j for k in ("elbow", "wrist", "shoulder", "arm")):
        return f"{side}_arm"
    if side and any(k in j for k in ("knee", "ankle", "hip", "leg", "foot")):
        return f"{side}_leg"
    return "other"


def check_video(path: Path, field: str) -> None:
    """Light readability + duration check. Deep validation belongs to Module 2."""
    if cv2 is None:
        log.warning("OpenCV not installed: skipping server-side video validation.")
        return
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise UploadError("This file couldn't be read as a video. Try re-exporting it as MP4.", field)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = frames / fps if fps and fps > 0 and frames and frames > 0 else 0.0
        if duration == 0.0:  # some WebM files have no metadata: fall back to reading a frame
            ok, _ = cap.read()
            if not ok:
                raise UploadError("This video appears to be empty or corrupted.", field)
            return
        if duration < config.MIN_DURATION_S:
            raise UploadError(f"This video is only {duration:.1f}s long. Use at least "
                              f"{config.MIN_DURATION_S:.0f} seconds.", field)
        if duration > config.MAX_DURATION_S:
            raise UploadError(f"This video is {duration:.0f}s long. The limit is "
                              f"{config.MAX_DURATION_S:.0f} seconds.", field)
    finally:
        cap.release()


class JobStore:
    """In-memory job registry, mirrored to outputs/<id>/status.json so results survive restarts."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _persist(self, job: dict) -> None:
        d = self.output_dir / job["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "status.json").write_text(json.dumps(job), encoding="utf-8")

    def create(self, job_id: str, reference: Path, learner: Path) -> dict:
        job = {"id": job_id, "status": "queued", "stage": None, "stage_index": -1,
               "message": "Waiting to start", "error": None, "error_kind": None,
               "reference_path": str(reference), "learner_path": str(learner),
               "created": time.time(), "updated": time.time()}
        with self._lock:
            self._jobs[job_id] = job
        self._persist(job)
        return dict(job)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            job["updated"] = time.time()
            snapshot = dict(job)
        self._persist(snapshot)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return dict(job)
        f = self.output_dir / job_id / "status.json"
        if not f.exists():
            return None
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if job.get("status") in ("queued", "running"):   # server restarted mid-run
            job.update(status="error", error_kind="internal",
                       error="The server restarted while this analysis was running. "
                             "Please upload the videos again.")
        return job


def status_payload(job: dict) -> dict:
    idx, status = job.get("stage_index", -1), job["status"]
    stages = []
    for i, s in enumerate(config.STAGES):
        if status == "done" or i < idx:
            state = "done"
        elif i == idx:
            state = "error" if status == "error" else "active"
        else:
            state = "pending"
        stages.append({"key": s["key"], "state": state})
    return {"id": job["id"], "status": status, "stage": job.get("stage"),
            "stage_index": idx, "stage_count": len(STAGE_KEYS), "stages": stages,
            "message": job.get("message"), "error": job.get("error"),
            "error_kind": job.get("error_kind"),
            "redirect": f"/dashboard/{job['id']}" if status == "done" else None}


def load_results(output_dir: Path, job_id: str) -> dict | None:
    f = Path(output_dir) / job_id / "results.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def build_report(results: dict) -> dict:
    """Shape raw results into what the dashboard / comparison templates need."""
    analysis = results.get("analysis", {})
    viz = results.get("visualization") or {}
    meta = results.get("meta") or {}

    errors = sorted((dict(e) for e in analysis.get("errors", [])),
                    key=lambda e: e.get("timestamp", 0))
    for i, e in enumerate(errors):
        e["index"] = i
        e["region"] = region_of(e.get("joint", ""))

    body_scores = [(k, analysis["body_scores"][k]) for k in BODY_ORDER
                   if k in analysis.get("body_scores", {})]

    distribution = viz.get("error_distribution")
    if not distribution:
        distribution = {}
        for e in errors:
            distribution[e["region"]] = distribution.get(e["region"], 0) + 1

    ranked = sorted(errors, key=lambda e: (-SEVERITY_RANK.get(e.get("severity"), 0),
                                           -(e.get("deviation") or 0)))
    suggestions, seen = [], set()
    for e in ranked:
        text = e.get("suggestion")
        if text and text not in seen:
            seen.add(text)
            suggestions.append(e)
        if len(suggestions) == 5:
            break

    duration = meta.get("reference_duration") or (max((e["timestamp"] for e in errors), default=0) + 2)

    return {
        "analysis": {**analysis, "errors": errors},
        "meta": meta,
        "viz": viz,
        "errors": errors,
        "body_scores": body_scores,
        "distribution": distribution,
        "suggestions": suggestions,
        "duration": duration,
        "counts": {"total": len(errors),
                   "high": sum(1 for e in errors if e.get("severity") == "high"),
                   "medium": sum(1 for e in errors if e.get("severity") == "medium"),
                   "low": sum(1 for e in errors if e.get("severity") == "low")},
    }


# ---------------------------------------------------------------- the app
def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.SECRET_KEY,
        UPLOAD_DIR=config.UPLOAD_DIR,
        OUTPUT_DIR=config.OUTPUT_DIR,
        MAX_CONTENT_LENGTH=2 * config.MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024,
        ENABLE_DEMO=config.ENABLE_DEMO,
    )
    if overrides:
        app.config.update(overrides)
    for key in ("UPLOAD_DIR", "OUTPUT_DIR"):
        app.config[key] = Path(app.config[key])
        app.config[key].mkdir(parents=True, exist_ok=True)

    store = JobStore(app.config["OUTPUT_DIR"])
    app.extensions["jobs"] = store

    # ---- template helpers
    @app.template_filter("label")
    def label_filter(value: str) -> str:
        return str(value or "").replace("_", " ").title()

    @app.template_filter("mmss")
    def mmss_filter(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0))
        return f"{int(seconds // 60)}:{seconds % 60:04.1f}"

    @app.template_filter("tone")
    def tone_filter(score: float) -> str:
        return "ok" if score >= 80 else "warn" if score >= 60 else "err"

    @app.template_filter("num")
    def num_filter(value: float) -> str:
        text = f"{float(value):.1f}"
        return text[:-2] if text.endswith(".0") else text

    @app.context_processor
    def inject_globals():
        return {"demo_enabled": app.config["ENABLE_DEMO"]}

    # ---- pages
    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/upload")
    def upload():
        limits = {"extensions": list(config.ALLOWED_EXTENSIONS),
                  "max_mb": config.MAX_UPLOAD_MB,
                  "min_duration": config.MIN_DURATION_S,
                  "max_duration": config.MAX_DURATION_S,
                  "recommended": list(config.RECOMMENDED_DURATION_S)}
        return render_template("upload.html", limits=limits)

    @app.get("/processing/<job_id>")
    def processing(job_id: str):
        job = _job_or_404(job_id)
        if job["status"] == "done":
            return redirect(url_for("dashboard", job_id=job_id))
        return render_template("processing.html", job_id=job_id, stages=config.STAGES)

    @app.get("/dashboard/<job_id>")
    def dashboard(job_id: str):
        job = _job_or_404(job_id)
        results = load_results(app.config["OUTPUT_DIR"], job_id)
        if job["status"] != "done" or results is None:
            return redirect(url_for("processing", job_id=job_id))
        return _render_report("dashboard.html", job_id, results, sample=False)

    @app.get("/comparison/<job_id>")
    def comparison(job_id: str):
        job = _job_or_404(job_id)
        results = load_results(app.config["OUTPUT_DIR"], job_id)
        if job["status"] != "done" or results is None:
            return redirect(url_for("processing", job_id=job_id))
        return _render_report("comparison.html", job_id, results, sample=False)

    @app.get("/demo/dashboard")
    def demo_dashboard():
        _require_demo()
        return _render_report("dashboard.html", "demo", sample_data.build_sample_results(), sample=True)

    @app.get("/demo/comparison")
    def demo_comparison():
        _require_demo()
        return _render_report("comparison.html", "demo", sample_data.build_sample_results(), sample=True)

    # ---- API
    @app.post("/api/upload")
    def api_upload():
        files = {slot: request.files.get(slot) for slot in ("reference", "learner")}
        for slot, f in files.items():
            if f is None or not f.filename:
                return _upload_error(f"Please add your {SLOT_LABELS[slot]} video.", slot)

        job_id = uuid.uuid4().hex[:12]
        job_dir = app.config["UPLOAD_DIR"] / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        saved: dict[str, Path] = {}
        try:
            for slot, f in files.items():
                ext = Path(f.filename).suffix.lower().lstrip(".")
                if ext not in config.ALLOWED_EXTENSIONS:
                    raise UploadError(f".{ext or '?'} isn't supported. Use: "
                                      + ", ".join(config.ALLOWED_EXTENSIONS) + ".", slot)
                dest = job_dir / f"{slot}.{ext}"
                f.save(dest)
                if dest.stat().st_size == 0:
                    raise UploadError("This file is empty.", slot)
                check_video(dest, slot)
                saved[slot] = dest
        except UploadError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            return _upload_error(exc.message, exc.field)

        store.create(job_id, saved["reference"], saved["learner"])
        threading.Thread(target=_worker, args=(app, job_id), daemon=True).start()
        return jsonify({"job_id": job_id, "redirect": url_for("processing", job_id=job_id)}), 202

    @app.get("/api/status/<job_id>")
    def api_status(job_id: str):
        return jsonify(status_payload(_job_or_404(job_id)))

    @app.get("/api/results/<job_id>")
    def api_results(job_id: str):
        results = load_results(app.config["OUTPUT_DIR"], _valid_id(job_id))
        if results is None:
            abort(404)
        return jsonify(results)

    @app.get("/api/landmarks/<job_id>")
    def api_landmarks(job_id: str):
        return send_from_directory(app.config["OUTPUT_DIR"] / _valid_id(job_id), "landmarks.json",
                                   mimetype="application/json", max_age=0)

    @app.get("/media/<job_id>/<name>")
    def media(job_id: str, name: str):
        """Serve source videos and the annotated MP4 (supports HTTP range for seeking)."""
        job_id = _valid_id(job_id)
        if name == "annotated":
            folder, filename = app.config["OUTPUT_DIR"] / job_id, "comparison.mp4"
        elif name in ("reference", "learner"):
            folder = app.config["UPLOAD_DIR"] / job_id
            matches = sorted(folder.glob(f"{name}.*")) if folder.is_dir() else []
            if not matches:
                abort(404)
            filename = matches[0].name
        else:
            abort(404)
        return send_from_directory(folder, filename, conditional=True, max_age=0)

    # ---- internals
    def _valid_id(job_id: str) -> str:
        if not JOB_ID_RE.match(job_id):
            abort(404)
        return job_id

    def _job_or_404(job_id: str) -> dict:
        job = store.get(_valid_id(job_id))
        if job is None:
            abort(404)
        return job

    def _require_demo() -> None:
        if not app.config["ENABLE_DEMO"]:
            abort(404)

    def _upload_error(message: str, field: str | None):
        return jsonify({"error": message, "field": field}), 400

    def _render_report(template: str, job_id: str, results: dict, sample: bool):
        report = build_report(results)
        if sample:
            urls = {"dashboard": url_for("demo_dashboard"), "comparison": url_for("demo_comparison"),
                    "landmarks": None}
            media_urls: dict[str, str | None] = {"reference": None, "learner": None, "annotated": None}
        else:
            out, up = app.config["OUTPUT_DIR"] / job_id, app.config["UPLOAD_DIR"] / job_id
            has_lm = (out / "landmarks.json").exists()
            urls = {"dashboard": url_for("dashboard", job_id=job_id),
                    "comparison": url_for("comparison", job_id=job_id),
                    "landmarks": url_for("api_landmarks", job_id=job_id) if has_lm else None}
            media_urls = {
                "reference": url_for("media", job_id=job_id, name="reference") if list(up.glob("reference.*")) else None,
                "learner": url_for("media", job_id=job_id, name="learner") if list(up.glob("learner.*")) else None,
                "annotated": url_for("media", job_id=job_id, name="annotated") if (out / "comparison.mp4").exists() else None,
            }
        # one JSON blob for the page scripts
        page_data = {
            "errors": report["errors"],
            "alignment": report["analysis"].get("alignment", []),
            "distribution": report["distribution"],
            "duration": report["duration"],
            "sample_fps": report["meta"].get("sample_fps", config.SAMPLE_FPS),
            "video_fps": report["viz"].get("video_fps"),
            "media": media_urls,
            "urls": urls,
            "is_sample": sample,
        }
        return render_template(template, report=report, media=media_urls, urls=urls,
                               page_data=page_data, is_sample=sample, job_id=job_id)

    # ---- errors
    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        if request.path.startswith(("/api/", "/media/")):
            return jsonify({"error": exc.description or exc.name}), exc.code
        return render_template("error.html", code=exc.code, name=exc.name,
                               message=exc.description), exc.code

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify({"error": f"Upload too large. Each video can be up to "
                                 f"{config.MAX_UPLOAD_MB} MB."}), 413

    return app


def _worker(app: Flask, job_id: str) -> None:
    """Background thread: run the pipeline and record progress / result / error."""
    store: JobStore = app.extensions["jobs"]
    job = store.get(job_id)
    job_dir = Path(app.config["OUTPUT_DIR"]) / job_id

    def on_progress(stage_key: str, message: str) -> None:
        store.update(job_id, stage=stage_key, stage_index=STAGE_KEYS.index(stage_key), message=message)

    store.update(job_id, status="running", message="Starting analysis")
    try:
        result = pipeline.run_pipeline(Path(job["reference_path"]), Path(job["learner_path"]),
                                       job_dir, progress=on_progress)
        (job_dir / "results.json").write_text(json.dumps(result), encoding="utf-8")
        store.update(job_id, status="done", stage="complete",
                     stage_index=len(STAGE_KEYS), message="Analysis complete")
    except pipeline.PipelineUnavailable as exc:
        store.update(job_id, status="error", error_kind="unavailable", error=str(exc))
    except pipeline.PipelineError as exc:
        store.update(job_id, status="error", error_kind="analysis", error=str(exc))
    except Exception:  # never leave a job stuck in "running"
        log.exception("Job %s crashed", job_id)
        store.update(job_id, status="error", error_kind="internal",
                     error="Something went wrong while analysing. Check the server log for details.")


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, host="127.0.0.1", port=5000)
