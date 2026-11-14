"""Module 1 tests. Run from the project root:  pytest tests/ -v

The real analysis modules are replaced with a fake pipeline, so these tests check
Flask routing, validation, job handling and page rendering only.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module          # noqa: E402
import pipeline                   # noqa: E402
import sample_data                # noqa: E402

try:
    import cv2
    import numpy as np
except ImportError:               # pragma: no cover
    cv2 = None


def make_video(path: Path, seconds: float = 4.0, fps: int = 10) -> Path:
    """Write a tiny real video (MJPG/AVI plays everywhere OpenCV does)."""
    if cv2 is None:
        path.write_bytes(b"not-a-real-video" * 100)
        return path
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    for i in range(int(seconds * fps)):
        writer.write(np.full((48, 64, 3), i % 255, dtype=np.uint8))
    writer.release()
    return path


@pytest.fixture()
def client(tmp_path):
    flask_app = app_module.create_app({"TESTING": True, "UPLOAD_DIR": tmp_path / "up",
                                       "OUTPUT_DIR": tmp_path / "out"})
    return flask_app.test_client()


def fake_pipeline(ref, lrn, job_dir, progress=None):
    for stage in app_module.STAGE_KEYS:
        progress(stage, f"doing {stage}")
    (Path(job_dir) / "comparison.mp4").write_bytes(b"x")
    return sample_data.build_sample_results()


def wait_for(client, job_id, want, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/status/{job_id}").get_json()
        if st["status"] in want:
            return st
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def upload(client, tmp_path, ref_name="ref.avi", lrn_name="me.avi"):
    ref, lrn = make_video(tmp_path / ref_name), make_video(tmp_path / lrn_name)
    return client.post("/api/upload", data={"reference": (ref.open("rb"), ref_name),
                                            "learner": (lrn.open("rb"), lrn_name)},
                       content_type="multipart/form-data")


# ------------------------------------------------------------------ pages
@pytest.mark.parametrize("path", ["/", "/upload", "/demo/dashboard", "/demo/comparison"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_unknown_job_is_404(client):
    assert client.get("/dashboard/abcdef123456").status_code == 404
    assert client.get("/api/status/not-valid").status_code == 404


def test_demo_dashboard_is_labelled_sample(client):
    html = client.get("/demo/dashboard").get_data(as_text=True)
    assert "Sample data" in html and "Right Elbow" in html


def test_demo_can_be_disabled(tmp_path):
    flask_app = app_module.create_app({"TESTING": True, "ENABLE_DEMO": False,
                                       "UPLOAD_DIR": tmp_path / "u", "OUTPUT_DIR": tmp_path / "o"})
    assert flask_app.test_client().get("/demo/dashboard").status_code == 404


# ----------------------------------------------------------------- upload
def test_upload_requires_both_files(client):
    res = client.post("/api/upload", data={}, content_type="multipart/form-data")
    assert res.status_code == 400 and res.get_json()["field"] == "reference"


def test_upload_rejects_bad_extension(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    ok = make_video(tmp_path / "ok.avi")
    res = client.post("/api/upload", data={"reference": (bad.open("rb"), "notes.txt"),
                                           "learner": (ok.open("rb"), "ok.avi")},
                      content_type="multipart/form-data")
    assert res.status_code == 400 and "isn't supported" in res.get_json()["error"]


@pytest.mark.skipif(cv2 is None, reason="OpenCV needed for server-side video check")
def test_upload_rejects_unreadable_video(client, tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 50)
    ok = make_video(tmp_path / "ok.avi")
    res = client.post("/api/upload", data={"reference": (ok.open("rb"), "ok.avi"),
                                           "learner": (junk.open("rb"), "junk.mp4")},
                      content_type="multipart/form-data")
    assert res.status_code == 400 and res.get_json()["field"] == "learner"


@pytest.mark.skipif(cv2 is None, reason="OpenCV needed for server-side video check")
def test_upload_rejects_too_short(client, tmp_path):
    short = make_video(tmp_path / "short.avi", seconds=1.0)
    ok = make_video(tmp_path / "ok.avi")
    res = client.post("/api/upload", data={"reference": (short.open("rb"), "short.avi"),
                                           "learner": (ok.open("rb"), "ok.avi")},
                      content_type="multipart/form-data")
    assert res.status_code == 400 and "only" in res.get_json()["error"]


# ------------------------------------------------------------ full job flow
def test_full_flow_with_fake_pipeline(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    res = upload(client, tmp_path)
    assert res.status_code == 202
    job_id = res.get_json()["job_id"]

    assert client.get(f"/processing/{job_id}").status_code in (200, 302)
    st = wait_for(client, job_id, {"done", "error"})
    assert st["status"] == "done" and st["redirect"] == f"/dashboard/{job_id}"
    assert all(s["state"] == "done" for s in st["stages"])

    dash = client.get(f"/dashboard/{job_id}")
    assert dash.status_code == 200 and b"82.5" in dash.data
    assert client.get(f"/comparison/{job_id}").status_code == 200
    assert client.get(f"/media/{job_id}/reference").status_code == 200
    assert client.get(f"/media/{job_id}/annotated").status_code == 200
    assert client.get(f"/media/{job_id}/secret").status_code == 404
    assert client.get(f"/api/results/{job_id}").get_json()["analysis"]["overall_score"] == 82.5


def test_pipeline_unavailable_is_reported_honestly(client, tmp_path):
    """With no real modules/ files, the job must fail clearly, not fabricate results."""
    res = upload(client, tmp_path)
    job_id = res.get_json()["job_id"]
    st = wait_for(client, job_id, {"done", "error"})
    assert st["status"] == "error" and st["error_kind"] == "unavailable"
    assert "modules" in st["error"]
    assert client.get(f"/dashboard/{job_id}").status_code == 302   # no results -> back to processing


def test_pipeline_error_is_reported(client, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise pipeline.PipelineError("No person was detected in the learner video.")
    monkeypatch.setattr(pipeline, "run_pipeline", boom)
    job_id = upload(client, tmp_path).get_json()["job_id"]
    st = wait_for(client, job_id, {"error"})
    assert st["error_kind"] == "analysis" and "No person" in st["error"]


# ---------------------------------------------------------------- helpers
def test_region_mapping():
    assert app_module.region_of("right_elbow") == "right_arm"
    assert app_module.region_of("left_knee") == "left_leg"
    assert app_module.region_of("shoulders") == "other"


def test_pipeline_to_jsonable_handles_numpy():
    import numpy as np
    out = pipeline.to_jsonable({"a": np.arange(3), "b": np.float32(1.5), "c": float("nan")})
    assert out == {"a": [0, 1, 2], "b": 1.5, "c": None}
