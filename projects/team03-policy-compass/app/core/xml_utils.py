"""Small helpers for distinguishing empty XML results from API error envelopes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection

_SUCCESS_CODES = {"0", "00", "000", "200", "ok", "success"}
_ERROR_CONTAINER_TAGS = {
    "error",
    "errors",
    "fault",
    "faultstring",
    "errormessage",
    "errmsg",
}
_RESULT_CODE_TAGS = {"code", "errorcode", "resultcode", "resultcd", "returncode"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def xml_error_message(root: ET.Element, *, record_tags: Collection[str]) -> str | None:
    """Return a bounded error description only when no expected records exist.

    Some public APIs answer HTTP 200 with a parseable ``<error>`` or a failed
    ``resultCode``.  Treating that envelope as an empty list would falsely tell
    users that no matching policy exists.
    """

    normalized_records = {tag.lower() for tag in record_tags}
    if any(_local_name(node.tag) in normalized_records for node in root.iter()):
        return None

    for node in root.iter():
        tag = _local_name(node.tag)
        text = " ".join((node.text or "").split())
        if tag in _ERROR_CONTAINER_TAGS:
            return (text or "API error envelope")[:300]
        if tag in _RESULT_CODE_TAGS and text and text.lower() not in _SUCCESS_CODES:
            return f"{tag}={text}"[:300]
    return None
