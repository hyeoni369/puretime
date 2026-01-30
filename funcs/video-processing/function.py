#!/usr/bin/env python3
"""Video Processing - Multi-resource benchmark adapted from SeBS"""

import os
import time
import json
import subprocess
import urllib.request

# Sample video URLs (public domain / CC0)
SAMPLE_VIDEOS = [
    "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_5MB.mp4",
    "https://www.w3schools.com/html/mov_bbb.mp4",
]


def download_video(url: str, output_path: str) -> int:
    """Download video from URL"""
    print(f"Downloading video from {url} to {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
        with open(output_path, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    return len(data)


def video_to_gif(input_path: str, output_path: str, fps: int = 10, width: int = 320):
    """Convert video to GIF using ffmpeg"""
    # Generate palette for better quality
    palette_path = input_path + ".palette.png"

    # Step 1: Generate palette
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', f'fps={fps},scale={width}:-1:flags=lanczos,palettegen',
        palette_path
    ], capture_output=True, check=True)

    # Step 2: Create GIF with palette
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path, '-i', palette_path,
        '-lavfi', f'fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse',
        output_path
    ], capture_output=True, check=True)

    # Cleanup palette
    os.remove(palette_path)

    # Sync to disk
    with open(output_path, 'r+b') as f:
        os.fsync(f.fileno())

    return os.path.getsize(output_path)


def add_watermark(input_path: str, output_path: str, text: str = "PureTime"):
    """Add text watermark to video using ffmpeg"""
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', f"drawtext=text='{text}':fontsize=24:fontcolor=white:x=10:y=10",
        '-codec:a', 'copy',
        output_path
    ], capture_output=True, check=True)

    # Sync to disk
    with open(output_path, 'r+b') as f:
        os.fsync(f.fileno())

    return os.path.getsize(output_path)


def main():
    # Configuration
    iterations = int(os.environ.get('ITERATIONS', '3'))
    operation = os.environ.get('OPERATION', 'gif')  # 'gif' or 'watermark'
    work_dir = os.environ.get('WORK_DIR', '/tmp/video_test')
    video_url = os.environ.get('VIDEO_URL', SAMPLE_VIDEOS[0])

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        iter_start = time.perf_counter()

        input_path = os.path.join(work_dir, f"input_{i}.mp4")

        if operation == 'gif':
            output_path = os.path.join(work_dir, f"output_{i}.gif")
        else:
            output_path = os.path.join(work_dir, f"output_{i}.mp4")

        # Phase 1: Download (Network I/O)
        download_start = time.perf_counter()
        input_size = download_video(video_url, input_path)
        download_time = time.perf_counter() - download_start

        # Phase 2: Process (CPU + I/O)
        process_start = time.perf_counter()
        if operation == 'gif':
            output_size = video_to_gif(input_path, output_path)
        else:
            output_size = add_watermark(input_path, output_path)
        process_time = time.perf_counter() - process_start

        iter_time = time.perf_counter() - iter_start

        results.append({
            'iteration': i + 1,
            'download_time_ms': round(download_time * 1000, 2),
            'process_time_ms': round(process_time * 1000, 2),
            'total_time_ms': round(iter_time * 1000, 2),
            'input_size_bytes': input_size,
            'output_size_bytes': output_size
        })

    total_time = time.perf_counter() - total_start

    print(json.dumps({
        'iterations': iterations,
        'operation': operation,
        'total_elapsed_ms': round(total_time * 1000, 2),
        'results': results
    }))


if __name__ == "__main__":
    main()
