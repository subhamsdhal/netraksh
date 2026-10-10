from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from starlette.responses import FileResponse, Response, StreamingResponse

from backend.api.dashboard import _iter_file_range, _parse_byte_range, _video_file_response


def _request(range_header: str | None = None, method: str = "GET") -> Request:
    headers = [] if range_header is None else [(b"range", range_header.encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/media",
        "raw_path": b"/media",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_byte_range_parser_and_stream_support_bounded_open_and_suffix_ranges(tmp_path: Path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"abcdefgh")

    for header, expected_range, expected_body in [
        ("bytes=2-5", (2, 5), b"cdef"),
        ("bytes=5-", (5, 7), b"fgh"),
        ("bytes=7-", (7, 7), b"h"),
        ("BYTES=-3", (5, 7), b"fgh"),
    ]:
        byte_range = _parse_byte_range(header, 8)
        assert byte_range == expected_range
        start, end = byte_range
        assert b"".join(_iter_file_range(path, start, end - start + 1)) == expected_body


def test_video_file_response_returns_416_for_unsatisfiable_range(tmp_path: Path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"abcdefgh")

    with pytest.raises(ValueError, match="unsatisfiable byte range"):
        _parse_byte_range("bytes=8-", 8)
    with pytest.raises(ValueError, match="unsatisfiable byte range"):
        _parse_byte_range("bytes=-1", 0)


def test_malformed_or_multipart_ranges_are_ignored(tmp_path: Path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"abcdefgh")

    for header in ("bytes=bad", "bytes=1-2,4-5"):
        response = _video_file_response(path, _request(header))
        assert isinstance(response, FileResponse)
        assert response.status_code == 200
        assert dict(response.headers)["accept-ranges"] == "bytes"


def test_video_file_response_head_and_full_get_keep_expected_headers(tmp_path: Path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"abcdefgh")

    head = _video_file_response(path, _request("bytes=1-3", method="HEAD"))
    assert isinstance(head, Response)
    assert head.status_code == 206
    assert dict(head.headers)["content-range"] == "bytes 1-3/8"
    assert dict(head.headers)["content-length"] == "3"

    full = _video_file_response(path, _request())
    assert isinstance(full, FileResponse)
    assert full.status_code == 200
    assert dict(full.headers)["accept-ranges"] == "bytes"
    assert path.stat().st_size == 8

    ranged = _video_file_response(path, _request("bytes=1-3"))
    assert isinstance(ranged, StreamingResponse)
    assert ranged.status_code == 206
    assert dict(ranged.headers)["content-range"] == "bytes 1-3/8"
    assert dict(ranged.headers)["content-length"] == "3"
    assert dict(ranged.headers)["accept-ranges"] == "bytes"
    assert dict(ranged.headers)["content-type"] == "video/mp4"
    assert b"".join(_iter_file_range(path, 1, 3)) == b"bcd"


def test_empty_file_full_response_and_range(tmp_path: Path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")

    full = _video_file_response(path, _request())
    assert isinstance(full, FileResponse)
    assert full.status_code == 200
    assert dict(full.headers)["accept-ranges"] == "bytes"
    assert dict(full.headers)["content-type"] == "video/mp4"

    with pytest.raises(ValueError, match="unsatisfiable byte range"):
        _parse_byte_range("bytes=0-", 0)


def test_http_range_requests_return_exact_status_headers_and_bytes(tmp_path: Path):
    from fastapi.testclient import TestClient

    path = tmp_path / "sample.mp4"
    path.write_bytes(b"abcdefgh")
    app = FastAPI()

    @app.api_route("/media", methods=["GET", "HEAD"])
    async def media(request: Request):
        return _video_file_response(path, request)

    with TestClient(app) as client:
        full = client.get("/media")
        assert full.status_code == 200
        assert full.content == b"abcdefgh"
        assert full.headers["content-type"] == "video/mp4"
        assert full.headers["content-length"] == "8"
        assert full.headers["accept-ranges"] == "bytes"

        partial = client.get("/media", headers={"Range": "bytes=2-5"})
        assert partial.status_code == 206
        assert partial.content == b"cdef"
        assert partial.headers["content-range"] == "bytes 2-5/8"
        assert partial.headers["content-length"] == "4"
        assert partial.headers["content-type"] == "video/mp4"
        assert partial.headers["accept-ranges"] == "bytes"

        suffix = client.get("/media", headers={"Range": "bytes=-3"})
        assert suffix.status_code == 206
        assert suffix.content == b"fgh"
        assert suffix.headers["content-range"] == "bytes 5-7/8"

        eof = client.get("/media", headers={"Range": "bytes=7-"})
        assert eof.status_code == 206
        assert eof.content == b"h"

        unsatisfiable = client.get("/media", headers={"Range": "bytes=8-"})
        assert unsatisfiable.status_code == 416
        assert unsatisfiable.headers["content-range"] == "bytes */8"

        head = client.head("/media", headers={"Range": "bytes=1-3"})
        assert head.status_code == 206
        assert head.content == b""
        assert head.headers["content-range"] == "bytes 1-3/8"
        assert head.headers["content-length"] == "3"
