import glob
import hashlib
import os

from core.logger import get_logger

logger = get_logger("checksum")

CHECKSUM_FILENAME = "checksum.CHECKSUM"

def create_checksum_file(run_name: str, sequencer_location: str) -> str:
    """
    Walk every file inside the run folder, compute SHA256 for each
    """
    run_folder    = os.path.join(sequencer_location, run_name)
    checksum_path = os.path.join(run_folder, CHECKSUM_FILENAME)

    # if a *.CHECKSUM file already exists (e.g. retry after failed upload), reuse it
    existing = glob.glob(os.path.join(run_folder, "*.CHECKSUM"))
    if existing:
        logger.info(f"checksum file already exists — skipping creation: {os.path.basename(existing[0])}")
        return existing[0]

    # collect (relative_path, digest) for every file
    entries = []
    for root, dirs, files in os.walk(run_folder):
        for filename in files:
            if filename == CHECKSUM_FILENAME:
                continue  # don't hash the checksum file itself

            file_path = os.path.join(root, filename)
            relative  = os.path.relpath(file_path, run_folder)
            digest    = _sha256(file_path)
            entries.append((relative, digest))
            logger.info(f"checksummed: {relative}")

    # sort by hash — deterministic regardless of OS/filesystem walk order
    entries.sort(key=lambda e: e[1])

    logger.info(f"checksum array is: {entries}")

    with open(checksum_path, "w") as f:
        f.write("\n".join(digest for _, digest in entries) + "\n") # The _ discards the relative path — only hashes are written to the file.

    logger.info(f"checksum file written: {len(entries)} files")

    # Hash the checksum file itself and rename it to <hash>.checksum
    file_hash = _sha256(checksum_path)
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
            digest = _sha256(file_path)
            logger.debug(f"checked: {os.path.relpath(file_path, run_folder)} → {digest}")
            if digest == target_hash:
                relative = os.path.relpath(file_path, run_folder)
                logger.info(f"hash match found: {relative}")
                return relative
    logger.warning(f"no file matched hash {target_hash} in {run_folder}")
    return None


def _sha256(file_path: str) -> str:
    h = hashlib.sha256() # EMpty hash object
    with open(file_path, "rb") as f: # rb = ready binary
        for chunk in iter(lambda: f.read(8192), b""): # 8192 bytes at a time (8 KB) / b"" (empty bytes = end of file)
            h.update(chunk) # update the hash object with the chunk of data read from the file
    return h.hexdigest() # return final hash as hex string
