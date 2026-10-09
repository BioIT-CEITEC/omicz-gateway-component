"""Settings with a fixed set of values or hard numeric limits refuse anything else."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.repositories.settings import InvalidSettingValue, validate_value


@pytest.mark.parametrize("key,value", [
    ("upload_engine", "s5cmd"),
    ("upload_s5cmd_workers", "16"),
    ("upload_s5cmd_concurrency", "1"),
    ("upload_s5cmd_part_size_mb", "5"),
    ("upload_s5cmd_part_size_mb", "5120"),
    ("verify_interval", "anything"),        # no limits declared
])
def test_valid_values_pass(key, value):
    validate_value(key, value)


@pytest.mark.parametrize("key,value", [
    ("upload_engine", "rclone"),
    ("upload_s5cmd_workers", "0"),
    ("upload_s5cmd_concurrency", "65"),
    ("upload_s5cmd_part_size_mb", "4"),
    ("upload_s5cmd_part_size_mb", "5121"),
    ("upload_s5cmd_part_size_mb", "64.5"),
    ("upload_s5cmd_part_size_mb", "big"),
])
def test_invalid_values_are_refused(key, value):
    with pytest.raises(InvalidSettingValue):
        validate_value(key, value)
