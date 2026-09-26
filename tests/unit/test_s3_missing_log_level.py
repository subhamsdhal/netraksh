import logging

from backend.services import evidence_storage


class MissingObjectError(Exception):
    response = {
        "ResponseMetadata": {"HTTPStatusCode": 404},
        "Error": {"Code": "NoSuchKey", "Message": "not found"},
    }


class AccessDeniedError(Exception):
    response = {
        "ResponseMetadata": {"HTTPStatusCode": 403},
        "Error": {"Code": "AccessDenied", "Message": "forbidden"},
    }


def test_optional_missing_s3_object_is_debug_not_warning(caplog):
    with caplog.at_level(logging.DEBUG, logger=evidence_storage.__name__):
        evidence_storage._log_s3_failure("get object", MissingObjectError())
    assert any(record.levelno == logging.DEBUG for record in caplog.records)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_real_s3_failure_remains_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=evidence_storage.__name__):
        evidence_storage._log_s3_failure("get object", AccessDeniedError())
    assert any(record.levelno == logging.WARNING for record in caplog.records)
