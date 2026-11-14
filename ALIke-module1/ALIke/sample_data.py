"""Clearly-labelled SAMPLE data for frontend development (/demo pages only).

This is NOT analysis output. It is never used for real jobs and the demo pages
carry a visible "Sample data" banner.
"""
from __future__ import annotations

SAMPLE_FPS = 10
_DURATION = 15.0


def _alignment() -> list[list[int]]:
    """A gently warped path: the learner runs ~5% slower, then catches up."""
    n = int(_DURATION * SAMPLE_FPS)
    path = []
    for i in range(n):
        j = round(i * 1.05) if i < 100 else round(i * 1.05 - (i - 100) * 0.1)
        path.append([i, max(0, min(n - 1, j))])
    return path


def build_sample_results() -> dict:
    errors = [
        {"timestamp": 1.8, "reference_frame": 18, "learner_frame": 19, "joint": "left_knee",
         "deviation": 17.0, "severity": "low", "reference_value": 142, "learner_value": 159, "unit": "°",
         "suggestion": "Bend your left knee a little further to match the reference."},
        {"timestamp": 4.0, "reference_frame": 40, "learner_frame": 42, "joint": "right_elbow",
         "deviation": 32.0, "severity": "high", "reference_value": 118, "learner_value": 86, "unit": "°",
         "suggestion": "Raise your right forearm slightly to better match the reference."},
        {"timestamp": 6.3, "reference_frame": 63, "learner_frame": 66, "joint": "shoulders",
         "deviation": 21.0, "severity": "medium", "reference_value": 4, "learner_value": 25, "unit": "°",
         "suggestion": "Level your shoulders with the reference."},
        {"timestamp": 8.7, "reference_frame": 87, "learner_frame": 91, "joint": "right_knee",
         "deviation": 28.0, "severity": "medium", "reference_value": 128, "learner_value": 156, "unit": "°",
         "suggestion": "Bend your right knee further."},
        {"timestamp": 11.2, "reference_frame": 112, "learner_frame": 117, "joint": "right_elbow",
         "deviation": 44.0, "severity": "high", "reference_value": 95, "learner_value": 51, "unit": "°",
         "suggestion": "Open your right elbow more; it is bending too far."},
        {"timestamp": 13.4, "reference_frame": 134, "learner_frame": 139, "joint": "left_shoulder",
         "deviation": 16.0, "severity": "low", "reference_value": 88, "learner_value": 72, "unit": "°",
         "suggestion": "Lift your left arm a little higher."},
    ]
    return {
        "analysis": {
            "overall_score": 82.5,
            "timing_score": 74.0,
            "body_scores": {"left_arm": 85, "right_arm": 72, "left_leg": 90,
                            "right_leg": 80, "upper_body": 79, "lower_body": 86},
            "errors": errors,
            "alignment": _alignment(),
        },
        "visualization": {
            "error_distribution": {"left_arm": 1, "right_arm": 2, "left_leg": 1, "right_leg": 1, "other": 1},
        },
        "meta": {"sample_fps": SAMPLE_FPS, "reference_duration": _DURATION,
                 "learner_duration": _DURATION, "has_landmarks": False, "is_sample": True},
    }
