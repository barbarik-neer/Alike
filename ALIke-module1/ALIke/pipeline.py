"""ALIke pipeline — the integration layer between Flask (Module 1) and Modules 2-5.

Flask calls ``run_pipeline`` in a background thread. This file only *coordinates*:
it calls one function per stage, checks what comes back, and reports progress.
It contains no pose, maths or analysis logic.

THE CONTRACT
------------
Each stage maps to one function in ``modules/``. If a teammate's function has a
different name, change the one line in ``CONTRACT`` below.

  probe_video(path)                          -> dict   video_info (width, height, duration, fps); raise on unreadable video
  extract_pose_data(path, sample_fps)        -> dict   pose_data  (landmarks (n,33,3), confidence (n,33), timestamps (n,), ...)
  normalize_pose_data(pose_data)             -> dict   normalized_data
  align_sequences(ref_norm, lrn_norm)        -> list   [(ref_idx, lrn_idx), ...]   (DTW path)
  compare_movements(ref_norm, lrn_norm, alignment)
                                             -> dict   {"overall_score", "timing_score", "body_scores", "deviations", ...}
  detect_errors(comparison, alignment)       -> list   [{"timestamp", "reference_frame", "learner_frame", "joint",
                                                         "deviation", "severity", "description"}, ...]
  generate_feedback(errors)                  -> list   same errors, each with a "suggestion"
  generate_comparison_video(reference_video, learner_video, reference_pose, learner_pose,
                            analysis, output_path)
                                             -> dict   visualization_data (error_distribution, timeline, ...)

Optional extra keys the dashboard shows when present on each error:
  "reference_value", "learner_value", "unit"   (e.g. 120, 85, "°")

Landmark convention assumed for drawing live overlays in the browser:
  landmarks[..., 0:2] are normalised image coordinates (x, y in 0..1). If Module 2
  stores pixels instead, they are divided by video_info width/height here.
"""
from __future__ import annotations

import importlib
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import numpy as np

import config

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str], None]   # (stage_key, human message)

# name -> (module in modules/, function name)
CONTRACT: dict[str, tuple[str, str]] = {
    "probe_video": ("video_processor", "probe_video"),
    "extract_pose": ("pose_detector", "extract_pose_data"),
    "normalize": ("normalizer", "normalize_pose_data"),
    "align": ("movement_analyzer", "align_sequences"),
    "compare": ("movement_analyzer", "compare_movements"),
    "detect_errors": ("error_detector", "detect_errors"),
    "feedback": ("feedback_generator", "generate_feedback"),
    "render": ("video_generator", "generate_comparison_video"),
}

LABELS = {s["key"]: s["label"] for s in config.STAGES}


class PipelineUnavailable(RuntimeError):
    """One or more analysis modules are not implemented / importable yet."""


class PipelineError(RuntimeError):
    """The analysis ran but failed on this input (bad video, no person, ...)."""


# ------------------------------------------------------------------ helpers
def _resolve_all() -> dict[str, Callable[..., Any]]:
    """Import every contract function up front so we fail before doing any work."""
    fns: dict[str, Callable[..., Any]] = {}
    problems: list[str] = []
    for name, (module, func) in CONTRACT.items():
        try:
            mod = importlib.import_module(f"modules.{module}")
        except ImportError as exc:
            problems.append(f"modules/{module}.py can't be imported ({exc})")
            continue
        fn = getattr(mod, func, None)
        if not callable(fn):
            problems.append(f"modules/{module}.py has no function `{func}`")
            continue
        fns[name] = fn
    if problems:
        # de-duplicate while keeping order (one module can fail several entries)
        unique = list(dict.fromkeys(problems))
        raise PipelineUnavailable("Analysis modules aren't connected yet: " + "; ".join(unique))
    return fns


