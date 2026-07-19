from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Literal, cast
import unittest
from unittest.mock import patch

from scripts import release_publisher as publisher_module


REPOSITORY = "Infiland/GM2Godot"
TAG = "v0.7.18"
RELEASE_NAME = f"GM2Godot {TAG}"
TARGET_SHA = "a" * 40
OWNED_RELEASE_ID = 7001
FOREIGN_RELEASE_ID = 9009
HISTORICAL_RELEASE_ID = 6001
HISTORICAL_TAG = "v0.7.17"
DRAFT_TAG_SEGMENT = "untagged-4f85c190bafb4cdda230"
API_ORIGIN = "https://api.github.com"
UPLOAD_ORIGIN = "https://uploads.github.com"
API_ROOT = f"{API_ORIGIN}/repos/{REPOSITORY}"
UPLOAD_ROOT = f"{UPLOAD_ORIGIN}/repos/{REPOSITORY}"
LIST_RELEASES_URL = f"{API_ROOT}/releases?per_page=100&page=1"

ASSET_ORDER = (
    "GM2Godot-windows.zip",
    "GM2Godot-macos.zip",
    "GM2Godot-macos.dmg",
    "GM2Godot-linux.zip",
    "SHA256SUMS",
)
PAYLOAD_ORDER = (
    "GM2Godot-linux.zip",
    "GM2Godot-macos.dmg",
    "GM2Godot-macos.zip",
    "GM2Godot-windows.zip",
)
ASSET_CONTENT_TYPES = {
    "GM2Godot-windows.zip": "application/zip",
    "GM2Godot-macos.zip": "application/zip",
    "GM2Godot-macos.dmg": "application/x-apple-diskimage",
    "GM2Godot-linux.zip": "application/zip",
    "SHA256SUMS": "application/octet-stream",
}

FaultKind = Literal[
    "tag-present",
    "foreign-preflight-release",
    "tag-transport-error",
    "tag-conflict",
    "tag-validation-error",
    "tag-drift",
    "mutation-auth-error",
    "malformed-json",
    "unexpected-success",
    "release-collision",
    "release-transport-error",
    "release-wrong-success",
    "invalid-draft-receipt",
    "owned-id-drift",
    "foreign-published-release",
    "duplicate-exact-release",
    "upload-transport-error",
    "upload-server-error",
    "upload-collision",
    "invalid-upload-receipt",
    "upload-stream-size-mismatch",
    "upload-stream-digest-mismatch",
    "upload-reused-id",
    "publish-transport-error",
    "publish-server-error",
    "publish-id-drift",
    "asset-digest-drift",
    "unexpected-draft-asset",
]


@dataclass(frozen=True)
class ExpectedCall:
    method: str
    url: str
    role: str
    json_value: Mapping[str, object] | None = None
    asset_name: str | None = None


@dataclass(frozen=True)
class ObservedCall:
    ordinal: int
    method: str
    url: str
    json_body: bytes | None
    asset_name: str | None


@dataclass(frozen=True)
class FailureCase:
    name: str
    ordinal: int
    fault: FaultKind
    phase: str
    status: int | None
    ambiguous: bool
    owned_release_id: int | None
    uploaded_count: int
    mutation_intent_count: int
    accepted_mutation_count: int
    error_substring: str
    external_uploaded_count: int | None = None
    published: bool = False


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _happy_ledger() -> tuple[ExpectedCall, ...]:
    tag_ref_url = f"{API_ROOT}/git/ref/tags/{TAG}"
    release_url = f"{API_ROOT}/releases/{OWNED_RELEASE_ID}"
    asset_list_url = f"{release_url}/assets?per_page=100&page=1"
    by_tag_url = f"{API_ROOT}/releases/tags/{TAG}"

    def gate() -> list[ExpectedCall]:
        return [
            ExpectedCall("GET", tag_ref_url, "owned-tag-ref"),
            ExpectedCall("GET", release_url, "draft-release"),
            ExpectedCall("GET", asset_list_url, "draft-assets"),
            ExpectedCall("GET", by_tag_url, "published-release-absent"),
            ExpectedCall("GET", LIST_RELEASES_URL, "draft-release-list"),
        ]

    calls = [
        ExpectedCall("GET", f"{API_ROOT}/git/ref/heads/main", "main-ref"),
    ]
    for _ in range(3):
        calls.extend(
            (
                ExpectedCall("GET", tag_ref_url, "preflight-tag-absent"),
                ExpectedCall("GET", LIST_RELEASES_URL, "preflight-release-list"),
            )
        )
    calls.extend(
        (
            ExpectedCall(
                "POST",
                f"{API_ROOT}/git/refs",
                "create-tag",
                json_value={"ref": f"refs/tags/{TAG}", "sha": TARGET_SHA},
            ),
            ExpectedCall(
                "POST",
                f"{API_ROOT}/releases",
                "create-draft",
                json_value={
                    "tag_name": TAG,
                    "target_commitish": TARGET_SHA,
                    "name": RELEASE_NAME,
                    "draft": True,
                    "prerelease": False,
                    "generate_release_notes": True,
                    "make_latest": "false",
                },
            ),
        )
    )
    for asset_name in ASSET_ORDER:
        calls.extend(gate())
        calls.append(
            ExpectedCall(
                "POST",
                f"{UPLOAD_ROOT}/releases/{OWNED_RELEASE_ID}/assets?name={asset_name}",
                "upload",
                asset_name=asset_name,
            )
        )
    calls.extend(gate())
    calls.append(
        ExpectedCall(
            "PATCH",
            f"{API_ROOT}/releases/{OWNED_RELEASE_ID}",
            "publish",
            json_value={
                "draft": False,
                "prerelease": False,
                "make_latest": "true",
            },
        )
    )
    calls.extend(
        (
            ExpectedCall(
                "GET",
                f"{API_ROOT}/releases/{OWNED_RELEASE_ID}",
                "published-release",
            ),
            ExpectedCall(
                "GET",
                f"{API_ROOT}/releases/tags/{TAG}",
                "published-release",
            ),
            ExpectedCall("GET", tag_ref_url, "owned-tag-ref"),
            ExpectedCall(
                "GET",
                f"{API_ROOT}/releases/{OWNED_RELEASE_ID}/assets?per_page=100&page=1",
                "published-assets",
            ),
            ExpectedCall("GET", LIST_RELEASES_URL, "published-release-list"),
        )
    )
    if len(calls) != 50:
        raise AssertionError(f"Happy-path ledger must contain 50 calls, got {len(calls)}")
    return tuple(calls)


HAPPY_LEDGER = _happy_ledger()


class MemoryReceipt(publisher_module.ReceiptStore):
    snapshots: list[dict[str, object]]

    def __init__(self, config: publisher_module.PublisherConfig) -> None:
        self.snapshots = []
        super().__init__(config)

    def save(self) -> None:
        self.snapshots.append(copy.deepcopy(self._document()))


