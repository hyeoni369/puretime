#!/usr/bin/env python3
"""Thumbnailer - Multi-resource benchmark adapted from SeBS"""

import os
import io
import time
import json
import urllib.request
from PIL import Image


def download_image(url: str) -> bytes:
    """Download image from URL"""
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def resize_image(image_bytes: bytes, width: int, height: int) -> bytes:
    """Resize image to specified dimensions"""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((width, height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=85)
    return output.getvalue()


def save_image(image_bytes: bytes, filepath: str):
    """Save image to disk with fsync"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(image_bytes)
        f.flush()
        os.fsync(f.fileno())


def main():
    # Configuration
    iterations = int(os.environ.get('ITERATIONS', '5'))
    width = int(os.environ.get('THUMB_WIDTH', '200'))
    height = int(os.environ.get('THUMB_HEIGHT', '200'))
    work_dir = os.environ.get('WORK_DIR', '/tmp/thumbnailer_test')

    # Use Lorem Picsum for random images (different sizes for variety)
    image_sizes = [800, 1024, 1280, 1600, 1920]

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        iter_start = time.perf_counter()

        # Vary image size each iteration
        img_size = image_sizes[i % len(image_sizes)]
        url = f"https://picsum.photos/{img_size}/{img_size}"
        output_path = os.path.join(work_dir, f"thumb_{i}.jpg")

        # Phase 1: Download (Network I/O)
        download_start = time.perf_counter()
        image_bytes = download_image(url)
        download_time = time.perf_counter() - download_start
        original_size = len(image_bytes)

        # Phase 2: Resize (CPU)
        resize_start = time.perf_counter()
        thumb_bytes = resize_image(image_bytes, width, height)
        resize_time = time.perf_counter() - resize_start

        # Phase 3: Save (Block I/O)
        save_start = time.perf_counter()
        save_image(thumb_bytes, output_path)
        save_time = time.perf_counter() - save_start

        iter_time = time.perf_counter() - iter_start

        results.append({
            'iteration': i + 1,
            'download_time_ms': round(download_time * 1000, 2),
            'resize_time_ms': round(resize_time * 1000, 2),
            'save_time_ms': round(save_time * 1000, 2),
            'total_time_ms': round(iter_time * 1000, 2),
            'original_size_bytes': original_size,
            'thumb_size_bytes': len(thumb_bytes)
        })

    total_time = time.perf_counter() - total_start

    print(json.dumps({
        'iterations': iterations,
        'thumb_dimensions': f"{width}x{height}",
        'total_elapsed_ms': round(total_time * 1000, 2),
        'results': results
    }))


if __name__ == "__main__":
    main()
