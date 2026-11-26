"""Masking secrets and credentials in requests and responses before they're stored.

Used by the proxy's ``--bodies`` log (and what is built from it, like HAR files).
What's masked, with ``***``:

* headers: ``Authorization``, ``X-Amz-Security-Token``, ``Cookie``/``Set-Cookie``;
* query parameters of presigned URLs: ``X-Amz-Signature``, ``X-Amz-Credential``,
  ``X-Amz-Security-Token``, ``Signature``, ``AWSAccessKeyId``;
* in JSON, form (query protocol) and XML bodies, the values of keys that hold secrets:
  any name with ``secret``, ``password``, ``token``, ``credential``, ``private key`` or
  ``access key`` in it (``SecretString``, ``Password``, ``SessionToken``…), except names
  that only point at one (``SecretId``, ``SecretArn``, ``KeyName``) and pagination tokens
  (``NextToken``, ``ContinuationToken``);
* the ``Value`` of an SSM ``SecureString`` parameter.

Values that merely look like secrets under other names (an environment variable called
``DB_URL``, a DynamoDB attribute called ``pwd``) aren't recognised.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

MASK = "***"
SENSITIVE_HEADERS = {"authorization", "x-amz-security-token", "cookie", "set-cookie", "proxy-authorization"}
SENSITIVE_QUERY = {"x-amz-signature", "x-amz-credential", "x-amz-security-token", "signature", "awsaccesskeyid"}
SECRET_RE = re.compile(r"secret|passw(or)?d|token|credential|private_?key|access_?key", re.IGNORECASE)
NOT_SECRET_RE = re.compile(
    r"(id|ids|arn|arns|name|names|type|types|policy|count|length|version|versionid|stage|stages|"
    r"rotation\w*|nexttoken|continuationtoken|paginationtoken|clienttoken|clientrequesttoken|"
    r"idempotencytoken|starttoken|marker|duration\w*|expir\w*|tokentype)$",
    re.IGNORECASE,
)
XML_TAG_RE = re.compile(r"<(?P<tag>[A-Za-z_][\w.\-]*)>(?P<value>[^<]*)</(?P=tag)>")


def sensitive_key(key: str) -> bool:
    name = key.rsplit(".", 1)[-1]  # form keys like Attributes.1.Value
    return bool(SECRET_RE.search(name)) and not NOT_SECRET_RE.search(name)


def headers(items) -> list[tuple[str, str]]:
    return [(k, MASK if k.lower() in SENSITIVE_HEADERS else v) for k, v in items]


def url(path: str) -> str:
    """A path (or URL) with the signature and credential query parameters masked."""
    parts = urlsplit(path)
    if not parts.query:
        return path
    query = [
        (k, MASK if k.lower() in SENSITIVE_QUERY or sensitive_key(k) else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote, safe="*")))


def _json_value(value):
    if isinstance(value, dict):
        secure = value.get("Type") == "SecureString"  # SSM: the parameter's value is the secret
        return {
            k: MASK if isinstance(k, str) and (sensitive_key(k) or (secure and k == "Value")) else _json_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    return value


def text_body(text: str, content_type: str = "") -> str:
    """A body (already decoded) with its secrets masked, in the same format."""
    stripped = text.lstrip()
    ct = content_type.lower()
    if stripped.startswith(("{", "[")) or "json" in ct:
        try:
            return json.dumps(_json_value(json.loads(text)), separators=(",", ":"))
        except ValueError:
            pass
    if stripped.startswith("<"):
        return XML_TAG_RE.sub(lambda m: f"<{m['tag']}>{MASK}</{m['tag']}>" if sensitive_key(m["tag"]) else m[0], text)
    if "x-www-form-urlencoded" in ct or ("=" in text and "&" in text and " " not in text):
        pairs = parse_qsl(text, keep_blank_values=True)
        if pairs:
            return urlencode([(k, MASK if sensitive_key(k) else v) for k, v in pairs])
    return text