class ScriptedTransport:
    def __init__(self, faults: Mapping[int, FaultKind] | None = None) -> None:
        self.expected = HAPPY_LEDGER
        self.faults: dict[int, FaultKind] = dict(faults) if faults is not None else {}
        self.calls: list[ObservedCall] = []
        self.uploaded: list[tuple[publisher_module.FileSeal, int]] = []
        self.asset_listing_segments: list[str] = []
        self.published = False
        self._position = 0

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: bytes | None = None,
        file_body: publisher_module.FileSeal | None = None,
    ) -> publisher_module.TransportResult:
        if self._position >= len(self.expected):
            raise AssertionError(f"Unexpected extra transport call: {method} {url}")
        expected = self.expected[self._position]
        ordinal = self._position + 1
        self._position += 1

        if method != expected.method or url != expected.url:
            raise AssertionError(
                f"Call {ordinal} differed: expected {expected.method} {expected.url}, observed {method} {url}"
            )
        self._assert_request_body(expected, headers, json_body, file_body)
        self.calls.append(
            ObservedCall(
                ordinal=ordinal,
                method=method,
                url=url,
                json_body=json_body,
                asset_name=file_body.name if file_body is not None else None,
            )
        )

        fault = self.faults.get(ordinal)
        if fault is not None:
            return self._fault_result(ordinal, fault, expected, file_body)
        return self._normal_result(ordinal, expected, file_body)

    def _assert_request_body(
        self,
        expected: ExpectedCall,
        headers: Mapping[str, str],
        json_body: bytes | None,
        file_body: publisher_module.FileSeal | None,
    ) -> None:
        expected_headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer unit-test-token",
            "User-Agent": "GM2Godot-create-only-release-publisher/1",
            "X-GitHub-Api-Version": publisher_module.API_VERSION,
            "Connection": "close",
        }
        if expected.json_value is not None:
            expected_body = _canonical_json(expected.json_value)
            if json_body != expected_body or file_body is not None:
                raise AssertionError(f"Unexpected JSON request body for {expected.role}")
            expected_headers["Content-Type"] = "application/json"
            expected_headers["Content-Length"] = str(len(expected_body))
        elif expected.asset_name is not None:
            if json_body is not None or file_body is None:
                raise AssertionError(f"Missing file request body for {expected.role}")
            if file_body.name != expected.asset_name:
                raise AssertionError(f"Expected upload {expected.asset_name}, observed {file_body.name}")
            if file_body.content_type != ASSET_CONTENT_TYPES[file_body.name]:
                raise AssertionError(f"Wrong content type for {file_body.name}")
            actual_bytes = file_body.path.read_bytes()
            if len(actual_bytes) != file_body.size:
                raise AssertionError(f"Wrong sealed size for {file_body.name}")
            if hashlib.sha256(actual_bytes).hexdigest() != file_body.sha256:
                raise AssertionError(f"Wrong sealed digest for {file_body.name}")
            expected_headers["Content-Type"] = file_body.content_type
            expected_headers["Content-Length"] = str(file_body.size)
        elif json_body is not None or file_body is not None:
            raise AssertionError(f"Unexpected request body for {expected.role}")
        if dict(headers) != expected_headers:
            raise AssertionError(
                f"Headers differed for {expected.role}: expected={expected_headers!r}, observed={dict(headers)!r}"
            )

    def _normal_result(
        self,
        ordinal: int,
        expected: ExpectedCall,
        file_body: publisher_module.FileSeal | None,
    ) -> publisher_module.TransportResult:
        role = expected.role
        if role == "main-ref":
            return self._json_result(ordinal, 200, self._ref_object("heads/main"))
        if role in {"preflight-tag-absent", "published-release-absent"}:
            return self._empty_result(ordinal, 404)
        if role == "preflight-release-list":
            return self._json_result(ordinal, 200, [])
        if role in {"create-tag", "owned-tag-ref"}:
            status = 201 if role == "create-tag" else 200
            return self._json_result(ordinal, status, self._ref_object(f"tags/{TAG}"))
        if role in {"create-draft", "draft-release"}:
            status = 201 if role == "create-draft" else 200
            return self._json_result(ordinal, status, self._release_object(draft=True))
        if role == "draft-assets":
            self.asset_listing_segments.append(DRAFT_TAG_SEGMENT)
            return self._json_result(
                ordinal,
                200,
                self._asset_objects(DRAFT_TAG_SEGMENT),
            )
        if role == "draft-release-list":
            return self._json_result(
                ordinal,
                200,
                [self._release_object(draft=True)],
            )
        if role == "upload":
            if file_body is None:
                raise AssertionError("Upload call did not provide a sealed file")
            asset_id = 8001 + len(self.uploaded)
            self.uploaded.append((file_body, asset_id))
            return self._json_result(
                ordinal,
                201,
                self.asset_object(file_body, asset_id, DRAFT_TAG_SEGMENT),
                streamed_size=file_body.size,
                streamed_sha256=file_body.sha256,
            )
        if role == "publish":
            self.published = True
            return self._json_result(
                ordinal,
                200,
                self._release_object(draft=False),
            )
        if role == "published-release":
            return self._json_result(
                ordinal,
                200,
                self._release_object(draft=False),
            )
        if role == "published-assets":
            self.asset_listing_segments.append(TAG)
            return self._json_result(ordinal, 200, self._asset_objects(TAG))
        if role == "published-release-list":
            return self._json_result(
                ordinal,
                200,
                [self._release_object(draft=False)],
            )
        raise AssertionError(f"Unknown scripted transport role: {role}")

    def _fault_result(
        self,
        ordinal: int,
        fault: FaultKind,
        expected: ExpectedCall,
        file_body: publisher_module.FileSeal | None,
    ) -> publisher_module.TransportResult:
        if fault == "tag-present":
            return self._json_result(ordinal, 200, self._ref_object(f"tags/{TAG}"))
        if fault == "foreign-preflight-release":
            return self._json_result(
                ordinal,
                200,
                [{"id": FOREIGN_RELEASE_ID, "tag_name": TAG}],
            )
        if fault == "tag-transport-error":
            raise publisher_module.TransportError("simulated connection loss")
        if fault == "tag-conflict":
            return self._json_result(
                ordinal,
                409,
                {"message": "Conflict: reference already exists"},
            )
        if fault == "tag-validation-error":
            return self._json_result(
                ordinal,
                422,
                {"message": "Validation Failed: reference already exists"},
            )
        if fault == "tag-drift":
            drifted = self._ref_object(f"tags/{TAG}")
            target = drifted["object"]
            assert isinstance(target, dict)
            target_object = cast(dict[str, object], target)
            target_object["sha"] = "b" * 40
            target_object["url"] = f"{API_ROOT}/git/commits/{'b' * 40}"
            return self._json_result(ordinal, 200, drifted)
        if fault == "mutation-auth-error":
            return self._json_result(
                ordinal,
                403,
                {"message": "Resource not accessible by integration"},
            )
        if fault == "malformed-json":
            status = 200 if expected.role == "publish" else 201
            if expected.role == "upload":
                self._record_external_upload(file_body)
                return self._raw_result(
                    ordinal,
                    status,
                    b'{"id":',
                    streamed_size=file_body.size if file_body is not None else None,
                    streamed_sha256=(file_body.sha256 if file_body is not None else None),
                )
            if expected.role == "publish":
                self.published = True
            return self._raw_result(ordinal, status, b'{"id":')
        if fault == "unexpected-success":
            if expected.role == "upload":
                asset_id = self._record_external_upload(file_body)
                assert file_body is not None
                return self._json_result(
                    ordinal,
                    200,
                    self.asset_object(file_body, asset_id, DRAFT_TAG_SEGMENT),
                    streamed_size=file_body.size,
                    streamed_sha256=file_body.sha256,
                )
            if expected.role == "publish":
                self.published = True
                return self._json_result(
                    ordinal,
                    201,
                    self._release_object(draft=False),
                )
            return self._json_result(
                ordinal,
                200,
                self._ref_object(f"tags/{TAG}"),
            )
        if fault == "release-collision":
            return self._json_result(
                ordinal,
                422,
                {"message": "Validation Failed: release already exists"},
            )
        if fault == "release-transport-error":
            raise publisher_module.TransportError("simulated release response loss")
        if fault == "release-wrong-success":
            return self._json_result(
                ordinal,
                200,
                self._release_object(draft=True),
            )
        if fault == "invalid-draft-receipt":
            invalid = self._release_object(draft=True)
            invalid["html_url"] = f"https://github.com/{REPOSITORY}/releases/tag/v9.9.9"
            return self._json_result(ordinal, 201, invalid)
        if fault == "owned-id-drift":
            return self._json_result(ordinal, 200, {"id": FOREIGN_RELEASE_ID})
        if fault == "foreign-published-release":
            return self._json_result(ordinal, 200, {"id": FOREIGN_RELEASE_ID})
        if fault == "duplicate-exact-release":
            return self._json_result(
                ordinal,
                200,
                [
                    self._release_object(draft=not self.published),
                    {"id": FOREIGN_RELEASE_ID, "tag_name": TAG},
                ],
            )
        if fault == "upload-transport-error":
            self._record_external_upload(file_body)
            raise publisher_module.TransportError("simulated upload response loss")
        if fault == "upload-server-error":
            return self._json_result(
                ordinal,
                500,
                {"message": "Internal Server Error"},
            )
        if fault == "upload-collision":
            return self._json_result(
                ordinal,
                422,
                {"message": "Validation Failed: already_exists"},
            )
        if fault == "invalid-upload-receipt":
            asset_id = self._record_external_upload(file_body)
            assert file_body is not None
            invalid = self.asset_object(
                file_body,
                asset_id,
                DRAFT_TAG_SEGMENT,
            )
            invalid["digest"] = f"sha256:{'0' * 64}"
            return self._json_result(
                ordinal,
                201,
                invalid,
                streamed_size=file_body.size,
                streamed_sha256=file_body.sha256,
            )
        if fault == "upload-stream-size-mismatch":
            asset_id = self._record_external_upload(file_body)
            assert file_body is not None
            return self._json_result(
                ordinal,
                201,
                self.asset_object(file_body, asset_id, DRAFT_TAG_SEGMENT),
                streamed_size=file_body.size - 1,
                streamed_sha256=file_body.sha256,
            )
        if fault == "upload-stream-digest-mismatch":
            asset_id = self._record_external_upload(file_body)
            assert file_body is not None
            return self._json_result(
                ordinal,
                201,
                self.asset_object(file_body, asset_id, DRAFT_TAG_SEGMENT),
                streamed_size=file_body.size,
                streamed_sha256="0" * 64,
            )
        if fault == "upload-reused-id":
            if not self.uploaded:
                raise AssertionError("Reused asset ID fault requires a prior upload")
            assert file_body is not None
            asset_id = self.uploaded[0][1]
            self.uploaded.append((file_body, asset_id))
            return self._json_result(
                ordinal,
                201,
                self.asset_object(file_body, asset_id, DRAFT_TAG_SEGMENT),
                streamed_size=file_body.size,
                streamed_sha256=file_body.sha256,
            )
        if fault == "publish-transport-error":
            self.published = True
            raise publisher_module.TransportError("simulated publish response loss")
        if fault == "publish-server-error":
            self.published = True
            return self._json_result(
                ordinal,
                500,
                {"message": "Internal Server Error"},
            )
        if fault == "publish-id-drift":
            if expected.role == "publish":
                self.published = True
            return self._json_result(
                ordinal,
                200,
                self._release_object(draft=False, release_id=FOREIGN_RELEASE_ID),
            )
        if fault == "asset-digest-drift":
            assets = self._asset_objects(TAG)
            if not assets:
                raise AssertionError("Asset digest drift requires uploaded assets")
            assets[0]["digest"] = f"sha256:{'0' * 64}"
            return self._json_result(ordinal, 200, assets)
        if fault == "unexpected-draft-asset":
            return self._json_result(
                ordinal,
                200,
                [{"id": 9999, "name": "foreign.zip"}],
            )
        raise AssertionError(f"Unknown fault kind: {fault}")

    def _record_external_upload(
        self,
        file_body: publisher_module.FileSeal | None,
    ) -> int:
        if file_body is None:
            raise AssertionError("Upload fault did not provide a sealed file")
        asset_id = 8001 + len(self.uploaded)
        self.uploaded.append((file_body, asset_id))
        return asset_id

    def _ref_object(self, ref: str) -> dict[str, object]:
        return {
            "ref": f"refs/{ref}",
            "node_id": f"REF_{ref}",
            "url": f"{API_ROOT}/git/refs/{ref}",
            "object": {
                "type": "commit",
                "sha": TARGET_SHA,
                "url": f"{API_ROOT}/git/commits/{TARGET_SHA}",
            },
        }

    def _release_object(
        self,
        *,
        draft: bool,
        release_id: int = OWNED_RELEASE_ID,
    ) -> dict[str, object]:
        segment = DRAFT_TAG_SEGMENT if draft else TAG
        return {
            "id": release_id,
            "node_id": f"RELEASE_{release_id}",
            "tag_name": TAG,
            "target_commitish": TARGET_SHA,
            "name": RELEASE_NAME,
            "draft": draft,
            "prerelease": False,
            "url": f"{API_ROOT}/releases/{release_id}",
            "assets_url": f"{API_ROOT}/releases/{release_id}/assets",
            "upload_url": (f"{UPLOAD_ROOT}/releases/{release_id}/assets{{?name,label}}"),
            "html_url": f"https://github.com/{REPOSITORY}/releases/tag/{segment}",
            "created_at": "2026-07-19T00:00:00Z",
            "published_at": None if draft else "2026-07-19T00:05:00Z",
            "immutable": False,
            "assets": self._asset_objects(segment),
        }

    def _asset_objects(self, browser_segment: str) -> list[dict[str, object]]:
        return [self.asset_object(seal, asset_id, browser_segment) for seal, asset_id in self.uploaded]

    @staticmethod
    def asset_object(
        seal: publisher_module.FileSeal,
        asset_id: int,
        browser_segment: str,
    ) -> dict[str, object]:
        return {
            "id": asset_id,
            "node_id": f"ASSET_{asset_id}",
            "name": seal.name,
            "label": "",
            "state": "uploaded",
            "content_type": seal.content_type,
            "size": seal.size,
            "digest": f"sha256:{seal.sha256}",
            "url": f"{API_ROOT}/releases/assets/{asset_id}",
            "browser_download_url": (
                f"https://github.com/{REPOSITORY}/releases/download/{browser_segment}/{seal.name}"
            ),
            "created_at": "2026-07-19T00:01:00Z",
            "updated_at": "2026-07-19T00:01:01Z",
        }

    @staticmethod
    def _json_result(
        ordinal: int,
        status: int,
        value: object,
        *,
        streamed_size: int | None = None,
        streamed_sha256: str | None = None,
    ) -> publisher_module.TransportResult:
        return publisher_module.TransportResult(
            response=publisher_module.ApiResponse(
                status=status,
                headers={"x-github-request-id": f"request-{ordinal:03d}"},
                body=_canonical_json(value),
            ),
            streamed_size=streamed_size,
            streamed_sha256=streamed_sha256,
        )

    @staticmethod
    def _empty_result(
        ordinal: int,
        status: int,
    ) -> publisher_module.TransportResult:
        return publisher_module.TransportResult(
            response=publisher_module.ApiResponse(
                status=status,
                headers={"x-github-request-id": f"request-{ordinal:03d}"},
                body=b"",
            )
        )

    @staticmethod
    def _raw_result(
        ordinal: int,
        status: int,
        body: bytes,
        *,
        streamed_size: int | None = None,
        streamed_sha256: str | None = None,
    ) -> publisher_module.TransportResult:
        return publisher_module.TransportResult(
            response=publisher_module.ApiResponse(
                status=status,
                headers={"x-github-request-id": f"request-{ordinal:03d}"},
                body=body,
            ),
            streamed_size=streamed_size,
            streamed_sha256=streamed_sha256,
        )


