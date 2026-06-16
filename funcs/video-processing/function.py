#!/usr/bin/env python3
"""Video processing — multi-resource victim (Experiment 2, interval-merge / C3).

Single-threaded, blocking. Exercises the three PureTime-tracked resources so their
co-tenant wait intervals OVERLAP in time (which is what interval-merge must handle):
  - generate a synthetic input video      → CPU + Block(write)
  - OpenCV grayscale conversion            → Block(read) + CPU + Block(write)
  - upload the grayscale result to MinIO   → Net-TX (+ Block read of the file)

VIDEO_FRAMES / FRAME_W / FRAME_H tune the workload size, which adjusts how much the
per-resource wait intervals overlap (the x-axis of the merge-vs-naive figure).
"""
import os
import time
import json
import cv2
import numpy as np

cv2.setNumThreads(1)  # single-thread (design: single-threaded victim)

FRAMES = int(os.environ.get("VIDEO_FRAMES", "300"))
W = int(os.environ.get("FRAME_W", "640"))
H = int(os.environ.get("FRAME_H", "480"))
WORK = os.environ.get("WORK_DIR", "/tmp/video_test")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://165.194.27.225:9000")
MINIO_AK = os.environ.get("MINIO_ACCESS_KEY", "minioadmincslab")
MINIO_SK = os.environ.get("MINIO_SECRET_KEY", "minioadmincslab")
BUCKET = os.environ.get("MINIO_BUCKET", "uploads")


def generate_input(path):
    """Synthetic input video (deterministic) → CPU + Block(write)."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(path, fourcc, 30, (W, H))
    rng = np.random.RandomState(0)
    base = rng.randint(0, 255, (H, W, 3), dtype=np.uint8)
    for i in range(FRAMES):
        frame = np.roll(base, i * 3, axis=1)  # cheap per-frame change (deterministic)
        vw.write(frame)
    vw.release()
    with open(path, "r+b") as f:
        os.fsync(f.fileno())
    return os.path.getsize(path)


def to_grayscale(src, dst):
    """Read → grayscale → write → Block(read) + CPU + Block(write)."""
    cap = cv2.VideoCapture(src)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(dst, fourcc, 30, (W, H), isColor=False)
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        vw.write(gray)
        n += 1
    cap.release()
    vw.release()
    with open(dst, "r+b") as f:
        os.fsync(f.fileno())
    return n, os.path.getsize(dst)


def upload(path, key):
    """Upload to MinIO → Net-TX."""
    import boto3
    from botocore.client import Config
    s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT,
                      aws_access_key_id=MINIO_AK, aws_secret_access_key=MINIO_SK,
                      config=Config(signature_version="s3v4"), region_name="us-east-1")
    t = time.perf_counter()
    s3.upload_file(path, BUCKET, key)
    return round((time.perf_counter() - t) * 1000, 2)


def main():
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(WORK, "input.mp4")
    dst = os.path.join(WORK, "gray.mp4")
    t0 = time.perf_counter()

    passes = int(os.environ.get("GRAYSCALE_PASSES", "1"))
    do_upload = os.environ.get("UPLOAD", "1") != "0"

    gen_t = time.perf_counter(); in_sz = generate_input(src); gen_ms = (time.perf_counter() - gen_t) * 1000
    # grayscale (read+CPU+write) — repeated PASSES times to make CPU+Block the dominant,
    # overlapping work (Exp2 interval-merge demonstrates CPU∩Block overlap; net upload is
    # out-of-scope TCP backoff so it is optional / not the merge driver).
    proc_t = time.perf_counter()
    nframes = out_sz = 0
    for p in range(passes):
        nframes, out_sz = to_grayscale(src, os.path.join(WORK, f"gray_{p}.mp4"))
    proc_ms = (time.perf_counter() - proc_t) * 1000
    dst = os.path.join(WORK, f"gray_{passes - 1}.mp4")
    up_ms = upload(dst, f"gray_{os.getpid()}.mp4") if do_upload else 0.0

    total_ms = (time.perf_counter() - t0) * 1000
    print(json.dumps({
        "frames": nframes, "resolution": f"{W}x{H}",
        "generate_ms": round(gen_ms, 2), "grayscale_ms": round(proc_ms, 2),
        "upload_ms": up_ms, "total_ms": round(total_ms, 2),
        "input_bytes": in_sz, "output_bytes": out_sz,
    }))


if __name__ == "__main__":
    main()
