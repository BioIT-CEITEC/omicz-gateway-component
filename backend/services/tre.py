"""
TRE (Trusted Research Environment)
"""
import fnmatch
import os
import threading
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

# Always skip hidden files/folders (same rule as checksumming)
_BUILTIN_EXCLUSIONS = [".*"]

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


class _ProgressReader:
    """Wraps a file and calls on_chunk(n) for every chunk read, enabling live progress."""
    def __init__(self, fh, on_chunk):
        self._fh = fh
        self._on_chunk = on_chunk

    def read(self, n=-1):
        data = self._fh.read(n)
        if data and self._on_chunk:
            self._on_chunk(len(data))
        return data

    def __getattr__(self, name):
        return getattr(self._fh, name)


def _upload_file_put(s3, local_path: str, bucket: str, s3_key: str,
                     on_bytes=None, max_attempts: int = 5) -> None:
    """
    Upload a single file using a plain PUT (put_object).

    Avoids multipart upload entirely — some S3 proxies forbid CompleteMultipartUpload
    even when they allow individual UploadPart calls.
    on_bytes(n) is called progressively as bytes are streamed.
    """
    file_size = os.path.getsize(local_path)
    for attempt in range(1, max_attempts + 1):
        try:
            with open(local_path, "rb") as fh:
                reader = _ProgressReader(fh, on_bytes)
                s3.put_object(Bucket=bucket, Key=s3_key, Body=reader, ContentLength=file_size)
            logger.info(f"[TRE upload] put_object complete: s3://{bucket}/{s3_key} size={file_size}")
            return
        except (BotoCoreError, ClientError, OSError) as exc:
            if attempt < max_attempts:
                wait = min(5 * attempt, 30)
                logger.warning(f"[TRE upload] put_object attempt {attempt} failed — retry in {wait}s: {exc}")
                time.sleep(wait)
            else:
                logger.error(f"[TRE upload] all {max_attempts} put_object attempts failed for {local_path}: {exc}")
                raise


def send_to_tre(run_name: str, sequencer_location: str, sequencer_slug: str, exclusions: list[str] | None = None, on_progress=None) -> bool:
    """
    Upload the run folder to S3.
    Raises on failure so the caller can store the real error detail.
    on_progress(files_done, total_files, bytes_done, total_bytes) called after each file.
    """
    local_folder   = os.path.join(sequencer_location, run_name)
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

        try:
            _upload_file_put(s3, local_path, S3_BUCKET, s3_key, on_bytes=_chunk_done)
        except (BotoCoreError, ClientError, OSError) as e:
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