class VisibilityScriptedTransport(ScriptedTransport):
    """Repeat one complete ownership gate with scripted exact-tag visibility."""

    def __init__(
        self,
        gate_index: int,
        list_states: Sequence[str],
        faults: Mapping[int, FaultKind] | None = None,
    ) -> None:
        if not list_states:
            raise ValueError("Visibility transport requires at least one list state")
        super().__init__(faults)
        list_positions = [index for index, call in enumerate(HAPPY_LEDGER) if call.role == "draft-release-list"]
        if not 0 <= gate_index < len(list_positions):
            raise ValueError(f"Invalid ownership gate index: {gate_index}")
        list_position = list_positions[gate_index]
        gate_start = list_position - 4
        gate = HAPPY_LEDGER[gate_start : list_position + 1]
        repeated: list[ExpectedCall] = []
        for state in list_states:
            repeated.extend(gate[:-1])
            repeated.append(
                ExpectedCall(
                    gate[-1].method,
                    gate[-1].url,
                    f"visibility-list-{state}",
                )
            )
        self.expected = (
            *HAPPY_LEDGER[:gate_start],
            *repeated,
            *HAPPY_LEDGER[list_position + 1 :],
        )

    def _normal_result(
        self,
        ordinal: int,
        expected: ExpectedCall,
        file_body: publisher_module.FileSeal | None,
    ) -> publisher_module.TransportResult:
        state_prefix = "visibility-list-"
        if not expected.role.startswith(state_prefix):
            return super()._normal_result(ordinal, expected, file_body)
        state = expected.role.removeprefix(state_prefix)
        historical = self._historical_release_object()
        if state == "missing-owned":
            value: object = [historical]
        elif state == "owned":
            value = [historical, self._release_object(draft=True)]
        elif state == "foreign":
            value = [historical, {"id": FOREIGN_RELEASE_ID, "tag_name": TAG}]
        elif state == "duplicate":
            value = [
                historical,
                self._release_object(draft=True),
                {"id": FOREIGN_RELEASE_ID, "tag_name": TAG},
            ]
        elif state == "duplicate-owned":
            value = [
                historical,
                self._release_object(draft=True),
                self._release_object(draft=True),
            ]
        elif state == "malformed":
            value = [historical, {"id": FOREIGN_RELEASE_ID}]
        elif state == "owned-invalid":
            invalid = self._release_object(draft=True)
            invalid["name"] = "Foreign title"
            value = [historical, invalid]
        elif state == "api-error":
            return self._json_result(
                ordinal,
                500,
                {"message": "simulated release-list failure"},
            )
        else:
            raise AssertionError(f"Unknown visibility list state: {state}")
        return self._json_result(ordinal, 200, value)

    def _historical_release_object(self) -> dict[str, object]:
        historical = self._release_object(
            draft=False,
            release_id=HISTORICAL_RELEASE_ID,
        )
        historical.update(
            {
                "tag_name": HISTORICAL_TAG,
                "target_commitish": "b" * 40,
                "name": f"GM2Godot {HISTORICAL_TAG}",
                "html_url": (f"https://github.com/{REPOSITORY}/releases/tag/{HISTORICAL_TAG}"),
                "assets": [],
            }
        )
        return historical


