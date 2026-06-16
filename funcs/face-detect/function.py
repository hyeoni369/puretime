#!/usr/bin/env python3
"""Face-detect + sentiment victim — input-variance workload (Experiment 3, C5).

Compute scales monotonically with NUM_FACES:
  - an image holding N tiled faces is built (image area ∝ N),
  - Haar cascade `detectMultiScale` scans it (scan cost ∝ image area ∝ N),
  - a per-face "sentiment" compute runs N times.
So the *solo* makespan is a deterministic, increasing function of the input (# faces),
which is exactly the input-variance that Experiment 3 stresses PureTime with.

Env:
  NUM_FACES        # input level: 0,1,5,10,15,30 (the experiment sweep)
  SENTIMENT_ITERS  # per-face compute units (tune so N=30 takes a few seconds)
  FACE_IMG         # path to a real frontal-face image, tiled to make N faces
"""
import os
import time
import json
import cv2
import numpy as np

cv2.setNumThreads(1)  # single-thread (design: single-threaded victim, single-core pin)

NUM_FACES = int(os.environ.get("NUM_FACES", "5"))
SENTIMENT_ITERS = int(os.environ.get("SENTIMENT_ITERS", "60"))
FACE_IMG = os.environ.get("FACE_IMG", "/app/face.jpg")
TILE = 160  # each face tile is TILE x TILE px

_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def build_image(n):
    """Tile a real face image n times into a grid → image with n detectable faces.
    Image area grows ∝ n, so the detection scan cost grows ∝ n."""
    if n <= 0:
        return np.zeros((TILE, TILE, 3), dtype=np.uint8)
    face = cv2.imread(FACE_IMG)
    if face is None:
        # deterministic fallback if the bundled face image is missing: a textured tile
        # (detection may find 0, but scan + sentiment still scale with n).
        ramp = np.linspace(0, 255, TILE, dtype=np.uint8)
        face = cv2.cvtColor(np.tile(ramp, (TILE, 1)), cv2.COLOR_GRAY2BGR)
    face = cv2.resize(face, (TILE, TILE))
    cols = int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    canvas = np.zeros((rows * TILE, cols * TILE, 3), dtype=np.uint8)
    for i in range(n):
        r, c = divmod(i, cols)
        canvas[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE] = face
    return canvas


def sentiment_score(region):
    """Per-face sentiment proxy: deterministic CPU-bound compute on a face tile.
    Uses Sobel gradients + trig (no large working set → friendly to a register/L1
    CPU stressor; on-CPU IPC dilation stays out of scope)."""
    g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
    acc = 0.0
    for _ in range(SENTIMENT_ITERS):
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.sqrt(gx * gx + gy * gy)
        acc += float(np.mean(mag) + np.sin(acc))
    return acc


def main():
    t0 = time.perf_counter()
    img = build_image(NUM_FACES)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # face detection: scans the whole image at multiple scales → cost ∝ image area ∝ N
    faces = _cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
    )
    detect_t = time.perf_counter()

    # sentiment per intended face (N), each on its tile region (deterministic, independent
    # of detection success so the per-face compute always scales with the input level).
    cols = int(np.ceil(np.sqrt(NUM_FACES))) if NUM_FACES > 0 else 1
    total = 0.0
    for i in range(NUM_FACES):
        r, c = divmod(i, cols)
        region = img[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE]
        if region.size:
            total += sentiment_score(region)
    end = time.perf_counter()

    print(json.dumps({
        "num_faces": NUM_FACES,
        "faces_detected": int(len(faces)),
        "detect_ms": round((detect_t - t0) * 1000, 2),
        "sentiment_ms": round((end - detect_t) * 1000, 2),
        "total_ms": round((end - t0) * 1000, 2),
        "sentiment_acc": round(total, 4),
    }))


if __name__ == "__main__":
    main()
