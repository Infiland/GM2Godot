#!/usr/bin/env python3
"""Create and publish a GitHub release without adopting foreign state.

Ownership is established only by validated ``201 Created`` responses from this
process. Read requests confirm state, but their identifiers are never promoted
to ownership receipts.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from typing import BinaryIO, Protocol, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit


API_VERSION = "2026-03-10"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
MAX_PAGES = 100
OWNED_DRAFT_VISIBILITY_SNAPSHOTS = 7
MAX_OWNERSHIP_RETRY_DELAY_SECONDS = 32.0
DEFAULT_RECEIPT_PATH = Path("release-receipt/release-publisher.json")
DEFAULT_ASSET_ROOT = Path("artifacts")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
REPOSITORY_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?\Z"
)


class TransportError(RuntimeError):
    """The HTTP exchange did not produce a complete bounded response."""


class SchemaError(ValueError):
    """A GitHub response failed the publisher contract."""


class PublishError(RuntimeError):
    """A terminal publisher failure with recovery metadata."""

    def __init__(
        self,
        phase: str,
        message: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.status = status
        self.request_id = request_id
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class FileSeal:
    path: Path
    name: str
    content_type: str
    size: int
    sha256: str
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class ApiResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class TransportResult:
    response: ApiResponse
    streamed_size: int | None = None
    streamed_sha256: str | None = None


@dataclass(frozen=True)
class ApiPayload:
    status: int
    headers: Mapping[str, str]
    value: object | None
    streamed_size: int | None = None
    streamed_sha256: str | None = None

    @property
    def request_id(self) -> str | None:
        value = self.headers.get("x-github-request-id")
        return value if value else None


@dataclass(frozen=True)
class ReleaseIdentity:
    release_id: int
    api_url: str
    html_url: str
    assets_url: str
    upload_url: str
    browser_tag_segment: str


@dataclass(frozen=True)
class AssetReceipt:
    asset_id: int
    name: str
    size: int
    digest: str
    content_type: str
    api_url: str
    browser_download_url: str


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: bytes | None = None,
        file_body: FileSeal | None = None,
    ) -> TransportResult:
        """Perform exactly one HTTP request without redirects or retries."""

        raise NotImplementedError


def _fingerprint(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _expected_fingerprint(seal: FileSeal) -> tuple[int, int, int, int, int]:
    return (seal.device, seal.inode, seal.size, seal.mtime_ns, seal.ctime_ns)


@contextmanager
def _open_regular(path: Path) -> Generator[BinaryIO, None, None]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"Cannot open regular release asset {path}: {error}") from error
    handle = os.fdopen(descriptor, "rb")
    try:
        file_stat = os.fstat(handle.fileno())
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"Release asset is not a regular file: {path}")
        yield handle
    finally:
        handle.close()


def seal_file(path: Path, name: str, content_type: str) -> FileSeal:
    """Hash a fixed regular file and retain its identity for upload."""

    with _open_regular(path) as handle:
        initial = os.fstat(handle.fileno())
        if initial.st_size <= 0:
            raise ValueError(f"Release asset is empty: {path}")
        hasher = hashlib.sha256()
        while chunk := handle.read(STREAM_CHUNK_BYTES):
            hasher.update(chunk)
        digest = hasher.hexdigest()
        final = os.fstat(handle.fileno())
    if _fingerprint(initial) != _fingerprint(final):
        raise ValueError(f"Release asset changed while it was sealed: {path}")
    return FileSeal(
        path=path,
        name=name,
        content_type=content_type,
        size=initial.st_size,
        sha256=digest,
        device=initial.st_dev,
        inode=initial.st_ino,
        mtime_ns=initial.st_mtime_ns,
        ctime_ns=initial.st_ctime_ns,
    )


class HttpsTransport:
    """Small streaming HTTPS transport with no redirect or retry behavior."""

    def __init__(self, *, timeout_seconds: float = 300.0) -> None:
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: bytes | None = None,
        file_body: FileSeal | None = None,
    ) -> TransportResult:
        if json_body is not None and file_body is not None:
            raise TransportError("An HTTP request cannot have two bodies.")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise TransportError(f"Refusing unsafe GitHub API URL: {url!r}")
        request_target = parsed.path or "/"
        if parsed.query:
            request_target = f"{request_target}?{parsed.query}"

        connection = http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port,
            timeout=self._timeout_seconds,
        )
        streamed_size: int | None = None
        streamed_digest: str | None = None
        try:
            connection.putrequest(method, request_target, skip_accept_encoding=True)
            for header, value in headers.items():
                if "\r" in header or "\n" in header or "\r" in value or "\n" in value:
                    raise TransportError("Refusing an HTTP header containing a line break.")
                connection.putheader(header, value)
            connection.endheaders()

            if json_body is not None:
                connection.send(json_body)
            elif file_body is not None:
                streamed_size, streamed_digest = self._stream_file(connection, file_body)

            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise TransportError(f"GitHub API response exceeded {MAX_RESPONSE_BYTES} bytes.")
            response_headers: dict[str, str] = {}
            for name, value in response.getheaders():
                normalized_name = name.casefold()
                if normalized_name == "link" and normalized_name in response_headers:
                    response_headers[normalized_name] = f"{response_headers[normalized_name]}, {value}"
                else:
                    response_headers[normalized_name] = value
            return TransportResult(
                response=ApiResponse(
                    status=response.status,
                    headers=response_headers,
                    body=body,
                ),
                streamed_size=streamed_size,
                streamed_sha256=streamed_digest,
            )
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            raise TransportError(str(error)) from error
        finally:
            connection.close()

    @staticmethod
    def _stream_file(
        connection: http.client.HTTPSConnection,
        seal: FileSeal,
    ) -> tuple[int, str]:
        sent_size = 0
        digest = hashlib.sha256()
        with _open_regular(seal.path) as handle:
            initial = os.fstat(handle.fileno())
            if _fingerprint(initial) != _expected_fingerprint(seal):
                raise TransportError(f"Release asset changed after sealing: {seal.path}")
            while chunk := handle.read(STREAM_CHUNK_BYTES):
                connection.send(chunk)
                digest.update(chunk)
                sent_size += len(chunk)
            final = os.fstat(handle.fileno())
        streamed_digest = digest.hexdigest()
        if (
            _fingerprint(final) != _expected_fingerprint(seal)
            or sent_size != seal.size
            or streamed_digest != seal.sha256
        ):
            raise TransportError(f"Release asset changed while it was uploaded: {seal.path}")
        return sent_size, streamed_digest


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _safe_error_body(body: bytes) -> str:
    if not body:
        return "empty response body"
    try:
        value = cast(object, json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "non-JSON response body"
    if not isinstance(value, dict):
        return "unexpected JSON response"
    raw_object = cast(dict[object, object], value)
    message = raw_object.get("message")
    if not isinstance(message, str) or not message:
        return "GitHub API error without a message"
    return re.sub(r"[\r\n]+", " ", message)[:500]


def pagination_has_next(
    headers: Mapping[str, str],
    *,
    api_origin: str,
    expected_path: str,
    canonical_suffix: str,
    current_page: int,
) -> bool:
    link_header = headers.get("link")
    if link_header is None:
        return False
    next_urls: list[str] = []
    for raw_part in link_header.split(","):
        part = raw_part.strip()
        match = re.fullmatch(r"<([^<>]+)>(.*)", part)
        if match is None:
            raise SchemaError("GitHub pagination Link header was malformed.")
        linked_url, raw_parameters = match.groups()
        relations: list[str] = []
        for raw_parameter in raw_parameters.split(";"):
            parameter = raw_parameter.strip()
            if not parameter:
                continue
            key, separator, value = parameter.partition("=")
            if not separator:
                raise SchemaError("GitHub pagination Link parameter was malformed.")
            if key.casefold() == "rel":
                if len(value) < 2 or value[0] != '"' or value[-1] != '"':
                    raise SchemaError("GitHub pagination rel parameter was not quoted.")
                relations.extend(value[1:-1].split())
        if "next" in relations:
            next_urls.append(linked_url)
    if not next_urls:
        return False
    if len(next_urls) != 1:
        raise SchemaError("GitHub pagination exposed multiple next links.")
    next_url = urlsplit(next_urls[0])
    origin = urlsplit(api_origin)
    if (
        next_url.scheme != origin.scheme
        or next_url.netloc != origin.netloc
        or (
            next_url.path != expected_path
            and re.fullmatch(
                rf"/repositories/[1-9][0-9]*{re.escape(canonical_suffix)}",
                next_url.path,
            )
            is None
        )
        or next_url.fragment
        or next_url.username is not None
        or next_url.password is not None
    ):
        raise SchemaError("GitHub pagination next link left the expected API endpoint.")
    query_pairs = parse_qsl(next_url.query, keep_blank_values=True)
    if sorted(query_pairs) != sorted((("page", str(current_page + 1)), ("per_page", "100"))):
        raise SchemaError("GitHub pagination next link had unexpected query parameters.")
    return True


class GitHubApi:
    """Strict GitHub REST client used by the ownership state machine."""

    def __init__(
        self,
        transport: Transport,
        *,
        repository: str,
        token: str,
        api_origin: str,
        upload_origin: str,
    ) -> None:
        self._transport = transport
        self.repository = repository
        self.api_origin = api_origin.rstrip("/")
        self.upload_origin = upload_origin.rstrip("/")
        self._common_headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "GM2Godot-create-only-release-publisher/1",
            "X-GitHub-Api-Version": API_VERSION,
            "Connection": "close",
        }

    def _request_json(
        self,
        phase: str,
        method: str,
        url: str,
        *,
        accepted_statuses: Sequence[int],
        no_json_statuses: Sequence[int] = (),
        body: Mapping[str, object] | None = None,
        file_body: FileSeal | None = None,
    ) -> ApiPayload:
        headers = dict(self._common_headers)
        json_body: bytes | None = None
        if body is not None:
            json_body = _json_bytes(body)
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(json_body))
        elif file_body is not None:
            headers["Content-Type"] = file_body.content_type
            headers["Content-Length"] = str(file_body.size)

        mutation = method != "GET"
        try:
            result = self._transport.request(
                method,
                url,
                headers,
                json_body=json_body,
                file_body=file_body,
            )
        except (TransportError, ValueError) as error:
            raise PublishError(
                phase,
                f"GitHub API transport failed during {phase}: {error}",
                ambiguous=mutation,
            ) from error

        response = result.response
        request_id = response.headers.get("x-github-request-id")
        if response.status not in accepted_statuses:
            raise PublishError(
                phase,
                f"GitHub API returned HTTP {response.status} during {phase}: {_safe_error_body(response.body)}",
                status=response.status,
                request_id=request_id,
                ambiguous=mutation and (200 <= response.status < 300 or response.status >= 500),
            )
        if response.status in no_json_statuses:
            return ApiPayload(
                status=response.status,
                headers=response.headers,
                value=None,
                streamed_size=result.streamed_size,
                streamed_sha256=result.streamed_sha256,
            )
        try:
            value = cast(object, json.loads(response.body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PublishError(
                phase,
                f"GitHub API returned malformed JSON during {phase}: {error}",
                status=response.status,
                request_id=request_id,
                ambiguous=mutation,
            ) from error
        return ApiPayload(
            status=response.status,
            headers=response.headers,
            value=value,
            streamed_size=result.streamed_size,
            streamed_sha256=result.streamed_sha256,
        )

    def get_ref(self, phase: str, ref: str, *, allow_missing: bool) -> ApiPayload:
        encoded_ref = quote(ref, safe="/")
        statuses = (200, 404) if allow_missing else (200,)
        return self._request_json(
            phase,
            "GET",
            f"{self.api_origin}/repos/{self.repository}/git/ref/{encoded_ref}",
            accepted_statuses=statuses,
            no_json_statuses=(404,),
        )

    def create_ref(self, ref: str, sha: str) -> ApiPayload:
        return self._request_json(
            "create-tag-ref",
            "POST",
            f"{self.api_origin}/repos/{self.repository}/git/refs",
            accepted_statuses=(201,),
            body={"ref": ref, "sha": sha},
        )

    def list_releases(self, phase: str) -> list[dict[str, object]]:
        releases: list[dict[str, object]] = []
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({"per_page": 100, "page": page})
            payload = self._request_json(
                phase,
                "GET",
                f"{self.api_origin}/repos/{self.repository}/releases?{query}",
                accepted_statuses=(200,),
            )
            try:
                values = _expect_list(payload.value, f"{phase} release page {page}")
                for index, value in enumerate(values):
                    releases.append(
                        _expect_object(
                            value,
                            f"{phase} release page {page} item {index}",
                        )
                    )
                has_next = pagination_has_next(
                    payload.headers,
                    api_origin=self.api_origin,
                    expected_path=f"/repos/{self.repository}/releases",
                    canonical_suffix="/releases",
                    current_page=page,
                )
            except SchemaError as error:
                raise PublishError(
                    phase,
                    f"Release listing schema failed during {phase}: {error}",
                    status=payload.status,
                    request_id=payload.request_id,
                ) from error
            if not has_next and len(values) < 100:
                return releases
        raise PublishError(
            phase,
            f"Release listing exceeded the bounded {MAX_PAGES}-page limit.",
        )

    def create_draft_release(self, tag: str, name: str, target_sha: str) -> ApiPayload:
        return self._request_json(
            "create-draft-release",
            "POST",
            f"{self.api_origin}/repos/{self.repository}/releases",
            accepted_statuses=(201,),
            body={
                "tag_name": tag,
                "target_commitish": target_sha,
                "name": name,
                "draft": True,
                "prerelease": False,
                "generate_release_notes": True,
                "make_latest": "false",
            },
        )

    def get_release(self, phase: str, release_id: int) -> ApiPayload:
        return self._request_json(
            phase,
            "GET",
            f"{self.api_origin}/repos/{self.repository}/releases/{release_id}",
            accepted_statuses=(200,),
        )

    def get_release_by_tag(
        self,
        phase: str,
        tag: str,
        *,
        allow_missing: bool,
    ) -> ApiPayload:
        statuses = (200, 404) if allow_missing else (200,)
        return self._request_json(
            phase,
            "GET",
            f"{self.api_origin}/repos/{self.repository}/releases/tags/{quote(tag, safe='')}",
            accepted_statuses=statuses,
            no_json_statuses=(404,),
        )

    def list_assets(self, phase: str, release_id: int) -> list[dict[str, object]]:
        assets: list[dict[str, object]] = []
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({"per_page": 100, "page": page})
            payload = self._request_json(
                phase,
                "GET",
                f"{self.api_origin}/repos/{self.repository}/releases/{release_id}/assets?{query}",
                accepted_statuses=(200,),
            )
            try:
                values = _expect_list(payload.value, f"{phase} asset page {page}")
                for index, value in enumerate(values):
                    assets.append(
                        _expect_object(
                            value,
                            f"{phase} asset page {page} item {index}",
                        )
                    )
                has_next = pagination_has_next(
                    payload.headers,
                    api_origin=self.api_origin,
                    expected_path=(f"/repos/{self.repository}/releases/{release_id}/assets"),
                    canonical_suffix=f"/releases/{release_id}/assets",
                    current_page=page,
                )
            except SchemaError as error:
                raise PublishError(
                    phase,
                    f"Asset listing schema failed during {phase}: {error}",
                    status=payload.status,
                    request_id=payload.request_id,
                ) from error
            if not has_next and len(values) < 100:
                return assets
        raise PublishError(
            phase,
            f"Asset listing exceeded the bounded {MAX_PAGES}-page limit.",
        )

    def upload_asset(self, release_id: int, seal: FileSeal) -> ApiPayload:
        query = urlencode({"name": seal.name}, quote_via=quote)
        return self._request_json(
            f"upload-{seal.name}",
            "POST",
            f"{self.upload_origin}/repos/{self.repository}/releases/{release_id}/assets?{query}",
            accepted_statuses=(201,),
            file_body=seal,
        )

    def publish_release(self, release_id: int) -> ApiPayload:
        return self._request_json(
            "publish-owned-release",
            "PATCH",
            f"{self.api_origin}/repos/{self.repository}/releases/{release_id}",
            accepted_statuses=(200,),
            body={"draft": False, "prerelease": False, "make_latest": "true"},
        )


def _expect_object(value: object | None, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SchemaError(f"{context} was not a JSON object with string keys.")
    raw_object = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw_object):
        raise SchemaError(f"{context} was not a JSON object with string keys.")
    return {cast(str, key): item for key, item in raw_object.items()}


def _expect_list(value: object | None, context: str) -> list[object]:
    if not isinstance(value, list):
        raise SchemaError(f"{context} was not a JSON array.")
    return cast(list[object], value)


def _required_string(value: Mapping[str, object], key: str, context: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise SchemaError(f"{context}.{key} was not a non-empty string.")
    return result


def _required_int(value: Mapping[str, object], key: str, context: str) -> int:
    result = value.get(key)
    if type(result) is not int or result <= 0:
        raise SchemaError(f"{context}.{key} was not a positive integer.")
    return result


def _required_bool(value: Mapping[str, object], key: str, context: str) -> bool:
    result = value.get(key)
    if type(result) is not bool:
        raise SchemaError(f"{context}.{key} was not a boolean.")
    return result


def _validate_timestamp(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{context} was not a non-empty timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SchemaError(f"{context} was not a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise SchemaError(f"{context} did not include a timezone.")
    return value


def validate_ref(
    value: object | None,
    *,
    repository: str,
    api_origin: str,
    ref: str,
    sha: str,
) -> dict[str, object]:
    receipt = _expect_object(value, "git reference")
    if _required_string(receipt, "ref", "git reference") != f"refs/{ref}":
        raise SchemaError("Git reference receipt named a different ref.")
    expected_url = f"{api_origin}/repos/{repository}/git/refs/{quote(ref, safe='/')}"
    if _required_string(receipt, "url", "git reference") != expected_url:
        raise SchemaError("Git reference receipt had a noncanonical URL.")
    _required_string(receipt, "node_id", "git reference")
    target = _expect_object(receipt.get("object"), "git reference.object")
    if _required_string(target, "type", "git reference.object") != "commit":
        raise SchemaError("Git reference did not resolve directly to a commit.")
    if _required_string(target, "sha", "git reference.object") != sha:
        raise SchemaError("Git reference resolved to the wrong commit SHA.")
    expected_commit_url = f"{api_origin}/repos/{repository}/git/commits/{sha}"
    if _required_string(target, "url", "git reference.object") != expected_commit_url:
        raise SchemaError("Git reference object had a noncanonical commit URL.")
    return receipt


def _validate_draft_html_url(html_url: str, repository: str, tag: str) -> str:
    parsed = urlsplit(html_url)
    expected_prefix = f"/{repository}/releases/tag/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or not parsed.path.startswith(expected_prefix)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise SchemaError("Draft release had an unsafe or noncanonical HTML URL.")
    tag_segment = parsed.path.removeprefix(expected_prefix)
    if (
        not tag_segment
        or "/" in tag_segment
        or (tag_segment != tag and re.fullmatch(r"untagged-[A-Za-z0-9._-]+", tag_segment) is None)
    ):
        raise SchemaError("Draft release HTML URL had an unexpected tag segment.")
    return tag_segment


def validate_release(
    value: object | None,
    *,
    repository: str,
    api_origin: str,
    upload_origin: str,
    tag: str,
    name: str,
    expected_id: int | None,
    draft: bool,
    require_empty_assets: bool = False,
) -> ReleaseIdentity:
    release = _expect_object(value, "release")
    release_id = _required_int(release, "id", "release")
    if expected_id is not None and release_id != expected_id:
        raise SchemaError(f"Release identity drifted from owned id={expected_id} to id={release_id}.")
    if _required_string(release, "tag_name", "release") != tag:
        raise SchemaError("Release receipt named a different tag.")
    if _required_string(release, "name", "release") != name:
        raise SchemaError("Release receipt named a different release.")
    if _required_bool(release, "draft", "release") is not draft:
        raise SchemaError("Release draft state did not match the expected phase.")
    if _required_bool(release, "prerelease", "release"):
        raise SchemaError("Release unexpectedly became a prerelease.")

    api_url = f"{api_origin}/repos/{repository}/releases/{release_id}"
    assets_url = f"{api_url}/assets"
    upload_url = f"{upload_origin}/repos/{repository}/releases/{release_id}/assets{{?name,label}}"
    if _required_string(release, "url", "release") != api_url:
        raise SchemaError("Release receipt had a noncanonical API URL.")
    if _required_string(release, "assets_url", "release") != assets_url:
        raise SchemaError("Release receipt had a noncanonical assets URL.")
    if _required_string(release, "upload_url", "release") != upload_url:
        raise SchemaError("Release receipt had a noncanonical upload URL.")

    html_url = _required_string(release, "html_url", "release")
    if draft:
        browser_tag_segment = _validate_draft_html_url(html_url, repository, tag)
    elif html_url != f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}":
        raise SchemaError("Published release had a noncanonical HTML URL.")
    else:
        browser_tag_segment = tag

    _required_string(release, "node_id", "release")
    _required_string(release, "target_commitish", "release")
    _validate_timestamp(release.get("created_at"), "release.created_at")
    published_at = release.get("published_at")
    if draft:
        if published_at is not None:
            raise SchemaError("Draft release unexpectedly had a publication timestamp.")
    else:
        _validate_timestamp(published_at, "release.published_at")
    immutable = release.get("immutable")
    if immutable is not None and type(immutable) is not bool:
        raise SchemaError("release.immutable was not a boolean.")
    if draft and immutable is True:
        raise SchemaError("Owned draft unexpectedly became immutable.")
    assets = _expect_list(release.get("assets"), "release.assets")
    if require_empty_assets and assets:
        raise SchemaError("Newly created draft already contained release assets.")
    return ReleaseIdentity(
        release_id=release_id,
        api_url=api_url,
        html_url=html_url,
        assets_url=assets_url,
        upload_url=upload_url,
        browser_tag_segment=browser_tag_segment,
    )


def validate_asset(
    value: object | None,
    *,
    repository: str,
    api_origin: str,
    browser_tag_segment: str,
    seal: FileSeal,
) -> AssetReceipt:
    asset = _expect_object(value, f"asset {seal.name}")
    asset_id = _required_int(asset, "id", f"asset {seal.name}")
    if _required_string(asset, "name", f"asset {seal.name}") != seal.name:
        raise SchemaError(f"Asset receipt named a different file than {seal.name}.")
    if _required_string(asset, "state", f"asset {seal.name}") != "uploaded":
        raise SchemaError(f"Asset {seal.name} did not reach uploaded state.")
    if _required_int(asset, "size", f"asset {seal.name}") != seal.size:
        raise SchemaError(f"Asset {seal.name} size differed from the sealed file.")
    if _required_string(asset, "content_type", f"asset {seal.name}") != seal.content_type:
        raise SchemaError(f"Asset {seal.name} content type differed from the upload.")
    digest = _required_string(asset, "digest", f"asset {seal.name}")
    if digest != f"sha256:{seal.sha256}":
        raise SchemaError(f"Asset {seal.name} digest differed from the sealed file.")
    label = asset.get("label")
    if label is not None and label != "":
        raise SchemaError(f"Asset {seal.name} unexpectedly had a label.")
    api_url = f"{api_origin}/repos/{repository}/releases/assets/{asset_id}"
    browser_url = (
        f"https://github.com/{repository}/releases/download/"
        f"{quote(browser_tag_segment, safe='')}/"
        f"{quote(seal.name, safe='')}"
    )
    if _required_string(asset, "url", f"asset {seal.name}") != api_url:
        raise SchemaError(f"Asset {seal.name} had a noncanonical API URL.")
    if _required_string(asset, "browser_download_url", f"asset {seal.name}") != browser_url:
        raise SchemaError(f"Asset {seal.name} had a noncanonical download URL.")
    _required_string(asset, "node_id", f"asset {seal.name}")
    _validate_timestamp(asset.get("created_at"), f"asset {seal.name}.created_at")
    _validate_timestamp(asset.get("updated_at"), f"asset {seal.name}.updated_at")
    return AssetReceipt(
        asset_id=asset_id,
        name=seal.name,
        size=seal.size,
        digest=digest,
        content_type=seal.content_type,
        api_url=api_url,
        browser_download_url=browser_url,
    )


@dataclass(frozen=True)
class PublisherConfig:
    repository: str
    token: str
    tag: str
    release_name: str
    target_sha: str
    run_id: str
    run_attempt: str
    run_url: str
    api_origin: str
    upload_origin: str
    receipt_path: Path
    asset_root: Path
    preflight_delay_seconds: float
    ownership_retry_delay_seconds: float

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> PublisherConfig:
        def required(name: str) -> str:
            value = environment.get(name, "")
            if not value:
                raise ValueError(f"Required publisher environment is missing: {name}")
            if "\r" in value or "\n" in value:
                raise ValueError(f"Publisher environment contains a line break: {name}")
            return value

        repository = required("GITHUB_REPOSITORY")
        if REPOSITORY_PATTERN.fullmatch(repository) is None:
            raise ValueError(f"Invalid GITHUB_REPOSITORY: {repository!r}")
        github_ref = required("GITHUB_REF")
        if github_ref != "refs/heads/main":
            raise ValueError("Release publication is restricted to the exact refs/heads/main event ref.")
        if required("GITHUB_REF_TYPE") != "branch":
            raise ValueError("Release publication requires a branch event ref.")
        event_name = required("GITHUB_EVENT_NAME")
        if event_name not in {"push", "workflow_dispatch"}:
            raise ValueError(f"Release publication is not allowed for event {event_name!r}.")

        github_sha = required("GITHUB_SHA")
        target_sha = required("RELEASE_TARGET_SHA")
        if SHA_PATTERN.fullmatch(github_sha) is None or target_sha != github_sha:
            raise ValueError("RELEASE_TARGET_SHA must equal the exact 40-hex main event GITHUB_SHA.")
        tag = required("RELEASE_TAG")
        if TAG_PATTERN.fullmatch(tag) is None:
            raise ValueError(f"Invalid release tag: {tag!r}")
        release_name = required("RELEASE_NAME")
        if release_name != f"GM2Godot {tag}":
            raise ValueError("RELEASE_NAME did not match the fixed GM2Godot tag title.")

        server_url = required("GITHUB_SERVER_URL").rstrip("/")
        api_origin = required("GITHUB_API_URL").rstrip("/")
        if server_url != "https://github.com" or api_origin != "https://api.github.com":
            raise ValueError("This publisher is restricted to canonical GitHub.com origins.")
        upload_origin = "https://uploads.github.com"
        run_id = required("GITHUB_RUN_ID")
        run_attempt = required("GITHUB_RUN_ATTEMPT")
        if not run_id.isdecimal() or not run_attempt.isdecimal():
            raise ValueError("GITHUB_RUN_ID and GITHUB_RUN_ATTEMPT must be decimal integers.")

        receipt_path = Path(environment.get("RELEASE_RECEIPT_PATH", str(DEFAULT_RECEIPT_PATH)))
        asset_root = Path(environment.get("RELEASE_ASSET_ROOT", str(DEFAULT_ASSET_ROOT)))
        for label, path in (("receipt", receipt_path), ("asset root", asset_root)):
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Publisher {label} path must stay relative to the workspace.")
        delay_text = environment.get("RELEASE_PREFLIGHT_RETRY_DELAY_SECONDS", "1")
        try:
            delay = float(delay_text)
        except ValueError as error:
            raise ValueError("Invalid release preflight retry delay.") from error
        if not 0 <= delay <= 10:
            raise ValueError("Release preflight retry delay must be between 0 and 10 seconds.")
        ownership_delay_text = environment.get(
            "RELEASE_OWNERSHIP_RETRY_DELAY_SECONDS",
            "1",
        )
        try:
            ownership_delay = float(ownership_delay_text)
        except ValueError as error:
            raise ValueError("Invalid release ownership retry delay.") from error
        if not 0 <= ownership_delay <= 1:
            raise ValueError("Release ownership retry delay must be between 0 and 1 second.")

        return cls(
            repository=repository,
            token=required("GITHUB_TOKEN"),
            tag=tag,
            release_name=release_name,
            target_sha=target_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            run_url=(f"{server_url}/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"),
            api_origin=api_origin,
            upload_origin=upload_origin,
            receipt_path=receipt_path,
            asset_root=asset_root,
            preflight_delay_seconds=delay,
            ownership_retry_delay_seconds=ownership_delay,
        )


class ReceiptStore:
    """Atomically persist enough state for manual, ID-first recovery."""

    def __init__(self, config: PublisherConfig) -> None:
        self._config = config
        self.stage = "initializing"
        self.expected_assets: list[dict[str, object]] = []
        self.mutation_intents: list[dict[str, object]] = []
        self.observations: list[dict[str, object]] = []
        self.tag_receipt: dict[str, object] | None = None
        self.release_receipt: dict[str, object] | None = None
        self.asset_receipts: list[dict[str, object]] = []
        self.failure: dict[str, object] | None = None
        self.save()

    def _document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "stage": self.stage,
            "repository": self._config.repository,
            "tag": self._config.tag,
            "release_name": self._config.release_name,
            "target_sha": self._config.target_sha,
            "run": {
                "id": self._config.run_id,
                "attempt": self._config.run_attempt,
                "url": self._config.run_url,
            },
            "expected_assets": self.expected_assets,
            "mutation_intents": self.mutation_intents,
            "observations": self.observations,
            "tag_receipt": self.tag_receipt,
            "release_receipt": self.release_receipt,
            "asset_receipts": self.asset_receipts,
            "failure": self.failure,
        }

    def save(self) -> None:
        destination = self._config.receipt_path
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            dir=destination.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    self._document(),
                    handle,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def set_assets(self, assets: Sequence[FileSeal]) -> None:
        self.expected_assets = [
            {
                "name": asset.name,
                "path": str(asset.path),
                "content_type": asset.content_type,
                "size": asset.size,
                "digest": f"sha256:{asset.sha256}",
            }
            for asset in assets
        ]
        self.stage = "sealed"
        self.save()

    def observe(self, phase: str, **values: object) -> None:
        self.observations.append({"phase": phase, **values})
        self.save()

    def begin_mutation(self, phase: str, **values: object) -> int:
        self.stage = phase
        self.mutation_intents.append({"phase": phase, "state": "pending", **values})
        self.save()
        return len(self.mutation_intents) - 1

    def accept_mutation(
        self,
        index: int,
        *,
        status: int,
        request_id: str | None,
        **values: object,
    ) -> None:
        intent = self.mutation_intents[index]
        intent.update(
            {
                "state": "accepted",
                "status": status,
                "request_id": request_id,
                **values,
            }
        )
        self.save()

    def record_failure(self, error: PublishError, owned_release_id: int | None) -> None:
        self.stage = "failed"
        self.failure = {
            "phase": error.phase,
            "message": str(error),
            "status": error.status,
            "request_id": error.request_id,
            "ambiguous": error.ambiguous,
            "owned_release_id": owned_release_id,
            "completed_asset_names": [str(receipt["name"]) for receipt in self.asset_receipts],
        }
        self.save()


class ReleasePublisher:
    def __init__(
        self,
        config: PublisherConfig,
        api: GitHubApi,
        receipt: ReceiptStore,
    ) -> None:
        self.config = config
        self.api = api
        self.receipt = receipt
        self.assets: tuple[FileSeal, ...] = ()
        self.owned_release: ReleaseIdentity | None = None
        self.uploaded: list[AssetReceipt] = []

    @property
    def owned_release_id(self) -> int | None:
        return self.owned_release.release_id if self.owned_release is not None else None

    def run(self) -> None:
        self.assets = self._seal_assets()
        self.receipt.set_assets(self.assets)
        self._verify_main_target()
        self._late_preflight()
        self._claim_tag()
        self._create_owned_draft()
        for index, asset in enumerate(self.assets):
            self._ownership_gate(index)
            self._upload(asset)
        self._ownership_gate(len(self.assets))
        self._publish()
        self._verify_final_state()
        self.receipt.stage = "verified"
        self.receipt.failure = None
        self.receipt.save()

    def _seal_assets(self) -> tuple[FileSeal, ...]:
        root = self.config.asset_root
        specifications = (
            (root / "GM2Godot-windows/GM2Godot-windows.zip", "application/zip"),
            (root / "GM2Godot-macos/GM2Godot-macos.zip", "application/zip"),
            (
                root / "GM2Godot-macos/GM2Godot-macos.dmg",
                "application/x-apple-diskimage",
            ),
            (root / "GM2Godot-linux/GM2Godot-linux.zip", "application/zip"),
            (root / "SHA256SUMS", "application/octet-stream"),
        )
        try:
            assets = tuple(seal_file(path, path.name, content_type) for path, content_type in specifications)
            self._validate_manifest(assets)
            return assets
        except (OSError, ValueError) as error:
            raise PublishError("seal-assets", str(error)) from error

    @staticmethod
    def _validate_manifest(assets: Sequence[FileSeal]) -> None:
        by_name = {asset.name: asset for asset in assets}
        manifest = by_name["SHA256SUMS"]
        payload_order = (
            "GM2Godot-linux.zip",
            "GM2Godot-macos.dmg",
            "GM2Godot-macos.zip",
            "GM2Godot-windows.zip",
        )
        expected = "".join(f"{by_name[name].sha256}  {name}\n" for name in payload_order).encode("ascii")
        try:
            with _open_regular(manifest.path) as handle:
                initial = os.fstat(handle.fileno())
                if _fingerprint(initial) != _expected_fingerprint(manifest):
                    raise ValueError("SHA256SUMS changed after it was sealed.")
                actual = handle.read(manifest.size + 1)
                final = os.fstat(handle.fileno())
        except OSError as error:
            raise ValueError(f"Cannot read checksum manifest: {error}") from error
        if _fingerprint(final) != _expected_fingerprint(manifest):
            raise ValueError("SHA256SUMS changed while it was validated.")
        if actual != expected:
            raise ValueError("SHA256SUMS is not the exact canonical four-line manifest for the sealed payloads.")

    def _verify_main_target(self) -> None:
        phase = "verify-main-target"
        payload = self.api.get_ref(phase, "heads/main", allow_missing=False)
        self._validate_read_ref(payload, "heads/main", self.config.target_sha, phase)
        self.receipt.observe(phase, target_sha=self.config.target_sha)

    def _late_preflight(self) -> None:
        for attempt in range(1, 4):
            phase = f"late-preflight-{attempt}"
            tag_payload = self.api.get_ref(
                phase,
                f"tags/{self.config.tag}",
                allow_missing=True,
            )
            if tag_payload.status != 404:
                raise PublishError(
                    phase,
                    f"Exact tag {self.config.tag} appeared before run ownership was claimed.",
                    status=tag_payload.status,
                    request_id=tag_payload.request_id,
                )
            matches = self._exact_release_matches(self.api.list_releases(phase), phase)
            if matches:
                identifiers = ", ".join(str(match.get("id", "invalid")) for match in matches)
                raise PublishError(
                    phase,
                    f"Exact release state already exists for {self.config.tag}: candidate ids={identifiers}.",
                )
            self.receipt.observe(phase, tag_absent=True, exact_release_ids=[])
            if attempt < 3 and self.config.preflight_delay_seconds:
                time.sleep(self.config.preflight_delay_seconds)
        self.receipt.stage = "preflighted"
        self.receipt.save()

    def _claim_tag(self) -> None:
        full_ref = f"refs/tags/{self.config.tag}"
        intent = self.receipt.begin_mutation(
            "create-tag-ref",
            method="POST",
            endpoint=f"/repos/{self.config.repository}/git/refs",
            ref=full_ref,
            target_sha=self.config.target_sha,
        )
        payload = self.api.create_ref(full_ref, self.config.target_sha)
        try:
            validated = validate_ref(
                payload.value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                ref=f"tags/{self.config.tag}",
                sha=self.config.target_sha,
            )
        except SchemaError as error:
            raise PublishError(
                "create-tag-ref",
                f"Create-tag 201 receipt was invalid: {error}",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            ) from error
        self.receipt.tag_receipt = {
            "ref": validated["ref"],
            "url": validated["url"],
            "target_sha": self.config.target_sha,
            "status": payload.status,
            "request_id": payload.request_id,
        }
        self.receipt.accept_mutation(
            intent,
            status=payload.status,
            request_id=payload.request_id,
            owned_ref=full_ref,
        )

    def _create_owned_draft(self) -> None:
        intent = self.receipt.begin_mutation(
            "create-draft-release",
            method="POST",
            endpoint=f"/repos/{self.config.repository}/releases",
            tag=self.config.tag,
        )
        payload = self.api.create_draft_release(
            self.config.tag,
            self.config.release_name,
            self.config.target_sha,
        )
        try:
            identity = validate_release(
                payload.value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                upload_origin=self.config.upload_origin,
                tag=self.config.tag,
                name=self.config.release_name,
                expected_id=None,
                draft=True,
                require_empty_assets=True,
            )
        except SchemaError as error:
            raise PublishError(
                "create-draft-release",
                f"Create-release 201 receipt was invalid: {error}",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            ) from error
        self.owned_release = identity
        self.receipt.release_receipt = {
            "id": identity.release_id,
            "api_url": identity.api_url,
            "create_html_url": identity.html_url,
            "assets_url": identity.assets_url,
            "upload_url": identity.upload_url,
            "browser_tag_segment": identity.browser_tag_segment,
            "status": payload.status,
            "request_id": payload.request_id,
        }
        self.receipt.accept_mutation(
            intent,
            status=payload.status,
            request_id=payload.request_id,
            owned_release_id=identity.release_id,
        )

    def _ownership_gate(self, uploaded_count: int) -> None:
        """Allow bounded convergence only while the exact-tag match set is empty."""

        identity = self._require_owned_release()
        phase = f"ownership-gate-{uploaded_count}"
        next_mutation = (
            f"upload-{self.assets[uploaded_count].name}"
            if uploaded_count < len(self.assets)
            else "publish-owned-release"
        )
        uploaded_asset_names = [receipt.name for receipt in self.uploaded]

        for snapshot_attempt in range(1, OWNED_DRAFT_VISIBILITY_SNAPSHOTS + 1):
            ref_payload = self.api.get_ref(
                phase,
                f"tags/{self.config.tag}",
                allow_missing=False,
            )
            self._validate_read_ref(
                ref_payload,
                f"tags/{self.config.tag}",
                self.config.target_sha,
                phase,
            )

            release_payload = self.api.get_release(phase, identity.release_id)
            self._validate_read_release(
                release_payload,
                identity.release_id,
                draft=True,
                phase=phase,
            )
            listed_assets = self.api.list_assets(phase, identity.release_id)
            self._validate_asset_inventory(
                listed_assets,
                self.uploaded,
                phase,
                draft=True,
            )

            published = self.api.get_release_by_tag(
                phase,
                self.config.tag,
                allow_missing=True,
            )
            if published.status != 404:
                foreign_id = "unknown"
                try:
                    foreign_id = str(
                        _required_int(
                            _expect_object(published.value, "published collision"),
                            "id",
                            "published collision",
                        )
                    )
                except SchemaError:
                    pass
                raise PublishError(
                    phase,
                    f"A published exact-tag release appeared while owned draft "
                    f"id={identity.release_id} was gated; published id={foreign_id}.",
                    status=published.status,
                    request_id=published.request_id,
                )

            listed_releases: list[dict[str, object]] | None = None
            try:
                listed_releases = self.api.list_releases(phase)
                matches = self._exact_release_matches(listed_releases, phase)
            except PublishError as error:
                self.receipt.observe(
                    f"{phase}-snapshot-{snapshot_attempt}",
                    snapshot_attempt=snapshot_attempt,
                    snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                    decision="fail-list-read",
                    next_mutation=next_mutation,
                    tag_sha=self.config.target_sha,
                    owned_release_id=identity.release_id,
                    exact_release_ids=None,
                    listed_release_count=(len(listed_releases) if listed_releases is not None else None),
                    uploaded_asset_names=uploaded_asset_names,
                    error=str(error),
                )
                raise
            match_ids = [self._release_id_for_diagnostic(match) for match in matches]
            observation_phase = phase if match_ids == [identity.release_id] else f"{phase}-snapshot-{snapshot_attempt}"
            if match_ids == [identity.release_id]:
                try:
                    self._validate_read_release_object(
                        matches[0],
                        identity.release_id,
                        draft=True,
                        phase=phase,
                    )
                except PublishError as error:
                    self.receipt.observe(
                        f"{phase}-snapshot-{snapshot_attempt}",
                        snapshot_attempt=snapshot_attempt,
                        snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                        decision="fail-owned-schema",
                        next_mutation=next_mutation,
                        tag_sha=self.config.target_sha,
                        owned_release_id=identity.release_id,
                        exact_release_ids=match_ids,
                        listed_release_count=len(listed_releases),
                        uploaded_asset_names=uploaded_asset_names,
                        error=str(error),
                    )
                    raise
                self.receipt.observe(
                    observation_phase,
                    snapshot_attempt=snapshot_attempt,
                    snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                    decision="accept-owned",
                    next_mutation=next_mutation,
                    tag_sha=self.config.target_sha,
                    owned_release_id=identity.release_id,
                    exact_release_ids=match_ids,
                    listed_release_count=len(listed_releases),
                    uploaded_asset_names=uploaded_asset_names,
                )
                return

            if match_ids:
                self.receipt.observe(
                    observation_phase,
                    snapshot_attempt=snapshot_attempt,
                    snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                    decision="fail-identity-drift",
                    next_mutation=next_mutation,
                    tag_sha=self.config.target_sha,
                    owned_release_id=identity.release_id,
                    exact_release_ids=match_ids,
                    listed_release_count=len(listed_releases),
                    uploaded_asset_names=uploaded_asset_names,
                )
                raise PublishError(
                    phase,
                    f"Exact-tag release identity drift before the next mutation: "
                    f"owned id={identity.release_id}, observed ids={match_ids}.",
                )

            if snapshot_attempt == OWNED_DRAFT_VISIBILITY_SNAPSHOTS:
                self.receipt.observe(
                    observation_phase,
                    snapshot_attempt=snapshot_attempt,
                    snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                    decision="fail-empty-exhausted",
                    next_mutation=next_mutation,
                    tag_sha=self.config.target_sha,
                    owned_release_id=identity.release_id,
                    exact_release_ids=[],
                    listed_release_count=len(listed_releases),
                    uploaded_asset_names=uploaded_asset_names,
                )
                raise PublishError(
                    phase,
                    f"Owned draft exact-tag visibility did not converge before "
                    f"the next mutation: owned id={identity.release_id}, "
                    f"observed ids=[] after "
                    f"{OWNED_DRAFT_VISIBILITY_SNAPSHOTS} snapshots.",
                )

            retry_delay = min(
                self.config.ownership_retry_delay_seconds * (2 ** (snapshot_attempt - 1)),
                MAX_OWNERSHIP_RETRY_DELAY_SECONDS,
            )
            self.receipt.observe(
                observation_phase,
                snapshot_attempt=snapshot_attempt,
                snapshot_limit=OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
                decision="retry-empty",
                retry_delay_seconds=retry_delay,
                next_mutation=next_mutation,
                tag_sha=self.config.target_sha,
                owned_release_id=identity.release_id,
                exact_release_ids=[],
                listed_release_count=len(listed_releases),
                uploaded_asset_names=uploaded_asset_names,
            )
            if retry_delay:
                time.sleep(retry_delay)

    def _upload(self, asset: FileSeal) -> None:
        identity = self._require_owned_release()
        phase = f"upload-{asset.name}"
        endpoint = (
            f"https://uploads.github.com/repos/{self.config.repository}/releases/"
            f"{identity.release_id}/assets?name={quote(asset.name, safe='')}"
        )
        intent = self.receipt.begin_mutation(
            phase,
            method="POST",
            endpoint=endpoint,
            owned_release_id=identity.release_id,
            asset=asset.name,
            size=asset.size,
            digest=f"sha256:{asset.sha256}",
        )
        payload = self.api.upload_asset(identity.release_id, asset)
        if payload.streamed_size != asset.size or payload.streamed_sha256 != asset.sha256:
            raise PublishError(
                phase,
                f"Upload stream receipt did not match sealed asset {asset.name}.",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            )
        try:
            receipt = validate_asset(
                payload.value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                browser_tag_segment=identity.browser_tag_segment,
                seal=asset,
            )
        except SchemaError as error:
            raise PublishError(
                phase,
                f"Asset upload 201 receipt was invalid: {error}",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            ) from error
        if any(existing.asset_id == receipt.asset_id for existing in self.uploaded):
            raise PublishError(
                phase,
                f"Asset upload reused owned asset id={receipt.asset_id}.",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            )
        self.uploaded.append(receipt)
        receipt_document: dict[str, object] = {
            "id": receipt.asset_id,
            "name": receipt.name,
            "size": receipt.size,
            "digest": receipt.digest,
            "content_type": receipt.content_type,
            "api_url": receipt.api_url,
            "upload_browser_download_url": receipt.browser_download_url,
            "status": payload.status,
            "request_id": payload.request_id,
        }
        self.receipt.asset_receipts.append(receipt_document)
        self.receipt.accept_mutation(
            intent,
            status=payload.status,
            request_id=payload.request_id,
            owned_release_id=identity.release_id,
            owned_asset_id=receipt.asset_id,
        )

    def _publish(self) -> None:
        identity = self._require_owned_release()
        intent = self.receipt.begin_mutation(
            "publish-owned-release",
            method="PATCH",
            endpoint=f"/repos/{self.config.repository}/releases/{identity.release_id}",
            owned_release_id=identity.release_id,
        )
        payload = self.api.publish_release(identity.release_id)
        try:
            validate_release(
                payload.value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                upload_origin=self.config.upload_origin,
                tag=self.config.tag,
                name=self.config.release_name,
                expected_id=identity.release_id,
                draft=False,
            )
        except SchemaError as error:
            raise PublishError(
                "publish-owned-release",
                f"Publish 200 receipt was invalid: {error}",
                status=payload.status,
                request_id=payload.request_id,
                ambiguous=True,
            ) from error
        self.receipt.accept_mutation(
            intent,
            status=payload.status,
            request_id=payload.request_id,
            owned_release_id=identity.release_id,
        )

    def _verify_final_state(self) -> None:
        identity = self._require_owned_release()
        phase = "final-verification"
        by_id = self.api.get_release(phase, identity.release_id)
        self._validate_read_release(
            by_id,
            identity.release_id,
            draft=False,
            phase=phase,
        )
        by_tag = self.api.get_release_by_tag(
            phase,
            self.config.tag,
            allow_missing=False,
        )
        self._validate_read_release(
            by_tag,
            identity.release_id,
            draft=False,
            phase=phase,
        )
        ref_payload = self.api.get_ref(
            phase,
            f"tags/{self.config.tag}",
            allow_missing=False,
        )
        self._validate_read_ref(
            ref_payload,
            f"tags/{self.config.tag}",
            self.config.target_sha,
            phase,
        )
        listed_assets = self.api.list_assets(phase, identity.release_id)
        self._validate_asset_inventory(
            listed_assets,
            self.uploaded,
            phase,
            draft=False,
        )
        for receipt_document in self.receipt.asset_receipts:
            asset_name = str(receipt_document["name"])
            receipt_document["published_browser_download_url"] = (
                f"https://github.com/{self.config.repository}/releases/download/"
                f"{quote(self.config.tag, safe='')}/{quote(asset_name, safe='')}"
            )
        self.receipt.save()
        matches = self._exact_release_matches(self.api.list_releases(phase), phase)
        match_ids = [self._release_id_for_diagnostic(match) for match in matches]
        if match_ids != [identity.release_id]:
            raise PublishError(
                phase,
                f"Final exact-tag listing was not the sole owned release: "
                f"owned id={identity.release_id}, observed ids={match_ids}.",
            )
        self._validate_read_release_object(
            matches[0],
            identity.release_id,
            draft=False,
            phase=phase,
        )
        self.receipt.observe(
            phase,
            owned_release_id=identity.release_id,
            published=True,
            tag_sha=self.config.target_sha,
            asset_ids=[receipt.asset_id for receipt in self.uploaded],
        )
        if self.receipt.release_receipt is not None:
            self.receipt.release_receipt["published_html_url"] = (
                f"https://github.com/{self.config.repository}/releases/tag/{quote(self.config.tag, safe='')}"
            )
            self.receipt.save()

    def _validate_read_ref(
        self,
        payload: ApiPayload,
        ref: str,
        sha: str,
        phase: str,
    ) -> None:
        try:
            validate_ref(
                payload.value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                ref=ref,
                sha=sha,
            )
        except SchemaError as error:
            raise PublishError(
                phase,
                f"Reference verification failed: {error}",
                status=payload.status,
                request_id=payload.request_id,
            ) from error

    def _validate_read_release(
        self,
        payload: ApiPayload,
        release_id: int,
        *,
        draft: bool,
        phase: str,
    ) -> None:
        self._validate_read_release_object(
            payload.value,
            release_id,
            draft=draft,
            phase=phase,
            status=payload.status,
            request_id=payload.request_id,
        )

    def _validate_read_release_object(
        self,
        value: object | None,
        release_id: int,
        *,
        draft: bool,
        phase: str,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        try:
            observed = validate_release(
                value,
                repository=self.config.repository,
                api_origin=self.config.api_origin,
                upload_origin=self.config.upload_origin,
                tag=self.config.tag,
                name=self.config.release_name,
                expected_id=release_id,
                draft=draft,
            )
            if (
                draft
                and self.owned_release is not None
                and (
                    observed.html_url != self.owned_release.html_url
                    or observed.browser_tag_segment != self.owned_release.browser_tag_segment
                )
            ):
                raise SchemaError("Owned draft HTML identity changed after creation.")
        except SchemaError as error:
            raise PublishError(
                phase,
                f"Owned release verification failed: {error}",
                status=status,
                request_id=request_id,
            ) from error

    def _validate_asset_inventory(
        self,
        values: Sequence[Mapping[str, object]],
        expected_receipts: Sequence[AssetReceipt],
        phase: str,
        *,
        draft: bool,
    ) -> None:
        expected_by_name = {receipt.name: receipt for receipt in expected_receipts}
        if len(values) != len(expected_by_name):
            raise PublishError(
                phase,
                f"Owned release asset count drifted: expected {len(expected_by_name)}, observed {len(values)}.",
            )
        observed_names: set[str] = set()
        observed_ids: set[int] = set()
        for value in values:
            name_value = value.get("name")
            if not isinstance(name_value, str) or name_value not in expected_by_name:
                raise PublishError(
                    phase,
                    f"Owned release contained an unexpected asset name: {name_value!r}.",
                )
            if name_value in observed_names:
                raise PublishError(
                    phase,
                    f"Owned release contained duplicate asset name {name_value!r}.",
                )
            expected = expected_by_name[name_value]
            seal = next(asset for asset in self.assets if asset.name == name_value)
            identity = self._require_owned_release()
            try:
                actual = validate_asset(
                    value,
                    repository=self.config.repository,
                    api_origin=self.config.api_origin,
                    browser_tag_segment=(identity.browser_tag_segment if draft else self.config.tag),
                    seal=seal,
                )
            except SchemaError as error:
                raise PublishError(
                    phase,
                    f"Owned asset verification failed: {error}",
                ) from error
            if (
                actual.asset_id != expected.asset_id
                or actual.name != expected.name
                or actual.size != expected.size
                or actual.digest != expected.digest
                or actual.content_type != expected.content_type
                or actual.api_url != expected.api_url
            ):
                raise PublishError(
                    phase,
                    f"Owned asset receipt drifted for {name_value}.",
                )
            if actual.asset_id in observed_ids:
                raise PublishError(
                    phase,
                    f"Owned release reused asset id={actual.asset_id}.",
                )
            observed_names.add(name_value)
            observed_ids.add(actual.asset_id)

    def _exact_release_matches(
        self,
        releases: Sequence[Mapping[str, object]],
        phase: str,
    ) -> list[Mapping[str, object]]:
        matches: list[Mapping[str, object]] = []
        for index, release in enumerate(releases):
            tag_name = release.get("tag_name")
            if not isinstance(tag_name, str) or not tag_name:
                raise PublishError(
                    phase,
                    f"Release listing item {index} lacked a non-empty tag_name.",
                )
            if tag_name == self.config.tag:
                matches.append(release)
        return matches

    @staticmethod
    def _release_id_for_diagnostic(release: Mapping[str, object]) -> int | str:
        release_id = release.get("id")
        return release_id if type(release_id) is int and release_id > 0 else "invalid"

    def _require_owned_release(self) -> ReleaseIdentity:
        if self.owned_release is None:
            raise PublishError(
                "ownership",
                "No validated create-release 201 ownership receipt exists.",
            )
        return self.owned_release


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _print_recovery(config: PublisherConfig, owned_release_id: int | None) -> None:
    encoded_tag = quote(config.tag, safe="")
    print(
        "Manual recovery only; do not rerun, adopt, delete, or roll back state "
        "until ownership is proven from this run receipt.",
        file=sys.stderr,
    )
    print(
        f"Run receipt: {config.receipt_path} (run: {config.run_url})",
        file=sys.stderr,
    )
    print(
        f"Inspect exact ref: {config.api_origin}/repos/{config.repository}/git/ref/tags/{encoded_tag}",
        file=sys.stderr,
    )
    if owned_release_id is None:
        print(
            "Owned release ID: no validated 201 receipt; creation outcome may be unknown.",
            file=sys.stderr,
        )
        print(
            f"Inspect the authenticated draft-aware release listing: "
            f"{config.api_origin}/repos/{config.repository}/releases?per_page=100",
            file=sys.stderr,
        )
    else:
        print(
            f"Inspect owned release ID first: {config.api_origin}/repos/"
            f"{config.repository}/releases/{owned_release_id}",
            file=sys.stderr,
        )


def main(environment: Mapping[str, str] | None = None) -> int:
    selected_environment = os.environ if environment is None else environment
    try:
        config = PublisherConfig.from_environment(selected_environment)
    except ValueError as error:
        print(f"::error::{_annotation_escape(str(error))}", file=sys.stderr)
        return 1

    try:
        receipt = ReceiptStore(config)
    except OSError as error:
        print(
            f"::error::{_annotation_escape(f'Cannot initialize release receipt: {error}')}",
            file=sys.stderr,
        )
        return 1

    api = GitHubApi(
        HttpsTransport(),
        repository=config.repository,
        token=config.token,
        api_origin=config.api_origin,
        upload_origin=config.upload_origin,
    )
    publisher = ReleasePublisher(config, api, receipt)
    try:
        publisher.run()
    except PublishError as error:
        try:
            receipt.record_failure(error, publisher.owned_release_id)
        except OSError as receipt_error:
            print(
                f"::error::{_annotation_escape(f'Cannot update release receipt: {receipt_error}')}",
                file=sys.stderr,
            )
        print(f"::error::{_annotation_escape(str(error))}", file=sys.stderr)
        _print_recovery(config, publisher.owned_release_id)
        return 1
    except Exception as error:  # pragma: no cover - final safety boundary
        failure = PublishError(
            "unexpected",
            f"Unexpected publisher failure: {type(error).__name__}: {error}",
            ambiguous=publisher.owned_release_id is not None,
        )
        try:
            receipt.record_failure(failure, publisher.owned_release_id)
        except OSError:
            pass
        print(f"::error::{_annotation_escape(str(failure))}", file=sys.stderr)
        _print_recovery(config, publisher.owned_release_id)
        return 1

    identity = publisher.owned_release
    if identity is None:  # pragma: no cover - guarded by successful run
        print("::error::Publisher completed without an owned release receipt.", file=sys.stderr)
        return 1
    print(
        f"Published run-owned release id={identity.release_id} tag={config.tag} "
        f"target={config.target_sha} url=https://github.com/{config.repository}/"
        f"releases/tag/{config.tag}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
