"""
TRE (Trusted Research Environment)
"""
import fnmatch
import os
import time

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError

from core.logger import get_logger

logger = get_logger("tre")

S3_ENDPOINT    = os.getenv("S3_ENDPOINT",    "http://host.docker.internal:8080")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY",  "EiqbDIIzDfz5Bda2Vc2GF57x")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY",  "SIP4zaJnw8Bhi37POMVDQoPb")
S3_REGION      = os.getenv("S3_REGION",      "us-east-1")
S3_BUCKET      = os.getenv("S3_BUCKET",      "omicz-dev")
S3_PREFIX      = os.getenv("S3_PREFIX",      "raw_run_data/")


VERIFY_RETRIES  = int(os.getenv("VERIFY_RETRIES",  "10"))   # how many times to check
VERIFY_INTERVAL = int(os.getenv("VERIFY_INTERVAL", "60"))   # seconds between each check


def _is_excluded(relative_path: str, exclusions: list[str]) -> bool:
    """
    Return True if relative_path matches any exclusion pattern.
    Supports exact filenames, subfolder names, and glob patterns (e.g. *.png).
    """
    if not exclusions:
        return False
    parts = relative_path.replace("\\", "/").split("/")
    for pattern in exclusions:
        if fnmatch.fnmatch(relative_path.replace("\\", "/"), pattern):
            return True
        if fnmatch.fnmatch(parts[-1], pattern):
            return True
        for part in parts[:-1]:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def send_to_tre(run_name: str, sequencer_location: str, sequencer_slug: str, exclusions: list[str] | None = None) -> bool:
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

    logger.info(f"[TRE upload] starting — endpoint={S3_ENDPOINT} bucket={S3_BUCKET} prefix={S3_PREFIX} folder={local_folder}")
    try:
        for root, dirs, files in os.walk(local_folder):
            for file in files:
                local_path    = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, sequencer_location)
                rel_to_run    = os.path.relpath(local_path, local_folder)
                if _is_excluded(rel_to_run, exclusions or []):
                    logger.info(f"[TRE upload] excluded (skipped): {rel_to_run}")
                    continue
                s3_key = f"{S3_PREFIX}{sequencer_slug}/{relative_path}"
                s3.upload_file(local_path, S3_BUCKET, s3_key,
                               Config=TransferConfig(multipart_threshold=5 * 1024 ** 4))  # 5 TB — effectively disables multipart
                logger.info(f"[TRE upload] uploaded: s3://{S3_BUCKET}/{s3_key}")
        logger.info(f"[TRE upload] SUCCESS — all files uploaded for run '{run_name}'")
        return True
    except (BotoCoreError, ClientError) as e:
        logger.error(f"[TRE upload] FAILED for run '{run_name}': {e}")
        return False


def verify_checksum_on_s3(checksum_filename: str) -> tuple[bool, str | None]:
    """
    Poll S3 until TRE places the checksum file in the checksums/ prefix.

    empty file (size 0) = success, TRE confirmed receipt
    file has content    = TRE wrote an error message → problem

    Returns: (success, error_content)
        (True,  None)        — file exists and is empty = OK
        (False, "<message>") — file exists and has content = TRE error
        (False, None)        — not found after all retries, or unexpected S3 error
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=boto3.session.Config(s3={"addressing_style": "path"}),
    )
    s3_key = checksum_filename

    logger.info(f"[TRE verify] starting — endpoint={S3_ENDPOINT} bucket=checksums key={s3_key} retries={VERIFY_RETRIES} interval={VERIFY_INTERVAL}s")

    for attempt in range(1, VERIFY_RETRIES + 1):
        try:
            logger.info(f"[TRE verify] attempt {attempt}/{VERIFY_RETRIES} — GET s3://checksums/{s3_key}")
            obj = s3.get_object(Bucket="checksums", Key=s3_key)
            content = obj["Body"].read().decode("utf-8")
            size = len(content)
            logger.info(f"[TRE verify] file found — size={size} bytes")

            if size == 0:
                logger.info(f"[TRE verify] SUCCESS — empty file = TRE confirmed receipt")
                return True, None

            # file has content — TRE reported a problem, no point retrying
            logger.warning(f"[TRE verify] FAILED — file has content (TRE error):\n{content}")
            return False, content

        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "unknown") if isinstance(e, ClientError) else type(e).__name__
            logger.warning(f"[TRE verify] attempt {attempt}/{VERIFY_RETRIES} failed — code={code} error={e}")
            if attempt < VERIFY_RETRIES:
                logger.info(f"[TRE verify] waiting {VERIFY_INTERVAL}s before next attempt")
                time.sleep(VERIFY_INTERVAL)

    logger.warning(f"[TRE verify] FAILED — not found after {VERIFY_RETRIES} attempts: s3://checksums/{s3_key}")
    return False, None


def delete_zip(zip_path: str) -> bool:
    """
    TODO: implement when deletion is needed.
    """
    return True