def _write_release_assets(root: Path) -> dict[str, bytes]:
    payloads = {
        "GM2Godot-windows.zip": b"PK\x03\x04GM2Godot Windows unit artifact\n",
        "GM2Godot-macos.zip": b"PK\x03\x04GM2Godot macOS unit artifact\n",
        "GM2Godot-macos.dmg": b"kolyGM2Godot macOS disk image unit artifact\n",
        "GM2Godot-linux.zip": b"PK\x03\x04GM2Godot Linux unit artifact\n",
    }
    locations = {
        "GM2Godot-windows.zip": root / "GM2Godot-windows/GM2Godot-windows.zip",
        "GM2Godot-macos.zip": root / "GM2Godot-macos/GM2Godot-macos.zip",
        "GM2Godot-macos.dmg": root / "GM2Godot-macos/GM2Godot-macos.dmg",
        "GM2Godot-linux.zip": root / "GM2Godot-linux/GM2Godot-linux.zip",
    }
    for name, path in locations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payloads[name])
    manifest = "".join(f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}\n" for name in PAYLOAD_ORDER).encode(
        "ascii"
    )
    (root / "SHA256SUMS").write_bytes(manifest)
    return {**payloads, "SHA256SUMS": manifest}


class TestReleasePublisher(unittest.TestCase):
    def _execute(
        self,
        faults: Mapping[int, FaultKind] | None = None,
        *,
        transport: ScriptedTransport | None = None,
        ownership_retry_delay_seconds: float = 0,
    ) -> tuple[
        publisher_module.ReleasePublisher,
        ScriptedTransport,
        MemoryReceipt,
        publisher_module.PublishError | None,
        dict[str, bytes],
    ]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            asset_root = root / "artifacts"
            payloads = _write_release_assets(asset_root)
            config = publisher_module.PublisherConfig(
                repository=REPOSITORY,
                token="unit-test-token",
                tag=TAG,
                release_name=RELEASE_NAME,
                target_sha=TARGET_SHA,
                run_id="12345",
                run_attempt="2",
                run_url=(f"https://github.com/{REPOSITORY}/actions/runs/12345/attempts/2"),
                api_origin=API_ORIGIN,
                upload_origin=UPLOAD_ORIGIN,
                receipt_path=root / "release-receipt/release-publisher.json",
                asset_root=asset_root,
                preflight_delay_seconds=0,
                ownership_retry_delay_seconds=ownership_retry_delay_seconds,
            )
            if transport is not None and faults is not None:
                raise ValueError("Provide faults or a scripted transport, not both")
            selected_transport = transport if transport is not None else ScriptedTransport(faults)
            api = publisher_module.GitHubApi(
                selected_transport,
                repository=config.repository,
                token=config.token,
                api_origin=config.api_origin,
                upload_origin=config.upload_origin,
            )
            receipt = MemoryReceipt(config)
            publisher = publisher_module.ReleasePublisher(config, api, receipt)
            error: publisher_module.PublishError | None = None
            try:
                publisher.run()
            except publisher_module.PublishError as caught:
                error = caught
            return publisher, selected_transport, receipt, error, payloads

    def test_happy_path_uses_exact_50_call_ownership_ledger(self) -> None:
        publisher, transport, receipt, error, payloads = self._execute()

        self.assertIsNone(error)
        self.assertEqual(len(transport.calls), 50)
        self.assertEqual(
            [(call.method, call.url) for call in transport.calls],
            [(call.method, call.url) for call in HAPPY_LEDGER],
        )
        mutation_ordinals = [call.ordinal for call in transport.calls if call.method != "GET"]
        self.assertEqual(mutation_ordinals, [8, 9, 15, 21, 27, 33, 39, 45])
        self.assertEqual(
            [call.asset_name for call in transport.calls if call.asset_name is not None],
            list(ASSET_ORDER),
        )
        self.assertTrue(transport.published)
        self.assertEqual(
            transport.asset_listing_segments,
            [DRAFT_TAG_SEGMENT] * 6 + [TAG],
        )

        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)
        self.assertEqual(
            [receipt.asset_id for receipt in publisher.uploaded],
            list(range(8001, 8006)),
        )
        self.assertTrue(
            all(
                f"/releases/download/{DRAFT_TAG_SEGMENT}/" in receipt.browser_download_url
                for receipt in publisher.uploaded
            )
        )
        self.assertEqual(receipt.stage, "verified")
        self.assertIsNone(receipt.failure)
        self.assertEqual(len(receipt.expected_assets), 5)
        self.assertEqual(len(receipt.asset_receipts), 5)
        for asset_receipt in receipt.asset_receipts:
            asset_name = str(asset_receipt["name"])
            self.assertIn(
                f"/releases/download/{DRAFT_TAG_SEGMENT}/{asset_name}",
                str(asset_receipt["upload_browser_download_url"]),
            )
            self.assertEqual(
                asset_receipt["published_browser_download_url"],
                f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{asset_name}",
            )
        self.assertEqual(
            {item["name"]: item["size"] for item in receipt.expected_assets},
            {name: len(payload) for name, payload in payloads.items()},
        )
        self.assertEqual(
            [intent["phase"] for intent in receipt.mutation_intents],
            [
                "create-tag-ref",
                "create-draft-release",
                *(f"upload-{name}" for name in ASSET_ORDER),
                "publish-owned-release",
            ],
        )
        self.assertEqual(
            [intent["state"] for intent in receipt.mutation_intents],
            ["accepted"] * 8,
        )
        self.assertEqual(
            [observation["phase"] for observation in receipt.observations],
            [
                "verify-main-target",
                "late-preflight-1",
                "late-preflight-2",
                "late-preflight-3",
                *(f"ownership-gate-{index}" for index in range(6)),
                "final-verification",
            ],
        )
        ownership_observations = [
            observation
            for observation in receipt.observations
            if str(observation["phase"]).startswith("ownership-gate-")
        ]
        self.assertEqual(
            [observation["decision"] for observation in ownership_observations],
            ["accept-owned"] * 6,
        )
        self.assertEqual(
            [observation["snapshot_attempt"] for observation in ownership_observations],
            [1] * 6,
        )
        self.assertIsNotNone(receipt.release_receipt)
        assert receipt.release_receipt is not None
        self.assertEqual(receipt.release_receipt["id"], OWNED_RELEASE_ID)
        self.assertEqual(
            receipt.release_receipt["browser_tag_segment"],
            DRAFT_TAG_SEGMENT,
        )
        self.assertEqual(
            receipt.release_receipt["create_html_url"],
            f"https://github.com/{REPOSITORY}/releases/tag/{DRAFT_TAG_SEGMENT}",
        )
        self.assertEqual(
            receipt.release_receipt["published_html_url"],
            f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
        )

    def test_missing_owned_match_repeats_the_whole_gate_until_visible(self) -> None:
        scripted = VisibilityScriptedTransport(
            0,
            ("missing-owned", "owned"),
        )
        with patch.object(publisher_module.time, "sleep") as sleeper:
            publisher, transport, receipt, error, _ = self._execute(
                transport=scripted,
                ownership_retry_delay_seconds=1,
            )

        self.assertIsNone(error)
        self.assertEqual(len(transport.calls), 55)
        self.assertEqual(
            [call.ordinal for call in transport.calls if call.method != "GET"],
            [8, 9, 20, 26, 32, 38, 44, 50],
        )
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [1.0])
        gate_observations = [
            observation
            for observation in receipt.observations
            if str(observation["phase"]).startswith("ownership-gate-0")
        ]
        self.assertEqual(
            [observation["decision"] for observation in gate_observations],
            ["retry-empty", "accept-owned"],
        )
        self.assertEqual(
            [observation["snapshot_attempt"] for observation in gate_observations],
            [1, 2],
        )
        self.assertEqual(
            [observation["listed_release_count"] for observation in gate_observations],
            [1, 2],
        )
        retry_snapshots = [
            snapshot
            for snapshot in receipt.snapshots
            if snapshot["observations"]
            and cast(list[dict[str, object]], snapshot["observations"])[-1].get("decision") == "retry-empty"
        ]
        self.assertEqual(len(retry_snapshots), 1)
        for snapshot in retry_snapshots:
            self.assertEqual(len(cast(list[object], snapshot["mutation_intents"])), 2)
            self.assertEqual(snapshot["asset_receipts"], [])
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_persistent_missing_owned_match_fails_before_upload(self) -> None:
        scripted = VisibilityScriptedTransport(
            0,
            ("missing-owned",) * publisher_module.OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
        )
        with patch.object(publisher_module.time, "sleep") as sleeper:
            publisher, transport, receipt, error, _ = self._execute(
                transport=scripted,
                ownership_retry_delay_seconds=1,
            )

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.phase, "ownership-gate-0")
        self.assertIn("visibility did not converge", str(error))
        self.assertEqual(len(transport.calls), 44)
        self.assertEqual(
            [call.ordinal for call in transport.calls if call.method != "GET"],
            [8, 9],
        )
        self.assertEqual(
            [call.args[0] for call in sleeper.call_args_list],
            [1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
        )
        self.assertEqual(transport.uploaded, [])
        self.assertFalse(transport.published)
        self.assertEqual(len(receipt.mutation_intents), 2)
        self.assertEqual(receipt.asset_receipts, [])
        self.assertEqual(receipt.observations[-1]["decision"], "fail-empty-exhausted")
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_visibility_retry_persists_release_list_api_failure(self) -> None:
        scripted = VisibilityScriptedTransport(
            0,
            ("missing-owned", "api-error"),
        )
        publisher, transport, receipt, error, _ = self._execute(transport=scripted)

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.phase, "ownership-gate-0")
        self.assertEqual(error.status, 500)
        self.assertEqual(error.request_id, "request-019")
        self.assertIn("simulated release-list failure", str(error))
        self.assertEqual(len(transport.calls), 19)
        self.assertEqual(
            [call.ordinal for call in transport.calls if call.method != "GET"],
            [8, 9],
        )
        self.assertEqual(transport.uploaded, [])
        self.assertFalse(transport.published)
        self.assertEqual(len(receipt.mutation_intents), 2)
        gate_observations = [
            observation
            for observation in receipt.observations
            if str(observation["phase"]).startswith("ownership-gate-0")
        ]
        self.assertEqual(
            [observation["decision"] for observation in gate_observations],
            ["retry-empty", "fail-list-read"],
        )
        self.assertEqual(gate_observations[0]["listed_release_count"], 1)
        self.assertIsNone(gate_observations[1]["listed_release_count"])
        self.assertIsNone(gate_observations[1]["exact_release_ids"])
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_visibility_retry_never_waits_out_nonempty_or_malformed_drift(self) -> None:
        for final_state, expected_message, final_decision, final_ids in (
            ("foreign", "observed ids=[9009]", "fail-identity-drift", [9009]),
            (
                "duplicate",
                "observed ids=[7001, 9009]",
                "fail-identity-drift",
                [7001, 9009],
            ),
            (
                "duplicate-owned",
                "observed ids=[7001, 7001]",
                "fail-identity-drift",
                [7001, 7001],
            ),
            (
                "malformed",
                "lacked a non-empty tag_name",
                "fail-list-read",
                None,
            ),
            (
                "owned-invalid",
                "Owned release verification failed",
                "fail-owned-schema",
                [7001],
            ),
        ):
            with self.subTest(final_state=final_state):
                scripted = VisibilityScriptedTransport(
                    0,
                    ("missing-owned", final_state),
                )
                publisher, transport, receipt, error, _ = self._execute(
                    transport=scripted,
                )

                self.assertIsNotNone(error)
                assert error is not None
                self.assertEqual(error.phase, "ownership-gate-0")
                self.assertIn(expected_message, str(error))
                self.assertEqual(len(transport.calls), 19)
                self.assertEqual(transport.uploaded, [])
                self.assertFalse(transport.published)
                self.assertEqual(len(receipt.mutation_intents), 2)
                self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)
                gate_observations = [
                    observation
                    for observation in receipt.observations
                    if str(observation["phase"]).startswith("ownership-gate-0")
                ]
                self.assertEqual(
                    [observation["decision"] for observation in gate_observations],
                    ["retry-empty", final_decision],
                )
                self.assertEqual(gate_observations[0]["exact_release_ids"], [])
                self.assertEqual(
                    gate_observations[1]["exact_release_ids"],
                    final_ids,
                )

    def test_visibility_retry_revalidates_non_list_gate_state(self) -> None:
        for ordinal, fault, expected_message in (
            (15, "tag-drift", "wrong commit SHA"),
            (16, "owned-id-drift", "Release identity drifted"),
            (17, "unexpected-draft-asset", "asset count drifted"),
            (18, "foreign-published-release", "published exact-tag release appeared"),
        ):
            with self.subTest(fault=fault):
                scripted = VisibilityScriptedTransport(
                    0,
                    ("missing-owned", "owned"),
                    {ordinal: cast(FaultKind, fault)},
                )
                _, transport, receipt, error, _ = self._execute(transport=scripted)

                self.assertIsNotNone(error)
                assert error is not None
                self.assertIn(expected_message, str(error))
                self.assertEqual(len(transport.calls), ordinal)
                self.assertEqual(transport.uploaded, [])
                self.assertEqual(len(receipt.mutation_intents), 2)

    def test_later_missing_owned_match_converges_without_replaying_uploaded_prefix(
        self,
    ) -> None:
        scripted = VisibilityScriptedTransport(3, ("missing-owned", "owned"))
        publisher, transport, receipt, error, _ = self._execute(transport=scripted)

        self.assertIsNone(error)
        self.assertEqual(len(transport.calls), 55)
        self.assertEqual(
            [call.ordinal for call in transport.calls if call.method != "GET"],
            [8, 9, 15, 21, 27, 38, 44, 50],
        )
        self.assertEqual([seal.name for seal, _ in transport.uploaded], list(ASSET_ORDER))
        self.assertEqual(len(receipt.mutation_intents), 8)
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_later_persistent_missing_owned_match_preserves_uploaded_prefix(self) -> None:
        scripted = VisibilityScriptedTransport(
            3,
            ("missing-owned",) * publisher_module.OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
        )
        publisher, transport, receipt, error, _ = self._execute(transport=scripted)

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.phase, "ownership-gate-3")
        self.assertIn("visibility did not converge", str(error))
        self.assertEqual(len(transport.calls), 62)
        self.assertEqual([seal.name for seal, _ in transport.uploaded], list(ASSET_ORDER[:3]))
        self.assertFalse(transport.published)
        self.assertEqual(
            [intent["phase"] for intent in receipt.mutation_intents],
            [
                "create-tag-ref",
                "create-draft-release",
                *(f"upload-{name}" for name in ASSET_ORDER[:3]),
            ],
        )
        self.assertEqual(
            [item["name"] for item in receipt.asset_receipts],
            list(ASSET_ORDER[:3]),
        )
        gate_observations = [
            observation
            for observation in receipt.observations
            if str(observation["phase"]).startswith("ownership-gate-3")
        ]
        self.assertEqual(
            [observation["decision"] for observation in gate_observations],
            ["retry-empty"] * 6 + ["fail-empty-exhausted"],
        )
        for observation in gate_observations:
            self.assertEqual(
                observation["uploaded_asset_names"],
                list(ASSET_ORDER[:3]),
            )
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_prepublish_persistent_missing_owned_match_never_patches(self) -> None:
        scripted = VisibilityScriptedTransport(
            5,
            ("missing-owned",) * publisher_module.OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
        )
        publisher, transport, receipt, error, _ = self._execute(transport=scripted)

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.phase, "ownership-gate-5")
        self.assertIn("visibility did not converge", str(error))
        self.assertEqual(len(transport.calls), 74)
        self.assertEqual(
            [call.ordinal for call in transport.calls if call.method != "GET"],
            [8, 9, 15, 21, 27, 33, 39],
        )
        self.assertEqual(
            [seal.name for seal, _ in transport.uploaded],
            list(ASSET_ORDER),
        )
        self.assertFalse(transport.published)
        self.assertEqual(
            [intent["phase"] for intent in receipt.mutation_intents],
            [
                "create-tag-ref",
                "create-draft-release",
                *(f"upload-{name}" for name in ASSET_ORDER),
            ],
        )
        self.assertEqual(
            [intent["state"] for intent in receipt.mutation_intents],
            ["accepted"] * 7,
        )
        self.assertEqual(
            [item["name"] for item in receipt.asset_receipts],
            list(ASSET_ORDER),
        )
        gate_observations = [
            observation
            for observation in receipt.observations
            if str(observation["phase"]).startswith("ownership-gate-5")
        ]
        self.assertEqual(
            [observation["decision"] for observation in gate_observations],
            ["retry-empty"] * 6 + ["fail-empty-exhausted"],
        )
        for observation in gate_observations:
            self.assertEqual(observation["next_mutation"], "publish-owned-release")
            self.assertEqual(observation["listed_release_count"], 1)
            self.assertEqual(
                observation["uploaded_asset_names"],
                list(ASSET_ORDER),
            )
        self.assertEqual(publisher.owned_release_id, OWNED_RELEASE_ID)

    def test_publisher_source_has_no_adoption_or_destructive_mutation_path(
        self,
    ) -> None:
        source = (Path(__file__).resolve().parents[1] / "scripts" / "release_publisher.py").read_text(encoding="utf-8")
        for forbidden in (
            '"DELETE"',
            '"PUT"',
            "softprops/action-gh-release",
            "gh release",
            "git push",
            "urllib.request",
            "requests.",
            "update_ref",
            "delete_ref",
            "delete_release",
            "delete_asset",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertEqual(source.count('"PATCH"'), 2)
        self.assertEqual(source.count('"POST"'), 6)

    def test_pagination_accepts_github_canonical_links_and_rejects_drift(
        self,
    ) -> None:
        expected_path = f"/repos/{REPOSITORY}/releases"
        canonical_next = (
            "<https://api.github.com/repositories/123456/releases?"
            'per_page=100&page=2>; rel="next", '
            "<https://api.github.com/repositories/123456/releases?"
            'per_page=100&page=4>; rel="last"'
        )
        self.assertTrue(
            publisher_module.pagination_has_next(
                {"link": canonical_next},
                api_origin=API_ORIGIN,
                expected_path=expected_path,
                canonical_suffix="/releases",
                current_page=1,
            )
        )
        self.assertFalse(
            publisher_module.pagination_has_next(
                {"link": ('<https://api.github.com/repositories/123456/releases?per_page=100&page=1>; rel="last"')},
                api_origin=API_ORIGIN,
                expected_path=expected_path,
                canonical_suffix="/releases",
                current_page=1,
            )
        )
        invalid_links = (
            '<https://example.invalid/releases?per_page=100&page=2>; rel="next"',
            ('<https://api.github.com/repositories/123456/releases?per_page=100&page=3>; rel="next"'),
            ('<https://api.github.com/repositories/123456/issues?per_page=100&page=2>; rel="next"'),
            "not-a-link",
        )
        for link in invalid_links:
            with self.subTest(link=link):
                with self.assertRaises(publisher_module.SchemaError):
                    publisher_module.pagination_has_next(
                        {"link": link},
                        api_origin=API_ORIGIN,
                        expected_path=expected_path,
                        canonical_suffix="/releases",
                        current_page=1,
                    )

    def test_asset_label_schema_accepts_github_empty_value_and_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / "GM2Godot-linux.zip"
            path.write_bytes(b"asset bytes\n")
            seal = publisher_module.seal_file(path, path.name, "application/zip")
            canonical = ScriptedTransport.asset_object(seal, 8001, TAG)

            for label in (None, ""):
                with self.subTest(accepted_label=label):
                    candidate = copy.deepcopy(canonical)
                    candidate["label"] = label
                    publisher_module.validate_asset(
                        candidate,
                        repository=REPOSITORY,
                        api_origin=API_ORIGIN,
                        browser_tag_segment=TAG,
                        seal=seal,
                    )
            rejected_labels: tuple[object, ...] = ("named", [], {})
            for label in rejected_labels:
                with self.subTest(rejected_label=label):
                    candidate = copy.deepcopy(canonical)
                    candidate["label"] = label
                    with self.assertRaises(publisher_module.SchemaError):
                        publisher_module.validate_asset(
                            candidate,
                            repository=REPOSITORY,
                            api_origin=API_ORIGIN,
                            browser_tag_segment=TAG,
                            seal=seal,
                        )

    def test_failures_are_terminal_without_retry_adoption_or_foreign_mutation(
        self,
    ) -> None:
        cases = (
            FailureCase(
                "existing tag",
                2,
                "tag-present",
                "late-preflight-1",
                200,
                False,
                None,
                0,
                0,
                0,
                f"Exact tag {TAG} appeared before run ownership was claimed",
            ),
            FailureCase(
                "existing exact release",
                3,
                "foreign-preflight-release",
                "late-preflight-1",
                None,
                False,
                None,
                0,
                0,
                0,
                f"Exact release state already exists for {TAG}",
            ),
            FailureCase(
                "exact release appears on second late preflight",
                5,
                "foreign-preflight-release",
                "late-preflight-2",
                None,
                False,
                None,
                0,
                0,
                0,
                f"Exact release state already exists for {TAG}",
            ),
            FailureCase(
                "tag appears on third late preflight",
                6,
                "tag-present",
                "late-preflight-3",
                200,
                False,
                None,
                0,
                0,
                0,
                f"Exact tag {TAG} appeared before run ownership was claimed",
            ),
            FailureCase(
                "ambiguous tag create",
                8,
                "tag-transport-error",
                "create-tag-ref",
                None,
                True,
                None,
                0,
                1,
                0,
                "GitHub API transport failed during create-tag-ref",
            ),
            FailureCase(
                "terminal tag create conflict",
                8,
                "tag-conflict",
                "create-tag-ref",
                409,
                False,
                None,
                0,
                1,
                0,
                "GitHub API returned HTTP 409 during create-tag-ref",
            ),
            FailureCase(
                "terminal tag create validation error",
                8,
                "tag-validation-error",
                "create-tag-ref",
                422,
                False,
                None,
                0,
                1,
                0,
                "GitHub API returned HTTP 422 during create-tag-ref",
            ),
            FailureCase(
                "terminal tag create authorization failure",
                8,
                "mutation-auth-error",
                "create-tag-ref",
                403,
                False,
                None,
                0,
                1,
                0,
                "GitHub API returned HTTP 403 during create-tag-ref",
            ),
            FailureCase(
                "malformed tag create receipt",
                8,
                "malformed-json",
                "create-tag-ref",
                201,
                True,
                None,
                0,
                1,
                0,
                "GitHub API returned malformed JSON during create-tag-ref",
            ),
            FailureCase(
                "terminal release collision",
                9,
                "release-collision",
                "create-draft-release",
                422,
                False,
                None,
                0,
                2,
                1,
                "GitHub API returned HTTP 422 during create-draft-release",
            ),
            FailureCase(
                "ambiguous release creation response loss",
                9,
                "release-transport-error",
                "create-draft-release",
                None,
                True,
                None,
                0,
                2,
                1,
                "GitHub API transport failed during create-draft-release",
            ),
            FailureCase(
                "unexpected release success status is ambiguous",
                9,
                "release-wrong-success",
                "create-draft-release",
                200,
                True,
                None,
                0,
                2,
                1,
                "GitHub API returned HTTP 200 during create-draft-release",
            ),
            FailureCase(
                "invalid draft receipt",
                9,
                "invalid-draft-receipt",
                "create-draft-release",
                201,
                True,
                None,
                0,
                2,
                1,
                "Create-release 201 receipt was invalid: Draft release HTML URL",
            ),
            FailureCase(
                "owned endpoint id drift",
                11,
                "owned-id-drift",
                "ownership-gate-0",
                200,
                False,
                OWNED_RELEASE_ID,
                0,
                2,
                2,
                "Owned release verification failed: Release identity drifted",
            ),
            FailureCase(
                "foreign published release",
                13,
                "foreign-published-release",
                "ownership-gate-0",
                200,
                False,
                OWNED_RELEASE_ID,
                0,
                2,
                2,
                "A published exact-tag release appeared while owned draft",
            ),
            FailureCase(
                "duplicate exact release",
                14,
                "duplicate-exact-release",
                "ownership-gate-0",
                None,
                False,
                OWNED_RELEASE_ID,
                0,
                2,
                2,
                "Exact-tag release identity drift before the next mutation",
            ),
            FailureCase(
                "mid-upload tag drift",
                28,
                "tag-drift",
                "ownership-gate-3",
                200,
                False,
                OWNED_RELEASE_ID,
                3,
                5,
                5,
                "Reference verification failed: Git reference resolved to the wrong commit SHA",
            ),
            FailureCase(
                "mid-upload foreign exact release",
                32,
                "duplicate-exact-release",
                "ownership-gate-3",
                None,
                False,
                OWNED_RELEASE_ID,
                3,
                5,
                5,
                "Exact-tag release identity drift before the next mutation",
            ),
            FailureCase(
                "foreign exact release before finalization",
                44,
                "duplicate-exact-release",
                "ownership-gate-5",
                None,
                False,
                OWNED_RELEASE_ID,
                5,
                7,
                7,
                "Exact-tag release identity drift before the next mutation",
            ),
            FailureCase(
                "mid-upload server error",
                27,
                "upload-server-error",
                "upload-GM2Godot-macos.dmg",
                500,
                True,
                OWNED_RELEASE_ID,
                2,
                5,
                4,
                "GitHub API returned HTTP 500 during upload-GM2Godot-macos.dmg",
            ),
            FailureCase(
                "ambiguous first asset response loss",
                15,
                "upload-transport-error",
                "upload-GM2Godot-windows.zip",
                None,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "GitHub API transport failed during upload-GM2Godot-windows.zip",
                external_uploaded_count=1,
            ),
            FailureCase(
                "terminal first asset authorization failure",
                15,
                "mutation-auth-error",
                "upload-GM2Godot-windows.zip",
                403,
                False,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "GitHub API returned HTTP 403 during upload-GM2Godot-windows.zip",
            ),
            FailureCase(
                "malformed first asset response",
                15,
                "malformed-json",
                "upload-GM2Godot-windows.zip",
                201,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "GitHub API returned malformed JSON during upload-GM2Godot-windows.zip",
                external_uploaded_count=1,
            ),
            FailureCase(
                "unexpected first asset success status",
                15,
                "unexpected-success",
                "upload-GM2Godot-windows.zip",
                200,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "GitHub API returned HTTP 200 during upload-GM2Godot-windows.zip",
                external_uploaded_count=1,
            ),
            FailureCase(
                "invalid first asset receipt",
                15,
                "invalid-upload-receipt",
                "upload-GM2Godot-windows.zip",
                201,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "Asset upload 201 receipt was invalid: Asset GM2Godot-windows.zip digest differed",
                external_uploaded_count=1,
            ),
            FailureCase(
                "first asset streamed size mismatch",
                15,
                "upload-stream-size-mismatch",
                "upload-GM2Godot-windows.zip",
                201,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "Upload stream receipt did not match sealed asset GM2Godot-windows.zip",
                external_uploaded_count=1,
            ),
            FailureCase(
                "first asset streamed digest mismatch",
                15,
                "upload-stream-digest-mismatch",
                "upload-GM2Godot-windows.zip",
                201,
                True,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "Upload stream receipt did not match sealed asset GM2Godot-windows.zip",
                external_uploaded_count=1,
            ),
            FailureCase(
                "same-name first asset collision",
                15,
                "upload-collision",
                "upload-GM2Godot-windows.zip",
                422,
                False,
                OWNED_RELEASE_ID,
                0,
                3,
                2,
                "GitHub API returned HTTP 422 during upload-GM2Godot-windows.zip",
            ),
            FailureCase(
                "second asset reused owned asset id",
                21,
                "upload-reused-id",
                "upload-GM2Godot-macos.zip",
                201,
                True,
                OWNED_RELEASE_ID,
                1,
                4,
                3,
                "Asset upload reused owned asset id=8001",
                external_uploaded_count=2,
            ),
            FailureCase(
                "ambiguous publish response loss",
                45,
                "publish-transport-error",
                "publish-owned-release",
                None,
                True,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "GitHub API transport failed during publish-owned-release",
                published=True,
            ),
            FailureCase(
                "terminal publish authorization failure",
                45,
                "mutation-auth-error",
                "publish-owned-release",
                403,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "GitHub API returned HTTP 403 during publish-owned-release",
            ),
            FailureCase(
                "malformed publish response",
                45,
                "malformed-json",
                "publish-owned-release",
                200,
                True,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "GitHub API returned malformed JSON during publish-owned-release",
                published=True,
            ),
            FailureCase(
                "unexpected publish success status",
                45,
                "unexpected-success",
                "publish-owned-release",
                201,
                True,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "GitHub API returned HTTP 201 during publish-owned-release",
                published=True,
            ),
            FailureCase(
                "ambiguous publish server error",
                45,
                "publish-server-error",
                "publish-owned-release",
                500,
                True,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "GitHub API returned HTTP 500 during publish-owned-release",
                published=True,
            ),
            FailureCase(
                "publish response id drift",
                45,
                "publish-id-drift",
                "publish-owned-release",
                200,
                True,
                OWNED_RELEASE_ID,
                5,
                8,
                7,
                "Publish 200 receipt was invalid: Release identity drifted",
                published=True,
            ),
            FailureCase(
                "final owned endpoint id drift",
                46,
                "publish-id-drift",
                "final-verification",
                200,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                8,
                "Owned release verification failed: Release identity drifted",
                published=True,
            ),
            FailureCase(
                "final tag lookup id drift",
                47,
                "publish-id-drift",
                "final-verification",
                200,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                8,
                "Owned release verification failed: Release identity drifted",
                published=True,
            ),
            FailureCase(
                "final tag ref drift",
                48,
                "tag-drift",
                "final-verification",
                200,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                8,
                "Reference verification failed: Git reference resolved to the wrong commit SHA",
                published=True,
            ),
            FailureCase(
                "final asset digest drift",
                49,
                "asset-digest-drift",
                "final-verification",
                None,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                8,
                "Owned asset verification failed: Asset GM2Godot-windows.zip digest differed",
                published=True,
            ),
            FailureCase(
                "final duplicate exact release",
                50,
                "duplicate-exact-release",
                "final-verification",
                None,
                False,
                OWNED_RELEASE_ID,
                5,
                8,
                8,
                "Final exact-tag listing was not the sole owned release",
                published=True,
            ),
        )

        for case in cases:
            with self.subTest(case=case.name):
                publisher, transport, receipt, error, _ = self._execute({case.ordinal: case.fault})

                self.assertIsNotNone(error)
                assert error is not None
                self.assertEqual(error.phase, case.phase)
                self.assertEqual(error.status, case.status)
                self.assertEqual(error.ambiguous, case.ambiguous)
                self.assertIn(case.error_substring, str(error))
                self.assertNotEqual(receipt.stage, "verified")
                self.assertTrue(receipt.snapshots)
                self.assertFalse(any(snapshot["stage"] == "verified" for snapshot in receipt.snapshots))
                self.assertEqual(len(transport.calls), case.ordinal)
                self.assertEqual(
                    [(call.method, call.url) for call in transport.calls],
                    [(expected.method, expected.url) for expected in HAPPY_LEDGER[: case.ordinal]],
                )
                self.assertEqual(publisher.owned_release_id, case.owned_release_id)
                self.assertEqual(len(publisher.uploaded), case.uploaded_count)
                expected_external_uploads = (
                    case.uploaded_count if case.external_uploaded_count is None else case.external_uploaded_count
                )
                self.assertEqual(len(transport.uploaded), expected_external_uploads)
                self.assertEqual(transport.published, case.published)
                self.assertEqual(
                    len(receipt.mutation_intents),
                    case.mutation_intent_count,
                )
                self.assertEqual(
                    sum(intent["state"] == "accepted" for intent in receipt.mutation_intents),
                    case.accepted_mutation_count,
                )
                if case.owned_release_id is None:
                    self.assertIsNone(receipt.release_receipt)
                else:
                    self.assertIsNotNone(receipt.release_receipt)
                    assert receipt.release_receipt is not None
                    self.assertEqual(
                        receipt.release_receipt["id"],
                        OWNED_RELEASE_ID,
                    )

                for call in transport.calls:
                    if call.method == "GET":
                        continue
                    self.assertNotEqual(call.method, "DELETE")
                    self.assertNotIn(str(FOREIGN_RELEASE_ID), call.url)
                    self.assertNotIn(
                        str(FOREIGN_RELEASE_ID).encode("ascii"),
                        call.json_body or b"",
                    )


if __name__ == "__main__":
    unittest.main()
