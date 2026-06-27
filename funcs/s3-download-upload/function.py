#!/usr/bin/env python3
"""FunctionBench s3_download_upload (network TCP-TX victim) — handler 제거.

원본: aws/network/s3_download_upload — boto3 download_file(RX) + upload_file(TX).
PureTime은 upload(TX, net_dev_queue→start_xmit)를 측정한다. download(RX)는 범위 밖이지만
원본 충실을 위해 포함 — qdisc throttle은 egress(TX)에만 걸리므로 RX는 빠르게 지나가고
makespan은 upload-TX가 지배한다. SeBS uploader(합성 blob, 작은 크기)와 *다른 벤치 + download
단계 + 다른 크기*로 구별. MinIO endpoint를 주입(원본은 boto3.client('s3') 기본).
출처: FunctionBench (Kim & Lee, SoCC'19; github.com/kmu-bigdata/serverless-faas-workbench)."""
import boto3
import os
import time
import json
from botocore.client import Config


def main():
    endpoint = os.environ.get('MINIO_ENDPOINT', 'http://165.194.27.225:9000')
    ak = os.environ.get('MINIO_ACCESS_KEY', 'minioadmincslab')
    sk = os.environ.get('MINIO_SECRET_KEY', 'minioadmincslab')
    in_bucket = os.environ.get('INPUT_BUCKET', 'uploads')
    out_bucket = os.environ.get('OUTPUT_BUCKET', 'uploads')
    object_key = os.environ.get('OBJECT_KEY', 's3dlul_input.bin')

    s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=ak,
                      aws_secret_access_key=sk, config=Config(signature_version='s3v4'),
                      region_name='us-east-1')
    path = '/tmp/' + os.path.basename(object_key)

    s = time.perf_counter()
    s3.download_file(in_bucket, object_key, path)   # RX (PureTime 범위 밖)
    dl = time.perf_counter() - s

    up_key = f"s3ul_{time.time_ns()}.bin"
    s = time.perf_counter()
    s3.upload_file(path, out_bucket, up_key)         # TX (측정 대상)
    ul = time.perf_counter() - s

    print(json.dumps({"elapsed_ms": round((dl + ul) * 1000, 2),
                      "download_ms": round(dl * 1000, 2),
                      "upload_ms": round(ul * 1000, 2)}))


if __name__ == "__main__":
    main()
