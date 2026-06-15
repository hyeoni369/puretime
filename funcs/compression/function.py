#!/usr/bin/env python3
"""Compression - Block I/O benchmark adapted from SeBS"""

import os
import time
import json
import shutil
import zipfile


def generate_input_files(data_dir: str, num_files: int, file_size_mb: int):
    """Generate random input files for compression"""
    os.makedirs(data_dir, exist_ok=True)
    for i in range(num_files):
        filepath = os.path.join(data_dir, f"input_{i}.bin")
        with open(filepath, 'wb') as f:
            # Write random-ish data (not compressible)
            f.write(os.urandom(file_size_mb * 1024 * 1024))
            f.flush()
            os.fsync(f.fileno())  # Force disk write
    return data_dir


def compress_directory(input_dir: str, output_path: str) -> int:
    """Archive directory to ZIP. COMPRESS_METHOD=stored → 무압축(I/O-bound, CPU 최소);
    'deflate'(기본) → DEFLATE(CPU-heavy). I/O 비율을 키워 block inflation을 높이려면 stored."""
    method = (zipfile.ZIP_STORED if os.environ.get('COMPRESS_METHOD', 'deflate') == 'stored'
              else zipfile.ZIP_DEFLATED)
    archive_path = output_path if output_path.endswith('.zip') else output_path + '.zip'
    with zipfile.ZipFile(archive_path, 'w', method) as zf:
        for root, _, files in os.walk(input_dir):
            for name in files:
                fp = os.path.join(root, name)
                zf.write(fp, os.path.relpath(fp, input_dir))
    # Force sync to disk
    with open(archive_path, 'r+b') as f:
        os.fsync(f.fileno())
    return os.path.getsize(archive_path)


def main():
    # Configuration
    num_files = int(os.environ.get('NUM_FILES', '5'))
    file_size_mb = int(os.environ.get('FILE_SIZE_MB', '10'))
    iterations = int(os.environ.get('ITERATIONS', '3'))
    work_dir = os.environ.get('WORK_DIR', '/tmp/compression_test')

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        iter_start = time.perf_counter()

        # Clean work directory
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)

        input_dir = os.path.join(work_dir, 'input')
        output_path = os.path.join(work_dir, f'archive_{i}.zip')

        # Phase 1: Generate input files (write I/O)
        gen_start = time.perf_counter()
        generate_input_files(input_dir, num_files, file_size_mb)
        gen_time = time.perf_counter() - gen_start

        # Phase 2: Compress (read I/O + CPU + write I/O)
        compress_start = time.perf_counter()
        archive_size = compress_directory(input_dir, output_path)
        compress_time = time.perf_counter() - compress_start

        iter_time = time.perf_counter() - iter_start

        results.append({
            'iteration': i + 1,
            'generate_time_ms': round(gen_time * 1000, 2),
            'compress_time_ms': round(compress_time * 1000, 2),
            'total_time_ms': round(iter_time * 1000, 2),
            'input_size_mb': num_files * file_size_mb,
            'archive_size_bytes': archive_size
        })

    total_time = time.perf_counter() - total_start

    print(json.dumps({
        'iterations': iterations,
        'num_files': num_files,
        'file_size_mb': file_size_mb,
        'total_elapsed_ms': round(total_time * 1000, 2),
        'results': results
    }))


if __name__ == "__main__":
    main()
