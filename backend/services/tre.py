"""
TRE (Trusted Research Environment)
"""
import fnmatch
import os
import threading
import time

import boto3
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

# Always skip hidden files/folders (same rule as checksumming)
_BUILTIN_EXCLUSIONS = [".*"]

from core.logger import get_logger

logger = get_logger("tre")

S3_ENDPOINT    = os.getenv("S3_ENDPOINT",    "https://omicz-s3proxy.dyn.cloud.e-infra.cz")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY")
S3_REGION      = os.getenv("S3_REGION",      "us-east-1")
S3_BUCKET      = os.getenv("S3_BUCKET",      "omicz-dev")
S3_PREFIX      = os.getenv("S3_PREFIX",      "raw_run_data/")


from db.repositories.settings import get_setting_int


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


_MULTIPART_THRESHOLD   = 16 * 1024 * 1024   # files >= 16 MB use multipart
_MULTIPART_CHUNKSIZE   = 16 * 1024 * 1024   # 16 MB per part
_MULTIPART_CONCURRENCY = 4                   # 4 parallel streams — kubectl port-forward safe limit


def _upload_file(s3, local_path: str, bucket: str, s3_key: str,
                 on_bytes=None, on_retry=None, max_attempts: int = 5, backoff_max: int = 30) -> None:
    """
    Upload a single file using the S3 Transfer Manager.
    Files >= _MULTIPART_THRESHOLD are split into _MULTIPART_CHUNKSIZE parts and
    uploaded with _MULTIPART_CONCURRENCY parallel threads. Smaller files use a
    single PUT. on_bytes(n) is called as bytes are transferred (thread-safe —
    the Transfer Manager may call it from multiple threads for large files).
    """
    config = TransferConfig(
        multipart_threshold=_MULTIPART_THRESHOLD,
        multipart_chunksize=_MULTIPART_CHUNKSIZE,
        max_concurrency=_MULTIPART_CONCURRENCY,
    )
    for attempt in range(1, max_attempts + 1):
        if attempt > 1 and on_retry:
            on_retry()   # reset per-file byte counter so progress doesn't exceed total
        try:
            s3.upload_file(local_path, bucket, s3_key, Config=config,
                           Callback=on_bytes if on_bytes else None)
            logger.info(f"[TRE upload] complete: s3://{bucket}/{s3_key} size={os.path.getsize(local_path)}")
            return
        except (S3UploadFailedError, ClientError) as exc:
            # S3UploadFailedError wraps ClientError when using upload_file(); check both forms
            is_precondition = (
                isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code", "") == "PreconditionFailed"
            ) or "PreconditionFailed" in str(exc)
            if is_precondition:
                logger.warning(f"[TRE upload] PreconditionFailed for {s3_key} — file already on S3, skipping")
                return
            if attempt < max_attempts:
                wait = min(5 * attempt, backoff_max)
                logger.warning(f"[TRE upload] attempt {attempt} failed — retry in {wait}s: {exc}")
                time.sleep(wait)
            else:
                logger.error(f"[TRE upload] all {max_attempts} attempts failed for {local_path}: {exc}")
                raise
        except Exception as exc:
            if attempt < max_attempts:
                wait = min(5 * attempt, backoff_max)
                logger.warning(f"[TRE upload] attempt {attempt} failed — retry in {wait}s: {exc}")
                time.sleep(wait)
            else:
                logger.error(f"[TRE upload] all {max_attempts} attempts failed for {local_path}: {exc}")
                raise


