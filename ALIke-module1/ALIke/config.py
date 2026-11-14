"""Shared configuration for ALIke.

Everything tunable lives here so every module reads the same values.
Paths are built with pathlib relative to the project root (no absolute paths).
"""
from __future__ import annotations

import os
from pathlib import Path

# ----------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"           # original videos, one folder per job
OUTPUT_DIR = BASE_DIR / "outputs"           # results, landmarks, annotated MP4, per job
STATIC_OUTPUT_DIR = BASE_DIR / "static" / "output"
MODEL_PATH = BASE_DIR / "models" / "pose_landmarker.task"

# ------------------------------------------------------------ Flask / app
SECRET_KEY = os.environ.get("ALIKE_SECRET_KEY", "dev-only-change-me")
# Sample report pages (/demo/...) use clearly labelled sample data.
# Set ALIKE_DEMO=0 to switch them off.
ENABLE_DEMO = os.environ.get("ALIKE_DEMO", "1") == "1"

# ---------------------------------------------------------------- uploads
ALLOWED_EXTENSIONS = ("mp4", "mov", "avi", "webm", "mkv")
MAX_UPLOAD_MB = 150                         # per video
MIN_DURATION_S = 3.0                        # hard limits (rejected outside)
MAX_DURATION_S = 60.0
RECOMMENDED_DURATION_S = (10, 20)           # soft guidance only

# ------------------------------------------------------ processing (Module 2)
SAMPLE_FPS = 10
FRAME_MAX_SIZE = (640, 480)                 # (width, height), aspect ratio preserved
MIN_LANDMARK_CONFIDENCE = 0.5

# ---------------------------------- analysis defaults (Modules 3-4 may read these)
ANGLE_DEVIATION_THRESHOLDS = {"low": 15.0, "medium": 25.0, "high": 40.0}   # degrees
SCORE_WEIGHTS = {"position": 0.4, "angle": 0.4, "timing": 0.2}            # must sum to 1
DTW_WINDOW_RATIO = 0.3                      # Sakoe-Chiba band as a fraction of length

# ------------------------------------------------------- processing stages
# Single source of truth for the stage list shown on the processing page.
STAGES = (
    {"key": "preprocessing", "label": "Video preprocessing",
     "description": "Reading both videos and sampling frames"},
    {"key": "pose_detection", "label": "Human pose detection",
     "description": "Finding 33 body landmarks in every sampled frame"},
    {"key": "normalization", "label": "Movement normalization",
     "description": "Making body size and position comparable"},
    {"key": "alignment", "label": "Temporal alignment",
     "description": "Matching moments in time with Dynamic Time Warping"},
    {"key": "comparison", "label": "Movement comparison",
     "description": "Measuring joint and body-part differences"},
    {"key": "error_detection", "label": "Error detection",
     "description": "Flagging deviations above the thresholds"},
    {"key": "feedback", "label": "Feedback generation",
     "description": "Writing corrections from the measured deviations"},
    {"key": "video_generation", "label": "Annotated video generation",
     "description": "Rendering the side-by-side comparison video"},
)
