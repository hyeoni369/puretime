#!/usr/bin/env python3
"""Network Uploader - Network-bound benchmark inspired by SeBS Uploader"""

import time
import json
import os
import tempfile
import urllib.request
import boto3
from botocore.client import Config


def download_file(url: str, local_path: str) -> dict:
    """Download file from URL and return timing info"""
    start = time.perf_counter()
    req = urllib.request.Request(url, headers={'User-Agent': 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2'})
    with urllib.request.urlopen(req) as response:
        with open(local_path, 'wb') as f:
            f.write(response.read())
    download_time = time.perf_counter() - start

    file_size = os.path.getsize(local_path)
    return {
        'download_time_ms': round(download_time * 1000, 2),
        'file_size_bytes': file_size
    }


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

    start = time.perf_counter()
    s3.upload_file(local_path, bucket, key)
    upload_time = time.perf_counter() - start

    return {
        'upload_time_ms': round(upload_time * 1000, 2),
        'bucket': bucket,
        'key': key
    }


def main():
    # Configuration from environment
    download_url = os.environ.get('DOWNLOAD_URL','https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Jammlich_crop.jpg/800px-Jammlich_crop.jpg')
    minio_endpoint = os.environ.get('MINIO_ENDPOINT', 'http://165.194.27.225:9000')
    minio_access_key = os.environ.get('MINIO_ACCESS_KEY', 'minioadmin')
    minio_secret_key = os.environ.get('MINIO_SECRET_KEY', 'minioadmin')
    bucket_name = os.environ.get('MINIO_BUCKET', 'uploads')
    iterations = int(os.environ.get('ITERATIONS', '5'))

    results = []
    total_start = time.perf_counter()

    for i in range(iterations):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            download_result = download_file(download_url, tmp_path)

            key = f"upload_{int(time.time_ns())}_{i}.bin"
            upload_result = upload_to_minio(
                tmp_path, bucket_name, key,
                minio_endpoint, minio_access_key, minio_secret_key
            )

            results.append({
                'iteration': i + 1,
                **download_result,
                **upload_result
            })
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    total_time = time.perf_counter() - total_start
    total_download = sum(r['download_time_ms'] for r in results)
    total_upload = sum(r['upload_time_ms'] for r in results)

    print(json.dumps({
        'iterations': iterations,
        'total_download_time_ms': round(total_download, 2),
        'total_upload_time_ms': round(total_upload, 2),
        'elapsed_ms': round(total_time * 1000, 2),
        'results': results
    }))


if __name__ == "__main__":
    main()
