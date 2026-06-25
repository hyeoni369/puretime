#!/usr/bin/env python3
"""Compression - Block I/O benchmark adapted from SeBS"""

import os
import time
import json
import shutil
import zipfile
import random
import mmap


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


def raw_block_io():
    """O_DIRECT random-write victim — block ~900ms에서 insert→issue 큐 적체를 살린다.

    sequential store-zip은 block 레이어 merge로 request 개수가 적어, 짧으면(I/O량↓) insert→issue
    큐잉이 소멸하고 경합이 device-internal(issue→complete, 측정 범위 밖)로 숨어 붕괴한다(파일럿 25%).
    이 모드는 작은 random write를 많이 날려 *request 개수*를 신호로 만든다: filled HDD + queue_depth=2
    에서 흩어진 sector를 때려 seek로 device 점유↑ → stressor 요청 뒤에서 victim의 issue가 지연 → wait
    포착. O_DIRECT로 page cache 우회(매 write = 동기 insert, victim cgroup 귀속 결정적). fsync는 끝에
    1회만(빈번 fsync = 드레인 배리어 → 적체 방해). 총 바이트(~48MB)는 작아 900ms에 끝나되 개수는 큼."""
    bs = int(os.environ.get('BLOCK_BS', '32768'))            # 32KB (4096 정렬 배수)
    io_ops = int(os.environ.get('IO_OPS', '1500'))            # write 횟수 = insert request 개수
    work_dir = os.environ.get('WORK_DIR', '/tmp/compression_test')
    os.makedirs(work_dir, exist_ok=True)
    backing = os.path.join(work_dir, 'blockio_backing.bin')
    backing_size = int(os.environ.get('BACKING_SIZE_MB', '1024')) * 1024 * 1024
    if not os.path.exists(backing) or os.path.getsize(backing) < backing_size:
        with open(backing, 'wb') as f:
            f.truncate(backing_size)
    n_blocks = backing_size // bs
    buf = mmap.mmap(-1, bs)                                   # page-aligned 버퍼 (O_DIRECT 요구)
    buf.write(os.urandom(bs)); buf.seek(0)
    fd = os.open(backing, os.O_WRONLY | os.O_DIRECT)
    start = time.perf_counter()
    for _ in range(io_ops):
        off = random.randint(0, n_blocks - 1) * bs           # random offset (bs 정렬)
        os.pwrite(fd, buf, off)
    os.fsync(fd)
    os.close(fd)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "io_ops": io_ops, "bs": bs,
                      "total_elapsed_ms": round(elapsed_ms, 2)}))


def main():
    if os.environ.get('COMPRESS_METHOD') == 'raw_block':
        raw_block_io()
        return
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