def send_to_tre(run_name: str, sequencer_location: str, sequencer_slug: str, exclusions: list[str] | None = None, on_progress=None) -> bool:
    """
    Upload the run folder to S3.
    Raises on failure so the caller can store the real error detail.
    on_progress(files_done, total_files, bytes_done, total_bytes) called after each file.
    """
    max_attempts = get_setting_int("upload_max_attempts", 5)
    backoff_max  = get_setting_int("upload_retry_backoff_max", 30)
    local_folder = os.path.join(sequencer_location, run_name)
    all_exclusions = _BUILTIN_EXCLUSIONS + (exclusions or [])

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=boto3.session.Config(
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=600,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )

    # test TCP connectivity before walking potentially thousands of files
    import socket
    from urllib.parse import urlparse
    _parsed = urlparse(S3_ENDPOINT)
    _host   = _parsed.hostname
    _port   = _parsed.port or (443 if _parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((_host, _port), timeout=10):
            pass
    except Exception as e:
        raise RuntimeError(f"Cannot reach S3 endpoint ({S3_ENDPOINT}): {e}") from e

    # pre-scan: collect files to upload and total byte count
    upload_files = []  # list of (local_path, relative_path, rel_to_run)
    total_bytes  = 0
    for root, dirs, files in os.walk(local_folder):
        for file in files:
            local_path    = os.path.join(root, file)
            rel_to_run    = os.path.relpath(local_path, local_folder)
            if _is_excluded(rel_to_run, all_exclusions):
                continue
            relative_path = os.path.relpath(local_path, sequencer_location)
            try:
                total_bytes += os.path.getsize(local_path)
            except OSError:
                pass
            upload_files.append((local_path, relative_path, rel_to_run))

    # Sort so that the .CHECKSUM file is uploaded last — it is the S3 trigger
    upload_files.sort(key=lambda t: t[2].endswith(".CHECKSUM"))

    total_files  = len(upload_files)
    files_done   = 0
    bytes_done   = 0
    _lock        = threading.Lock()

    logger.info(f"[TRE upload] starting — endpoint={S3_ENDPOINT} bucket={S3_BUCKET} prefix={S3_PREFIX} folder={local_folder} files={total_files}")

    # emit initial progress so UI shows "0 / N files · 0 B / X B" immediately
    if on_progress:
        try:
            on_progress(0, total_files, 0, total_bytes)
        except Exception:
            pass

    for local_path, relative_path, rel_to_run in upload_files:
        s3_key = f"{S3_PREFIX}{sequencer_slug}/{relative_path}"

        _file_bytes = [0]

        def _chunk_done(n, _fd=files_done, _bd=bytes_done):
            with _lock:
                _file_bytes[0] += n
                if on_progress:
                    try:
                        on_progress(_fd, total_files, _bd + _file_bytes[0], total_bytes)
                    except Exception:
                        pass

        def _reset_file_bytes():
            with _lock:
                _file_bytes[0] = 0

        try:
            _upload_file(s3, local_path, S3_BUCKET, s3_key, on_bytes=_chunk_done, on_retry=_reset_file_bytes,
                         max_attempts=max_attempts, backoff_max=backoff_max)
        except (BotoCoreError, ClientError, S3UploadFailedError, OSError) as e:
            logger.error(f"Failed to upload {local_path} to {S3_BUCKET}/{s3_key}: {e}")
            raise
        files_done += 1
        bytes_done += _file_bytes[0]
        if on_progress:
            try:
                on_progress(files_done, total_files, bytes_done, total_bytes)
            except Exception:
                pass

    logger.info(f"[TRE upload] SUCCESS — all files uploaded for run '{run_name}'")
    return True


def find_checksum_filename_in_s3(run_name: str, sequencer_slug: str) -> str | None:
    """
    When the local .CHECKSUM file is missing (e.g. SMB mount dropped), look it up
    in the S3 upload bucket by listing the run's prefix.
    Returns just the filename (e.g. "abc123.CHECKSUM") or None if not found.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=boto3.session.Config(s3={"addressing_style": "path"}),
    )
    prefix = f"{S3_PREFIX}{sequencer_slug}/{run_name}/"
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".CHECKSUM"):
                filename = os.path.basename(key)
                logger.info(f"[verify] found checksum filename in S3: {filename}")
                return filename
        logger.warning(f"[verify] no .CHECKSUM object found in S3 at {S3_BUCKET}/{prefix}")
        return None
    except Exception as e:
        logger.warning(f"[verify] failed to list S3 for checksum filename: {e}")
        return None


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
    VERIFY_RETRIES  = get_setting_int("verify_retries",  10)
    VERIFY_INTERVAL = get_setting_int("verify_interval", 60)

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


def check_verify_status(checksum_filename: str) -> dict:
    """
    Single-shot check of the TRE checksums bucket — no retries, no sleeping.
    Returns a dict:
      {"status": "pending"}              — file not in bucket yet (TRE still processing)
      {"status": "success"}              — empty file = TRE confirmed OK
      {"status": "failed", "detail": x}  — file has content = TRE reported an error
      {"status": "error",  "detail": x}  — unexpected S3/network error
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=boto3.session.Config(s3={"addressing_style": "path"}),
    )
    try:
        obj = s3.get_object(Bucket="checksums", Key=checksum_filename)
        content = obj["Body"].read().decode("utf-8")
        if len(content) == 0:
            return {"status": "success"}
        return {"status": "failed", "detail": content.strip()}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return {"status": "pending"}
        return {"status": "error", "detail": str(e)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def delete_zip(zip_path: str) -> bool:
    """
    TODO: implement when deletion is needed.
    """
    return True
