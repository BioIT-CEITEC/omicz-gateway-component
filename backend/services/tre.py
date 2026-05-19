"""
TRE (Trusted Research Environment)
"""
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from core.logger import get_logger

logger = get_logger("worker")

S3_ENDPOINT    = os.getenv("S3_ENDPOINT",    "http://host.docker.internal:8080")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY",  "EiqbDIIzDfz5Bda2Vc2GF57x")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY",  "SIP4zaJnw8Bhi37POMVDQoPb")
S3_REGION      = os.getenv("S3_REGION",      "us-east-1")
S3_BUCKET      = os.getenv("S3_BUCKET",      "omicz-dev")
S3_PREFIX      = os.getenv("S3_PREFIX",      "raw_run_data/")


def send_to_tre(run_name: str, sequencer_location: str, sequencer_slug: str) -> bool:
    """
    Upload the run folder to S3.

    Files are uploaded as:
        s3://<bucket>/<prefix><sequencer_slug>/<run_name>/<relative_file_path>

    Example:
        local:  /data/seq1/run_2026_04_13_B/sample.bam
        s3 key: raw_run_data/seq1/run_2026_04_13_B/sample.bam
    """
    local_folder = os.path.join(sequencer_location, run_name)

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=boto3.session.Config(s3={"addressing_style": "path"}),
    )

    try:
        for root, dirs, files in os.walk(local_folder):
            for file in files:
                local_path    = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, sequencer_location)
                # e.g. raw_run_data/seq1/run_2026_04_13_B/subdir/file.bam
                s3_key = f"{S3_PREFIX}{sequencer_slug}/{relative_path}"
                s3.upload_file(local_path, S3_BUCKET, s3_key)
                logger.info(f"Uploaded: {s3_key}")
        return True
    except (BotoCoreError, ClientError) as e:
        logger.error(f"S3 upload failed for run '{run_name}': {e}")
        return False


def delete_zip(zip_path: str) -> bool:
    """
    TODO: implement when deletion is needed.
    """
    return True
