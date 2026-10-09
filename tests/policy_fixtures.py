"""GitHub file metadata whose blob identity describes its exact raw bytes."""

import base64
import hashlib


def blob_sha(raw):
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
    ).hexdigest()


def file_response(path, text):
    raw = text.encode("utf-8")
    return dict(
        type="file",
        path=path,
        sha=blob_sha(raw),
        encoding="base64",
        size=len(raw),
        content=base64.b64encode(raw).decode(),
    )
