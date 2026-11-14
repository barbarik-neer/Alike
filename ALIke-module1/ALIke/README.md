# ALIke — AI-Powered Dance Movement Analysis and Correction

Compares a reference dance video with a learner video (MediaPipe pose, normalization, DTW) and shows where and how the movement differs.

**This README covers Module 1: the Flask app and frontend.** Modules 2–5 plug in through `pipeline.py`.

## Run

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

- `/demo/dashboard` and `/demo/comparison` show a **clearly labelled sample report** so the UI can be developed before the analysis modules exist. Turn off with `ALIKE_DEMO=0`.
- Until Modules 2–5 exist, a real upload fails on the processing page with "The analysis modules aren't connected yet", listing which `modules/*.py` files or functions are missing. No fake results are ever produced.

Optional: install `ffmpeg`. OpenCV's MP4s usually won't play in browsers; `pipeline.py` re-encodes the annotated video to H.264 when ffmpeg is on your PATH.

## Test

```bash
pytest tests/ -v
```

## The contract with Modules 2–5

`pipeline.py` calls one function per stage. If a teammate's names differ, edit the `CONTRACT` table at the top of `pipeline.py` (one line each).

| Stage | Function | Returns |
|---|---|---|
| 1 | `video_processor.probe_video(path)` | `video_info` dict (width, height, duration, fps); raise on unreadable video |
| 2 | `pose_detector.extract_pose_data(path, sample_fps=10)` | `pose_data` (`landmarks` (n,33,3), `confidence` (n,33), `timestamps` (n,), `frame_indices`, `video_info`) |
| 3 | `normalizer.normalize_pose_data(pose_data)` | `normalized_data` |
| 4 | `movement_analyzer.align_sequences(ref_norm, lrn_norm)` | DTW path `[(ref_idx, lrn_idx), ...]` |
| 5 | `movement_analyzer.compare_movements(ref_norm, lrn_norm, alignment)` | `{"overall_score", "timing_score", "body_scores", "deviations"}` |
| 6 | `error_detector.detect_errors(comparison, alignment)` | list of error dicts |
| 7 | `feedback_generator.generate_feedback(errors)` | same errors, each with `"suggestion"` |
| 8 | `video_generator.generate_comparison_video(reference_video, learner_video, reference_pose, learner_pose, analysis, output_path)` | `visualization_data` dict |

Rules the frontend relies on:

- `body_scores` keys: `left_arm, right_arm, left_leg, right_leg, upper_body, lower_body` (missing keys are simply not shown).
- Each error: `timestamp` (s), `reference_frame`, `learner_frame` (row indices into the sampled arrays), `joint`, `deviation`, `severity` (`low|medium|high`), `suggestion`. Optional: `reference_value`, `learner_value`, `unit` (default `°`) fill the correction panel.
- `joint` names that get highlighted on the skeleton: `left/right_` + `shoulder, elbow, wrist, hip, knee, ankle`, plus `shoulders, hips, left/right_arm, left/right_leg, upper_body, lower_body`.
- `landmarks[..., :2]` are normalized image coordinates (0–1). If pixels are stored, they are divided by `video_info` width/height.
- `alignment` indices refer to the same sampled rows as `timestamps`.
- Optional in `visualization_data`: `error_distribution`, `video_fps` (fps of the annotated MP4, defaults to the sampling fps).

## Layout

```
app.py              Flask routes, uploads, background jobs, status API
config.py           paths, limits, thresholds, stage list
pipeline.py         calls modules 2-5, validates output, writes landmarks.json
sample_data.py      sample data for /demo pages only
templates/, static/ the frontend (no JS framework; Plotly.js from CDN)
uploads/<job>/      original videos        outputs/<job>/  results.json, landmarks.json, comparison.mp4
tests/test_app.py   Module 1 tests
```

## Notes and limits

- Jobs run in a background thread in the Flask process; fine for a prototype, use a task queue for production. Uploads and outputs are not cleaned up automatically.
- Scores measure similarity between two recordings, not dance ability.
- Plotly and the Manrope font load from CDNs; the page still works without them, minus charts.
