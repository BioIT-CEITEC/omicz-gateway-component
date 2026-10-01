"""
TRE (Trusted Research Environment)
"""
import fnmatch
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

# Always skip hidden files/folders (same rule as checksumming)
_BUILTIN_EXCLUSIONS = [".*"]

from core.logger import get_logger

logger = get_logger("tre")

S3_ENDPOINT    = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY  = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY  = os.getenv("S3_SECRET_KEY")
S3_REGION      = os.getenv("S3_REGION")
S3_BUCKET      = os.getenv("S3_BUCKET")
S3_PREFIX      = os.getenv("S3_PREFIX")

_REQUIRED_S3_VARS = {
    "S3_ENDPOINT": S3_ENDPOINT,
    "S3_ACCESS_KEY": S3_ACCESS_KEY,
    "S3_SECRET_KEY": S3_SECRET_KEY,
    "S3_REGION": S3_REGION,
    "S3_BUCKET": S3_BUCKET,
    "S3_PREFIX": S3_PREFIX,
}
_missing = [k for k, v in _REQUIRED_S3_VARS.items() if not v]
if _missing:
    import warnings
    warnings.warn(
        f"[TRE] Missing required environment variables: {', '.join(_missing)}. "
        "S3 upload/verify operations will fail. Set these in backend/.env.",
        RuntimeWarning,
        stacklevel=1,
    )


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
_MAX_PARTS             = 10_000              # S3 limit per multipart upload


def _is_precondition(exc: Exception) -> bool:
    # the proxy refuses overwrites with PreconditionFailed; S3UploadFailedError only carries it in the text
    return (
        isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code", "") == "PreconditionFailed"
    ) or "PreconditionFailed" in str(exc)


def _error_details(exc: Exception) -> str:
    """Code, message and response headers of an S3 error — the proxy's 400s come without a code."""
    if not isinstance(exc, ClientError):
        return str(exc)
    meta = exc.response.get("ResponseMetadata", {})
    err  = exc.response.get("Error", {})
    return (f"HTTP {meta.get('HTTPStatusCode')} code={err.get('Code')!r} message={err.get('Message')!r} "
            f"request_id={meta.get('RequestId')!r} headers={meta.get('HTTPHeaders')}")


