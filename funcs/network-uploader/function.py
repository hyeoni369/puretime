#!/usr/bin/env python3
"""Network Uploader - Network-bound benchmark for TX traffic measurement"""

import time
import json
import os
import boto3
from botocore.client import Config


def upload_to_minio(local_path: str, bucket: str, key: str,
                    endpoint_url: str, access_key: str, secret_key: str) -> dict:
    """Upload file to MinIO and return timing info"""
    s3 = boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'
    )

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

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        key = f"upload_{time.time_ns()}_{i}.bin"
        upload_result = upload_to_minio(
            input_file, bucket_name, key,
            minio_endpoint, minio_access_key, minio_secret_key
        )

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
