import hashlib
import os

from core.logger import get_logger

logger = get_logger("checksum")

CHECKSUM_FILENAME = "checksum.txt"

def create_checksum_file(run_name: str, sequencer_location: str) -> str:
    """
    Walk every file inside the run folder, compute SHA256 for each
    """
    run_folder    = os.path.join(sequencer_location, run_name)
    checksum_path = os.path.join(run_folder, CHECKSUM_FILENAME)

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

    logger.info(f"checksum.txt written: {len(entries)} files")
    return checksum_path


def _sha256(file_path: str) -> str:
    h = hashlib.sha256() # EMpty hash object
    with open(file_path, "rb") as f: # rb = ready binary
        for chunk in iter(lambda: f.read(8192), b""): # 8192 bytes at a time (8 KB) / b"" (empty bytes = end of file)
            h.update(chunk) # update the hash object with the chunk of data read from the file
    return h.hexdigest() # return final hash as hex string
