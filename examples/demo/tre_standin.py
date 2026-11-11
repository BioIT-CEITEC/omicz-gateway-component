"""Stand-in for the TRE side of OmiCZ Gateway, for the local demo only.

Plays the role of the inbox bucket watcher inside a TRE: it finds each run's
<digest>.CHECKSUM manifest in the ingress bucket, re-reads every object of the run,
compares the digests, and writes the receipt in the same format as the real watcher:

  empty object               every digest in the manifest was found
  one digest per line        these manifest digests were not found (missing or altered)
  VALIDATION_FAILED          the manifest is unreadable, does not match its name,
                             or the run holds files that are not in the manifest

Unlike the real watcher it leaves the run in the ingress bucket (there is no storage
bucket in the demo). Uses only boto3, which is part of the backend image.
"""

import hashlib
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

ENDPOINT        = os.environ["S3_ENDPOINT"]
INGRESS_BUCKET  = os.environ["S3_BUCKET"]
INGRESS_PREFIX  = os.environ.get("S3_PREFIX", "")
RECEIPT_BUCKET  = os.environ["S3_CHECKSUM_BUCKET"]
RECEIPT_PREFIX  = os.environ.get("S3_CHECKSUM_PREFIX", "")
INTERVAL        = int(os.environ.get("STANDIN_INTERVAL", "10"))
SETTLE_SECONDS  = 5

s3 = boto3.client("s3", endpoint_url=ENDPOINT,
                  aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                  aws_secret_access_key=os.environ["S3_SECRET_KEY"],
                  region_name=os.environ.get("S3_REGION", "us-east-1"))


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} tre-standin: {msg}", flush=True)


def ensure_buckets() -> None:
    for bucket in {INGRESS_BUCKET, RECEIPT_BUCKET}:
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError:
            s3.create_bucket(Bucket=bucket)
            log(f"created bucket {bucket}")


def list_keys(bucket: str, prefix: str):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


def sha256_of(bucket: str, key: str) -> str:
    h = hashlib.sha256()
    for chunk in s3.get_object(Bucket=bucket, Key=key)["Body"].iter_chunks(1024 * 1024):
        h.update(chunk)
    return h.hexdigest()


def existing_receipt(name: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=RECEIPT_BUCKET, Key=RECEIPT_PREFIX + name)["Body"].read()
    except ClientError:
        return None


def check_run(manifest_key: str) -> bytes:
    """Return the receipt for one run."""
    name = manifest_key.rsplit("/", 1)[-1]
    run_prefix = manifest_key[: -len(name)]
    manifest = s3.get_object(Bucket=INGRESS_BUCKET, Key=manifest_key)["Body"].read()
    if hashlib.sha256(manifest).hexdigest() != name[: -len(".CHECKSUM")]:
        return b"VALIDATION_FAILED"
    listed = {line.strip() for line in manifest.decode().splitlines() if line.strip()}
    if not listed:
        return b"VALIDATION_FAILED"
    received = {sha256_of(INGRESS_BUCKET, o["Key"])
                for o in list_keys(INGRESS_BUCKET, run_prefix)
                if not o["Key"].endswith(".CHECKSUM")}
    missing = sorted(listed - received)
    if missing:
        return "\n".join(missing).encode()
    if received - listed:
        return b"VALIDATION_FAILED"
    return b""


def cycle() -> None:
    now = datetime.now(timezone.utc)
    for obj in list_keys(INGRESS_BUCKET, INGRESS_PREFIX):
        key = obj["Key"]
        if not key.endswith(".CHECKSUM"):
            continue
        if (now - obj["LastModified"]).total_seconds() < SETTLE_SECONDS:
            continue
        name = key.rsplit("/", 1)[-1]
        if existing_receipt(name) == b"":
            continue  # already confirmed
        receipt = check_run(key)
        s3.put_object(Bucket=RECEIPT_BUCKET, Key=RECEIPT_PREFIX + name, Body=receipt)
        result = "confirmed" if receipt == b"" else f"FAILED ({receipt[:80].decode()})"
        log(f"{key}: {result}")


def main() -> None:
    while True:
        try:
            ensure_buckets()
            break
        except EndpointConnectionError:
            log(f"waiting for S3 at {ENDPOINT}")
            time.sleep(2)
    log(f"watching s3://{INGRESS_BUCKET}/{INGRESS_PREFIX} every {INTERVAL} s")
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
