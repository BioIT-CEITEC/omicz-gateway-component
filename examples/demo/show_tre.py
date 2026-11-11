"""Show what the demo "TRE" received: per run, the uploaded files, the manifest and the receipt.

    docker exec fastapi_gateway_tre_standin-demo python /demo/show_tre.py
"""

import os
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"],
                  aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                  aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                  region_name=os.environ.get("S3_REGION", "us-east-1"))
INGRESS, PREFIX = os.environ["S3_BUCKET"], os.environ.get("S3_PREFIX", "")
RECEIPTS, RPREFIX = os.environ["S3_CHECKSUM_BUCKET"], os.environ.get("S3_CHECKSUM_PREFIX", "")


def objects(bucket, prefix):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


runs = defaultdict(list)
for o in objects(INGRESS, PREFIX):
    rel = o["Key"][len(PREFIX):]
    parts = rel.split("/", 2)              # <instrument>/<run>/<path in run>
    if len(parts) == 3:
        runs[f"{parts[0]}/{parts[1]}"].append((parts[2], o["Size"], o["Key"]))

if not runs:
    print(f"Nothing uploaded yet to s3://{INGRESS}/{PREFIX}")

for run, files in sorted(runs.items()):
    data = [f for f in files if not f[0].endswith(".CHECKSUM")]
    manifests = [f for f in files if f[0].endswith(".CHECKSUM")]
    print(f"\n=== {run}")
    print(f"  {len(data)} files, {sum(f[1] for f in data) / 2**20:.2f} MiB")
    for path, size, _ in sorted(data):
        print(f"    {size:>10,}  {path}")
    for path, _, key in manifests:
        digests = s3.get_object(Bucket=INGRESS, Key=key)["Body"].read().decode().split()
        print(f"  manifest  {path}  ({len(digests)} digests)")
        try:
            receipt = s3.get_object(Bucket=RECEIPTS, Key=RPREFIX + path)["Body"].read().decode()
            status = "CONFIRMED (empty receipt)" if receipt == "" else "FAILED:\n      " + receipt.replace("\n", "\n      ")
        except ClientError:
            status = "no receipt yet"
        print(f"  receipt   {status}")
    if not manifests:
        print("  manifest  not uploaded yet")
