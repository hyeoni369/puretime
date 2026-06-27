#!/usr/bin/env python3
"""FaaSDom filesystem (block I/O victim) — HTTP handler / /proc 읽기 제거.

원본: FaaSDom python_filesystem — n개 소파일(각 size 바이트) write 후 read.
    for i in range(n): open(.../i.txt,'w').write(text)   # 다수 소파일 write
    for i in range(n): open(.../i.txt,'r').read()         # read(page-cache 히트면 block≈0)
다수 소파일 write = block_rq_insert가 많이 생겨, queue_depth=2 + filled HDD에서 insert→issue
큐로 직렬화 → 합성 fio block stressor와 경합. (compression-store의 다수-소파일 패턴과 동형;
단 원본은 fsync가 없어 writeback에 의존 — buffered writeback은 blkcg로 victim에 귀속됨.)
WORK_DIR을 실블록디바이스(/mnt/hdd 바인드마운트)로 둬야 block 이벤트가 난다(tmpfs면 0).
인자: n(파일 수) size(바이트). 출처: FaaSDom (Maissen et al., ICPE'20)."""
import sys
import os
import time
import json
import shutil
import random


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 10240
    work = os.environ.get('WORK_DIR', '/tmp/test')
    rnd = random.randint(100000, 999999)
    d = os.path.join(work, str(rnd))
    os.makedirs(d, exist_ok=True)
    text = "A" * (size - 1)

    start = time.perf_counter()
    for i in range(n):
        with open(os.path.join(d, f'{i}.txt'), 'w') as f:
            f.write(text)
    os.sync()   # 끝에 전체 page cache flush로 writeback 강제(page cache 우회). per-file fsync는
                # filled HDD에서 비현실적으로 느려(>2분) 1회 sync로 대체 — 워크로드(다수 소파일 write)는 동일
    for i in range(n):
        with open(os.path.join(d, f'{i}.txt'), 'r') as f:
            f.read()
    elapsed_ms = (time.perf_counter() - start) * 1000

    shutil.rmtree(d, ignore_errors=True)
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "n": n, "size": size}))


if __name__ == "__main__":
    main()
