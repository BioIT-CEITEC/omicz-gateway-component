"""
Multipart upload of large files: a rejected part is retried on its own instead of
restarting the whole file (the TRE proxy answers an occasional UploadPart with a bare 400).
"""
import os
import sys
import threading

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import tre

MIB = 1024 * 1024


def client_error(status, code=""):
    return ClientError({"Error": {"Code": code, "Message": ""},
                        "ResponseMetadata": {"HTTPStatusCode": status, "HTTPHeaders": {}}}, "UploadPart")


class FakeS3:
    """Records parts; fail_parts maps part number → how many times it is rejected first."""

    def __init__(self, fail_parts=None, error=None):
        self.fail_parts = dict(fail_parts or {})
        self.error      = error or client_error(400)
        self.parts      = {}
        self.calls      = []
        self.completed  = None
        self.aborted    = False
        self._lock      = threading.Lock()

    def create_multipart_upload(self, Bucket, Key):
        return {"UploadId": "u1"}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        with self._lock:
            self.calls.append(PartNumber)
            if self.fail_parts.get(PartNumber, 0) > 0:
                self.fail_parts[PartNumber] -= 1
                raise self.error
            self.parts[PartNumber] = Body
        return {"ETag": f'"etag{PartNumber}"'}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self.completed = MultipartUpload["Parts"]

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted = True


@pytest.fixture
def big_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tre, "_MULTIPART_THRESHOLD", 1 * MIB)
    monkeypatch.setattr(tre, "_MULTIPART_CHUNKSIZE", 1 * MIB)
    monkeypatch.setattr(tre.time, "sleep", lambda s: None)
    data = os.urandom(5 * MIB + 123)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    return str(path), data


def test_rejected_part_is_retried_alone(big_file):
    path, data = big_file
    s3, sent = FakeS3(fail_parts={3: 2}), []
    tre._upload_file(s3, path, "b", "k", on_bytes=sent.append)

    assert s3.calls.count(3) == 3                                  # part 3: two 400s, then OK
    assert all(s3.calls.count(n) == 1 for n in (1, 2, 4, 5, 6))   # the others sent once
    assert b"".join(s3.parts[n] for n in sorted(s3.parts)) == data
    assert [p["PartNumber"] for p in s3.completed] == [1, 2, 3, 4, 5, 6]
    assert sum(sent) == len(data)                                   # progress counts each byte once
    assert not s3.aborted


def test_part_failing_every_attempt_aborts_upload(big_file):
    path, _ = big_file
    s3 = FakeS3(fail_parts={2: 99})
    with pytest.raises(ClientError):
        tre._upload_file(s3, path, "b", "k", max_attempts=3)
    assert s3.calls.count(2) == 3
    assert s3.aborted and s3.completed is None


def test_precondition_failed_means_already_on_s3(big_file):
    path, _ = big_file
    s3 = FakeS3(fail_parts={1: 1}, error=client_error(412, "PreconditionFailed"))
    tre._upload_file(s3, path, "b", "k")          # no exception: skipped
    assert s3.calls.count(1) == 1                 # not retried
    assert s3.completed is None


def test_part_size_stays_under_s3_part_limit():
    assert tre._part_size(100 * 1000**3) == 16 * MIB              # 100 GB → 16 MiB parts (≈6 000)
    size = 1000**4                                                  # 1 TB needs bigger parts
    part = tre._part_size(size)
    assert part % MIB == 0 and -(-size // part) <= tre._MAX_PARTS
