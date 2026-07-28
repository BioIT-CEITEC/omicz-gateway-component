import fnmatch
import glob
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from core.logger import get_logger

logger = get_logger("checksum")

CHECKSUM_FILENAME = "checksum.CHECKSUM"
_DEFAULT_CHUNK_MB = 5


def _chunk_size() -> int:
    """Read checksum_chunk_size_mb from settings DB at runtime. Falls back to default."""
    from db.repositories.settings import get_setting_int
    return get_setting_int("checksum_chunk_size_mb", _DEFAULT_CHUNK_MB) * 1024 * 1024

# Always exclude hidden files/folders (names starting with ".") regardless of user exclusions.
# This covers macOS resource forks (._*), SMB temp files (.smbdelete*), .DS_Store, etc.
BUILTIN_EXCLUSIONS = [".*"]


def _is_excluded(relative_path: str, exclusions: list[str]) -> bool:
    """
    Return True if relative_path matches any exclusion pattern.
    Supports exact filenames, subfolder names, and glob patterns (e.g. *.png).
    Matching is done against:
      - the full relative path  (e.g. thumbnails/image.png)
      - the filename only       (e.g. image.png)
      - each parent directory   (e.g. thumbnails)
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


def _sha256(file_path: str, chunk_callback: Callable | None = None) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(_chunk_size()), b""):
            h.update(chunk)
            if chunk_callback:
                chunk_callback(len(chunk))
    return h.hexdigest()


def _checksum_one(file_path: str, run_folder: str, exclusions: list[str], chunk_callback: Callable | None = None):
    """Checksum a single file. Returns (relative_path, digest, file_size) or None if excluded."""
    relative = os.path.relpath(file_path, run_folder)
    if _is_excluded(relative, BUILTIN_EXCLUSIONS + exclusions):
        logger.info(f"excluded (skipped): {relative}")
        return None
    size   = os.path.getsize(file_path)
    digest = _sha256(file_path, chunk_callback=chunk_callback)
    logger.info(f"checksummed: {relative}")
    return (relative, digest, size)


def create_checksum_file(
    run_name: str,
    sequencer_location: str,
    exclusions: list[str] | None = None,
    on_progress: Callable | None = None,
) -> str:
    """
    Walk every file inside the run folder, compute SHA256 for each in parallel.
    Calls on_progress(done, total, bytes_done, total_bytes) after each file completes,
    and also every PROGRESS_CHUNK_BYTES read within a large file.
    """
    PROGRESS_CHUNK_BYTES = 500 * 1024 * 1024  # report every 500 MB within a file

    run_folder    = os.path.join(sequencer_location, run_name)
    checksum_path = os.path.join(run_folder, CHECKSUM_FILENAME)

    if not os.path.isdir(run_folder):
        raise RuntimeError(f"Run folder is not accessible (network share may be disconnected): {run_folder}")

    # if a *.CHECKSUM file already exists (e.g. retry after failed upload), reuse it
    existing = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
    if existing:
        logger.info(f"checksum file already exists — skipping creation: {os.path.basename(existing[0])}")
        return existing[0]

    # collect all file paths first (fast walk — no hashing yet)
    all_exclusions = BUILTIN_EXCLUSIONS + (exclusions or [])
    file_paths = []
    for root, dirs, files in os.walk(run_folder):
        for filename in files:
            if filename == CHECKSUM_FILENAME:
                continue
            fp = os.path.join(root, filename)
            relative = os.path.relpath(fp, run_folder)
            if _is_excluded(relative, all_exclusions):
                continue
            file_paths.append(fp)

    total_files = len(file_paths)
    total_bytes = sum(os.path.getsize(p) for p in file_paths if os.path.isfile(p))

    import threading
    _lock         = threading.Lock()
    _done_files   = [0]
    _done_bytes   = [0]
    _partial_bytes = [0]   # bytes read mid-file across all active threads

    entries = []

    logger.info(f"checksumming {total_files} files ({_fmt_bytes(total_bytes)}) using {min(4, os.cpu_count() or 1)} threads")

    max_workers = min(4, os.cpu_count() or 1)

    def _make_chunk_callback():
        """Returns a per-file chunk callback that accumulates bytes and reports progress."""
        since_last = [0]

        def chunk_cb(n_bytes: int):
            with _lock:
                _partial_bytes[0] += n_bytes
            since_last[0] += n_bytes
            if since_last[0] >= PROGRESS_CHUNK_BYTES:
                since_last[0] = 0
                if on_progress:
                    with _lock:
                        df = _done_files[0]
                        db = _done_bytes[0] + _partial_bytes[0]
                    on_progress(df, total_files, db, total_bytes)
        return chunk_cb

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_checksum_one, fp, run_folder, exclusions or [], _make_chunk_callback()): fp
            for fp in file_paths
        }
        for future in as_completed(futures):
            result = future.result()
            with _lock:
                _done_files[0] += 1
                if result is not None:
                    relative, digest, size = result
                    entries.append((relative, digest))
                    _done_bytes[0] += size
                    _partial_bytes[0] = max(0, _partial_bytes[0] - size)
                df = _done_files[0]
                db = _done_bytes[0]
            if on_progress:
                on_progress(df, total_files, db, total_bytes)

    # sort by hash — deterministic regardless of OS/filesystem walk order
    entries.sort(key=lambda e: e[1])

    logger.info(f"checksum array is: {entries}")

    with open(checksum_path, "w") as f:
        f.write("\n".join(digest for _, digest in entries) + "\n")

    logger.info(f"checksum file written: {len(entries)} files")

    # hash the checksum file itself and rename to <hash>.CHECKSUM
    file_hash  = _sha256(checksum_path)
    final_path = os.path.join(run_folder, f"{file_hash}.CHECKSUM")
    os.rename(checksum_path, final_path)

    logger.info(f"checksum file renamed to: {file_hash}.CHECKSUM")
    return final_path


def find_file_by_hash(run_folder: str, target_hash: str) -> str | None:
    """
    Walk the run folder and return the relative path of the file whose
    SHA256 matches target_hash. Returns None if not found.
    """
    logger.info(f"scanning run folder to resolve hash {target_hash}: {run_folder}")
    for root, dirs, files in os.walk(run_folder):
        for filename in files:
            file_path = os.path.join(root, filename)
            digest    = _sha256(file_path)
            logger.debug(f"checked: {os.path.relpath(file_path, run_folder)} → {digest}")
            if digest == target_hash:
                relative = os.path.relpath(file_path, run_folder)
                logger.info(f"hash match found: {relative}")
                return relative
    logger.warning(f"no file matched hash {target_hash} in {run_folder}")
    return None


def _fmt_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