def _part_size(size: int) -> int:
    """_MULTIPART_CHUNKSIZE, or bigger (whole MiB) when the file would need more than _MAX_PARTS parts."""
    mib = 1024 * 1024
    needed = -(-size // _MAX_PARTS)
    return max(_MULTIPART_CHUNKSIZE, -(-needed // mib) * mib)


def _multipart_upload(s3, local_path: str, bucket: str, s3_key: str,
                      on_bytes=None, max_attempts: int = 5, backoff_max: int = 30) -> None:
    """
    Multipart upload where every part is retried on its own. With upload_file() one
    rejected part (the proxy answers an occasional UploadPart with a bare 400) threw away
    the whole file — for a 100 GB file that meant starting again from byte 0.
    Parts are read from disk per attempt, _MULTIPART_CONCURRENCY at a time.
    """
    size       = os.path.getsize(local_path)
    part_size  = _part_size(size)
    n_parts    = -(-size // part_size)
    upload_id  = s3.create_multipart_upload(Bucket=bucket, Key=s3_key)["UploadId"]

    def _send(part_number: int) -> dict:
        offset = (part_number - 1) * part_size
        length = min(part_size, size - offset)
        for attempt in range(1, max_attempts + 1):
            try:
                with open(local_path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                resp = s3.upload_part(Bucket=bucket, Key=s3_key, UploadId=upload_id,
                                      PartNumber=part_number, Body=data)
                if on_bytes:
                    on_bytes(length)
                return {"PartNumber": part_number, "ETag": resp["ETag"]}
            except Exception as exc:
                if _is_precondition(exc) or attempt == max_attempts:
                    raise
                wait = min(5 * attempt, backoff_max)
                logger.warning(f"[TRE upload] part {part_number}/{n_parts} of {s3_key} attempt {attempt} failed "
                               f"— retry in {wait}s: {_error_details(exc)}")
                time.sleep(wait)

    try:
        parts = []
        with ThreadPoolExecutor(max_workers=_MULTIPART_CONCURRENCY) as pool:
            futures = [pool.submit(_send, n) for n in range(1, n_parts + 1)]
            try:
                for future in as_completed(futures):
                    parts.append(future.result())
            except BaseException:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
        parts.sort(key=lambda p: p["PartNumber"])
        s3.complete_multipart_upload(Bucket=bucket, Key=s3_key, UploadId=upload_id,
                                     MultipartUpload={"Parts": parts})
    except BaseException:
        try:
            s3.abort_multipart_upload(Bucket=bucket, Key=s3_key, UploadId=upload_id)
        except Exception as exc:
            logger.warning(f"[TRE upload] could not abort multipart upload of {s3_key}: {exc}")
        raise


def _upload_file(s3, local_path: str, bucket: str, s3_key: str,
                 on_bytes=None, on_retry=None, max_attempts: int = 5, backoff_max: int = 30) -> None:
    """
    Upload a single file. Files >= _MULTIPART_THRESHOLD go through _multipart_upload
    (parts retried one by one); smaller files are a single PUT via the S3 Transfer
    Manager, retried as a whole. on_bytes(n) is called as bytes are transferred
    (thread-safe — it is called from several threads for large files).
    """
    try:
        if os.path.getsize(local_path) >= _MULTIPART_THRESHOLD:
            _multipart_upload(s3, local_path, bucket, s3_key, on_bytes=on_bytes,
                              max_attempts=max_attempts, backoff_max=backoff_max)
            logger.info(f"[TRE upload] complete: s3://{bucket}/{s3_key} size={os.path.getsize(local_path)}")
            return
    except Exception as exc:
        if _is_precondition(exc):
            logger.warning(f"[TRE upload] PreconditionFailed for {s3_key} — file already on S3, skipping")
            return
        logger.error(f"[TRE upload] failed for {local_path}: {_error_details(exc)}")
        raise

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
            if _is_precondition(exc):
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


def _upload_client():
    return boto3.client(
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


def _check_endpoint():
    """Test TCP connectivity before walking potentially thousands of files."""
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


def upload_file_list(upload_files: list[tuple[str, str]], sequencer_slug: str, on_progress=None, on_file_done=None) -> None:
    """
    Upload the given files in order.
    upload_files: list of (local_path, path relative to the sequencer location) — the S3 key is
    S3_PREFIX/<slug>/<relative path>, so a directory sent early lands where a full-run upload would put it.
    on_progress(files_done, total_files, bytes_done, total_bytes) during the upload.
    on_file_done(local_path, relative_path) after each file is uploaded.
    Raises on failure.
    """
    max_attempts = get_setting_int("upload_max_attempts", 5)
    backoff_max  = get_setting_int("upload_retry_backoff_max", 30)

    s3 = _upload_client()
    _check_endpoint()

    total_bytes = 0
    for local_path, _ in upload_files:
        try:
            total_bytes += os.path.getsize(local_path)
        except OSError:
            pass

    total_files  = len(upload_files)
    files_done   = 0
    bytes_done   = 0
    _lock        = threading.Lock()

    # emit initial progress so UI shows "0 / N files · 0 B / X B" immediately
    if on_progress:
        try:
            on_progress(0, total_files, 0, total_bytes)
        except Exception:
            pass

    for local_path, relative_path in upload_files:
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
        if on_file_done:
            on_file_done(local_path, relative_path)
        if on_progress:
            try:
                on_progress(files_done, total_files, bytes_done, total_bytes)
            except Exception:
                pass


def send_to_tre(run_name: str, sequencer_location: str, sequencer_slug: str, exclusions: list[str] | None = None, on_progress=None,
                already_uploaded: dict[str, tuple[int, int]] | None = None, on_file_done=None) -> bool:
    """
    Upload the run folder to S3.
    Raises on failure so the caller can store the real error detail.
    on_progress(files_done, total_files, bytes_done, total_bytes) called after each file.
    already_uploaded {rel_to_run: (size, mtime_ns)}: files sent earlier (directory stability, or an
    upload that was interrupted) — skipped when their size and mtime are unchanged.
    on_file_done(local_path, relative_path) after each file is uploaded, so the caller can record it.
    """
    local_folder = os.path.join(sequencer_location, run_name)
    all_exclusions = _BUILTIN_EXCLUSIONS + (exclusions or [])
    already_uploaded = already_uploaded or {}

    _check_endpoint()

    # pre-scan: collect files to upload
    upload_files = []  # list of (local_path, relative_path, rel_to_run)
    skipped      = 0
    for root, dirs, files in os.walk(local_folder):
        for file in files:
            local_path    = os.path.join(root, file)
            rel_to_run    = os.path.relpath(local_path, local_folder)
            if _is_excluded(rel_to_run, all_exclusions):
                continue
            sent = already_uploaded.get(rel_to_run.replace(os.sep, "/"))
            if sent:
                try:
                    st = os.stat(local_path)
                    if (st.st_size, st.st_mtime_ns) == tuple(sent):
                        skipped += 1
                        continue
                except OSError:
                    pass
            relative_path = os.path.relpath(local_path, sequencer_location)
            upload_files.append((local_path, relative_path, rel_to_run))

    # Sort so that the .CHECKSUM file is uploaded last — it is the S3 trigger
    upload_files.sort(key=lambda t: t[2].endswith(".CHECKSUM"))

    logger.info(f"[TRE upload] starting — endpoint={S3_ENDPOINT} bucket={S3_BUCKET} prefix={S3_PREFIX} folder={local_folder} "
                f"files={len(upload_files)} already_sent={skipped}")

    upload_file_list([(lp, rp) for lp, rp, _ in upload_files], sequencer_slug, on_progress=on_progress, on_file_done=on_file_done)

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
