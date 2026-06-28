#!/usr/bin/env python3
"""Network Uploader - Network-bound benchmark for TX traffic measurement"""

import time
import json
import os
import boto3
from botocore.client import Config


def upload_to_minio(s3, local_path: str, bucket: str, key: str) -> dict:
    """Upload file to MinIO and return timing info. s3 client는 재사용(연결 floor 분산):
    매 호출 새 client를 만들면 iteration마다 TCP connect/handshake floor가 반복돼 짧은 net
    victim에서 그 비율이 커진다(removal↓). client 1회 생성 + N 전송이면 floor가 분산된다."""
    file_size = os.path.getsize(local_path)

    start = time.perf_counter()
    s3.upload_file(local_path, bucket, key)
    upload_time = time.perf_counter() - start

    return {
        'upload_time_ms': round(upload_time * 1000, 2),
        'file_size_bytes': file_size,
        'bucket': bucket,
        'key': key
    }


def main():
    # Configuration from environment
    input_file = os.environ.get('INPUT_FILE', '/data/tmp.bin')
    minio_endpoint = os.environ.get('MINIO_ENDPOINT', 'http://165.194.27.225:9000')
    minio_access_key = os.environ.get('MINIO_ACCESS_KEY', 'minioadmincslab')
    minio_secret_key = os.environ.get('MINIO_SECRET_KEY', 'minioadmincslab')
    bucket_name = os.environ.get('MINIO_BUCKET', 'uploads')
    iterations = int(os.environ.get('ITERATIONS', '5'))

    # Check input file exists
    if not os.path.exists(input_file):
        print(json.dumps({
            'error': f'Input file not found: {input_file}',
            'hint': 'Mount a file to /data/tmp.bin or set INPUT_FILE env'
        }))
        return

    # client 1회 생성 (연결 floor 분산: iteration마다 재연결하지 않음)
    s3 = boto3.client(
        's3', endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key, aws_secret_access_key=minio_secret_key,
        config=Config(signature_version='s3v4'), region_name='us-east-1',
    )

    # SeBS uploader 원본의 download 단계 복원 (원본=URL download→MinIO upload; 외부 URL을 MinIO 인프라로
    # 대체). download(RX)는 PureTime 범위 밖이지만 connection을 활성화 → 이어지는 upload-TX 추적이 정확해짐
    # (s3_download_upload가 같은 이유로 upload-only 88%→92%). dl_input.bin이 없으면 첫 호출이 seed.
    try:
        try:
            s3.head_object(Bucket=bucket_name, Key='dl_input.bin')
        except Exception:
            s3.upload_file(input_file, bucket_name, 'dl_input.bin')
        s3.download_file(bucket_name, 'dl_input.bin', '/tmp/dl_input.bin')
    except Exception:
        pass

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        key = f"upload_{time.time_ns()}_{i}.bin"
        upload_result = upload_to_minio(s3, input_file, bucket_name, key)

        results.append({
            'iteration': i + 1,
            **upload_result
        })

    total_time = time.perf_counter() - total_start
    total_upload = sum(r['upload_time_ms'] for r in results)

    print(json.dumps({
        'iterations': iterations,
        'input_file': input_file,
        'total_upload_time_ms': round(total_upload, 2),
        'elapsed_ms': round(total_time * 1000, 2),
        'results': results
    }))


if __name__ == "__main__":
    main()