def to_jsonable(obj: Any) -> Any:
    """Recursively convert NumPy / Path / NaN values into JSON-safe Python values."""
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, np.generic):
        return to_jsonable(obj.item())
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _run_stage(key: str, progress: ProgressCallback, message: str,
               fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    progress(key, message)
    try:
        return fn(*args, **kwargs)
    except (PipelineError, PipelineUnavailable):
        raise
    except Exception as exc:  # module code failed: surface a readable message
        log.exception("Stage %s failed", key)
        raise PipelineError(f"{LABELS[key]} failed: {exc}") from exc


def _require_frames(pose: dict, who: str) -> None:
    lm = pose.get("landmarks") if isinstance(pose, dict) else None
    if lm is None or len(lm) == 0:
        raise PipelineError(f"No person was detected in the {who} video. "
                            "Make sure the full body is visible and well lit.")


def _validate_analysis(analysis: dict) -> None:
    for key in ("overall_score", "timing_score"):
        value = analysis.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise PipelineError(f"Analysis returned an invalid `{key}`.")
    if not isinstance(analysis.get("body_scores"), dict):
        raise PipelineError("Analysis returned no `body_scores`.")
    if not isinstance(analysis.get("errors"), list):
        raise PipelineError("Analysis returned no `errors` list.")
    if not isinstance(analysis.get("alignment"), list):
        raise PipelineError("Analysis returned no `alignment` path.")


def _landmark_payload(pose: dict) -> dict:
    """Compact landmarks for browser skeleton overlays: x, y (0..1) and visibility."""
    lm = np.asarray(pose["landmarks"], dtype=float)           # (n, 33, 3)
    ts = np.asarray(pose["timestamps"], dtype=float)
    xy = lm[..., :2].copy()
    info = pose.get("video_info") or {}
    width, height = info.get("width"), info.get("height")
    finite = xy[np.isfinite(xy)]
    if finite.size and np.max(np.abs(finite)) > 1.5 and width and height:
        xy[..., 0] /= width                                   # pixels -> 0..1
        xy[..., 1] /= height
    conf = pose.get("confidence")
    conf = np.asarray(conf, dtype=float) if conf is not None else np.ones(lm.shape[:2])
    bad = ~np.isfinite(xy).all(axis=-1)
    xy[bad] = 0.0
    conf = np.where(bad | ~np.isfinite(conf), 0.0, conf)
    points = np.concatenate([xy, conf[..., None]], axis=-1)   # (n, 33, 3)
    return {"timestamps": np.round(ts, 3), "points": np.round(points, 4)}


def _make_browser_playable(path: Path) -> None:
    """OpenCV's mp4v MP4s don't play in most browsers. Re-encode to H.264 if ffmpeg exists."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg not found: the annotated MP4 may not play in the browser.")
        return
    tmp = path.with_suffix(".h264.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)]
    try:
        subprocess.run(cmd, check=True, timeout=300)
        tmp.replace(path)
    except Exception as exc:  # keep the original file rather than failing the job
        log.warning("H.264 re-encode failed (%s); keeping original MP4.", exc)
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------- main entry
def run_pipeline(reference_path: Path, learner_path: Path, job_dir: Path,
                 progress: ProgressCallback | None = None) -> dict:
    """Run all stages. Returns a JSON-safe dict: {"analysis", "visualization", "meta"}.

    Raises PipelineUnavailable (modules missing) or PipelineError (bad input).
    """
    progress = progress or (lambda key, message: None)
    reference_path, learner_path, job_dir = Path(reference_path), Path(learner_path), Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    fns = _resolve_all()

    # 1. preprocessing
    ref_info = _run_stage("preprocessing", progress, "Reading the reference video",
                          fns["probe_video"], reference_path)
    lrn_info = _run_stage("preprocessing", progress, "Reading your performance video",
                          fns["probe_video"], learner_path)

    # 2. pose detection
    ref_pose = _run_stage("pose_detection", progress, "Detecting pose in the reference video",
                          fns["extract_pose"], reference_path, sample_fps=config.SAMPLE_FPS)
    _require_frames(ref_pose, "reference")
    lrn_pose = _run_stage("pose_detection", progress, "Detecting pose in your performance",
                          fns["extract_pose"], learner_path, sample_fps=config.SAMPLE_FPS)
    _require_frames(lrn_pose, "learner")

    # 3. normalization
    ref_norm = _run_stage("normalization", progress, "Normalizing the reference movement",
                          fns["normalize"], ref_pose)
    lrn_norm = _run_stage("normalization", progress, "Normalizing your movement",
                          fns["normalize"], lrn_pose)

    # 4. alignment
    alignment = _run_stage("alignment", progress, "Aligning both performances in time",
                           fns["align"], ref_norm, lrn_norm)
    if not alignment:
        raise PipelineError("Temporal alignment produced an empty path.")

    # 5. comparison
    comparison = _run_stage("comparison", progress, "Comparing aligned movements",
                            fns["compare"], ref_norm, lrn_norm, alignment)

    # 6. error detection
    errors = _run_stage("error_detection", progress, "Detecting movement errors",
                        fns["detect_errors"], comparison, alignment)

    # 7. feedback
    errors = _run_stage("feedback", progress, "Generating corrective feedback",
                        fns["feedback"], errors)

    analysis = {k: v for k, v in dict(comparison).items() if k != "deviations"}
    analysis["errors"] = list(errors)
    analysis["alignment"] = [list(map(int, pair)) for pair in alignment]
    _validate_analysis(analysis)

    # 8. annotated video
    video_path = job_dir / "comparison.mp4"
    visualization = _run_stage(
        "video_generation", progress, "Rendering the comparison video",
        fns["render"], reference_video=reference_path, learner_video=learner_path,
        reference_pose=ref_pose, learner_pose=lrn_pose, analysis=analysis,
        output_path=video_path)
    if not isinstance(visualization, dict):
        raise PipelineError("Video generation returned no visualization data.")
    if not video_path.exists():
        raise PipelineError("The annotated comparison video was not written.")
    _make_browser_playable(video_path)

    # landmarks for live overlays (kept out of results.json: it is large)
    landmarks = {
        "reference": _landmark_payload(ref_pose),
        "learner": _landmark_payload(lrn_pose),
    }
    (job_dir / "landmarks.json").write_text(
        __import__("json").dumps(to_jsonable(landmarks)), encoding="utf-8")

    visualization.pop("video_path", None)   # Flask serves the video itself

    meta = {
        "sample_fps": config.SAMPLE_FPS,
        "reference_duration": (ref_info or {}).get("duration"),
        "learner_duration": (lrn_info or {}).get("duration"),
        "has_landmarks": True,
        "is_sample": False,
    }
    return to_jsonable({"analysis": analysis, "visualization": visualization, "meta": meta})
