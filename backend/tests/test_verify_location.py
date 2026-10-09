"""The TRE confirmation is read from S3_CHECKSUM_BUCKET under S3_CHECKSUM_PREFIX."""
import io
import os
import sys

from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import tre


class FakeS3:
    def __init__(self, objects):
        self.objects, self.asked = objects, []

    def get_object(self, Bucket, Key):
        self.asked.append((Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def use(monkeypatch, objects, bucket, prefix):
    fake = FakeS3(objects)
    monkeypatch.setattr(tre.boto3, "client", lambda *a, **kw: fake)
    monkeypatch.setattr(tre, "S3_CHECKSUM_BUCKET", bucket)
    monkeypatch.setattr(tre, "S3_CHECKSUM_PREFIX", prefix)
    return fake


def test_separate_checksums_bucket_without_prefix(monkeypatch):
    fake = use(monkeypatch, {("checksums", "abc.CHECKSUM"): b""}, "checksums", "")
    assert tre.check_verify_status("abc.CHECKSUM") == {"status": "success"}
    assert fake.asked == [("checksums", "abc.CHECKSUM")]


def test_folder_inside_the_upload_bucket(monkeypatch):
    fake = use(monkeypatch, {("omicz-gateway", "checksums/abc.CHECKSUM"): b"sha mismatch\n"},
               "omicz-gateway", "checksums/")
    assert tre.check_verify_status("abc.CHECKSUM") == {"status": "failed", "detail": "sha mismatch"}
    assert fake.asked == [("omicz-gateway", "checksums/abc.CHECKSUM")]


def test_missing_confirmation_is_pending(monkeypatch):
    use(monkeypatch, {}, "omicz-gateway", "checksums/")
    assert tre.check_verify_status("abc.CHECKSUM") == {"status": "pending"}
