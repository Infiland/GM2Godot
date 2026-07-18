from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import release_publisher as publisher_module


REPOSITORY = "Infiland/GM2Godot"
API_ORIGIN = "https://api.github.com"
UPLOAD_ORIGIN = "https://uploads.github.com"
RELEASE_ID = 7001
API_ROOT = f"{API_ORIGIN}/repos/{REPOSITORY}"


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _page_response(
    value: object,
    *,
    headers: Mapping[str, str] | None = None,
) -> publisher_module.TransportResult:
    return publisher_module.TransportResult(
        response=publisher_module.ApiResponse(
            status=200,
            headers=dict(headers) if headers is not None else {},
            body=_json_bytes(value),
        )
    )


class _PageTransport:
    def __init__(
        self,
        responses: list[publisher_module.TransportResult],
    ) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: bytes | None = None,
        file_body: publisher_module.FileSeal | None = None,
    ) -> publisher_module.TransportResult:
        del headers
        if method != "GET" or json_body is not None or file_body is not None:
            raise AssertionError("Pagination transport received a non-GET request.")
        self.calls.append((method, url))
        if not self._responses:
            raise AssertionError(f"Unexpected pagination request: {method} {url}")
        return self._responses.pop(0)

    def assert_exhausted(self) -> None:
        if self._responses:
            raise AssertionError(f"Pagination left {len(self._responses)} scripted responses unused.")


class _FakeHttpResponse:
    def __init__(
        self,
        value: object,
        headers: list[tuple[str, str]],
    ) -> None:
        self.status = 200
        self._body = _json_bytes(value)
        self._headers = headers

    def read(self, amount: int | None = None) -> bytes:
        if amount is not None and amount < len(self._body):
            raise AssertionError("Fake response read bound was unexpectedly small.")
        return self._body

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers)


class _FakeHttpsConnection:
    def __init__(
        self,
        *,
        response: _FakeHttpResponse | None = None,
        on_endheaders: Callable[[], None] | None = None,
        on_send: Callable[[bytes], None] | None = None,
    ) -> None:
        self._response = response
        self._on_endheaders = on_endheaders
        self._on_send = on_send
        self.requests: list[tuple[str, str, bool]] = []
        self.headers: list[tuple[str, str]] = []
        self.sent_chunks: list[bytes] = []
        self.getresponse_calls = 0
        self.closed = False

    def putrequest(
        self,
        method: str,
        target: str,
        *,
        skip_accept_encoding: bool = False,
    ) -> None:
        self.requests.append((method, target, skip_accept_encoding))

    def putheader(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def endheaders(self) -> None:
        if self._on_endheaders is not None:
            self._on_endheaders()

    def send(self, data: bytes) -> None:
        chunk = bytes(data)
        self.sent_chunks.append(chunk)
        if self._on_send is not None:
            self._on_send(chunk)

    def getresponse(self) -> _FakeHttpResponse:
        self.getresponse_calls += 1
        if self._response is None:
            raise AssertionError("A rejected upload tried to accept an HTTP response.")
        return self._response

    def close(self) -> None:
        self.closed = True


def _api(transport: publisher_module.Transport) -> publisher_module.GitHubApi:
    return publisher_module.GitHubApi(
        transport,
        repository=REPOSITORY,
        token="unit-test-token",
        api_origin=API_ORIGIN,
        upload_origin=UPLOAD_ORIGIN,
    )


def _next_link(path: str) -> str:
    return f'<{API_ORIGIN}{path}?page=2&per_page=100>; rel="next"'


class TestReleasePaginationTransport(unittest.TestCase):
    def test_list_releases_accepts_owner_and_numeric_next_links(self) -> None:
        page_two_release = {
            "id": 9009,
            "tag_name": "v9.9.9",
            "draft": False,
            "foreign": True,
        }
        paths = (
            f"/repos/{REPOSITORY}/releases",
            "/repositories/123456789/releases",
        )
        for next_path in paths:
            with self.subTest(next_path=next_path):
                transport = _PageTransport(
                    [
                        _page_response(
                            [{"id": RELEASE_ID, "tag_name": "v0.7.17"}],
                            headers={"link": _next_link(next_path)},
                        ),
                        _page_response([page_two_release]),
                    ]
                )

                releases = _api(transport).list_releases("release-pagination")

                self.assertEqual(releases[-1], page_two_release)
                self.assertEqual(
                    transport.calls,
                    [
                        (
                            "GET",
                            f"{API_ROOT}/releases?per_page=100&page=1",
                        ),
                        (
                            "GET",
                            f"{API_ROOT}/releases?per_page=100&page=2",
                        ),
                    ],
                )
                transport.assert_exhausted()

    def test_list_assets_accepts_owner_and_numeric_next_links(self) -> None:
        page_two_asset = {
            "id": 9909,
            "name": "foreign.zip",
            "state": "starter",
        }
        paths = (
            f"/repos/{REPOSITORY}/releases/{RELEASE_ID}/assets",
            f"/repositories/123456789/releases/{RELEASE_ID}/assets",
        )
        for next_path in paths:
            with self.subTest(next_path=next_path):
                transport = _PageTransport(
                    [
                        _page_response(
                            [{"id": 8001, "name": "owned.zip"}],
                            headers={"link": _next_link(next_path)},
                        ),
                        _page_response([page_two_asset]),
                    ]
                )

                assets = _api(transport).list_assets(
                    "asset-pagination",
                    RELEASE_ID,
                )

                self.assertEqual(assets[-1], page_two_asset)
                self.assertEqual(
                    transport.calls,
                    [
                        (
                            "GET",
                            f"{API_ROOT}/releases/{RELEASE_ID}/assets?per_page=100&page=1",
                        ),
                        (
                            "GET",
                            f"{API_ROOT}/releases/{RELEASE_ID}/assets?per_page=100&page=2",
                        ),
                    ],
                )
                transport.assert_exhausted()

    def test_exactly_one_hundred_releases_without_link_fetches_page_two(self) -> None:
        first_page = [{"id": index + 1} for index in range(100)]
        page_two_release = {"id": 9009, "tag_name": "v0.7.17", "foreign": True}
        transport = _PageTransport([_page_response(first_page), _page_response([page_two_release])])

        releases = _api(transport).list_releases("release-fallback-pagination")

        self.assertEqual(len(releases), 101)
        self.assertEqual(releases[-1], page_two_release)
        self.assertEqual(len(transport.calls), 2)
        transport.assert_exhausted()

    def test_exactly_one_hundred_assets_without_link_fetches_page_two(self) -> None:
        first_page = [{"id": index + 1} for index in range(100)]
        page_two_asset = {"id": 9909, "name": "foreign.zip", "state": "starter"}
        transport = _PageTransport([_page_response(first_page), _page_response([page_two_asset])])

        assets = _api(transport).list_assets(
            "asset-fallback-pagination",
            RELEASE_ID,
        )

        self.assertEqual(len(assets), 101)
        self.assertEqual(assets[-1], page_two_asset)
        self.assertEqual(len(transport.calls), 2)
        transport.assert_exhausted()

    def test_split_link_fields_preserve_next_page_through_https_transport(
        self,
    ) -> None:
        next_url = f"{API_ROOT}/releases?page=2&per_page=100"
        last_url = f"{API_ROOT}/releases?page=9&per_page=100"
        page_two_release = {"id": 9009, "tag_name": "v9.9.9", "foreign": True}
        first = _FakeHttpsConnection(
            response=_FakeHttpResponse(
                [{"id": RELEASE_ID, "tag_name": "v0.7.17"}],
                [
                    ("Link", f'<{next_url}>; rel="next"'),
                    ("Link", f'<{last_url}>; rel="last"'),
                ],
            )
        )
        second = _FakeHttpsConnection(response=_FakeHttpResponse([page_two_release], []))
        with mock.patch.object(
            publisher_module.http.client,
            "HTTPSConnection",
            side_effect=[first, second],
        ) as connection_factory:
            releases = _api(publisher_module.HttpsTransport()).list_releases("split-link-pagination")

        self.assertEqual(releases[-1], page_two_release)
        self.assertEqual(connection_factory.call_count, 2)
        self.assertEqual(
            first.requests,
            [
                (
                    "GET",
                    f"/repos/{REPOSITORY}/releases?per_page=100&page=1",
                    True,
                )
            ],
        )
        self.assertEqual(
            second.requests,
            [
                (
                    "GET",
                    f"/repos/{REPOSITORY}/releases?per_page=100&page=2",
                    True,
                )
            ],
        )
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)


class TestReleaseArtifactIdentityTransport(unittest.TestCase):
    def _assert_upload_rejected(
        self,
        connection: _FakeHttpsConnection,
        seal: publisher_module.FileSeal,
    ) -> publisher_module.PublishError:
        with mock.patch.object(
            publisher_module.http.client,
            "HTTPSConnection",
            return_value=connection,
        ):
            with self.assertRaises(publisher_module.PublishError) as caught:
                _api(publisher_module.HttpsTransport()).upload_asset(
                    RELEASE_ID,
                    seal,
                )

        error = caught.exception
        self.assertEqual(error.phase, f"upload-{seal.name}")
        self.assertTrue(error.ambiguous)
        self.assertIsNone(error.status)
        self.assertEqual(connection.getresponse_calls, 0)
        self.assertTrue(connection.closed)
        return error

    def test_inode_replacement_after_headers_is_rejected_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            asset = root / "artifact.zip"
            replacement = root / "replacement.zip"
            original = b"sealed release artifact"
            asset.write_bytes(original)
            seal = publisher_module.seal_file(
                asset,
                asset.name,
                "application/zip",
            )
            replacement.write_bytes(original)

            def replace_after_headers() -> None:
                os.replace(replacement, asset)

            connection = _FakeHttpsConnection(
                on_endheaders=replace_after_headers,
            )
            error = self._assert_upload_rejected(connection, seal)

            self.assertIn("changed after sealing", str(error))
            self.assertEqual(connection.sent_chunks, [])

    def test_symlink_replacement_after_headers_is_rejected_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            asset = root / "artifact.zip"
            symlink_target = root / "symlink-target.zip"
            original = b"sealed release artifact"
            asset.write_bytes(original)
            seal = publisher_module.seal_file(
                asset,
                asset.name,
                "application/zip",
            )
            symlink_target.write_bytes(original)

            def replace_after_headers() -> None:
                asset.unlink()
                try:
                    asset.symlink_to(symlink_target)
                except OSError as error:
                    self.skipTest(f"Symlink creation is unavailable: {error}")

            connection = _FakeHttpsConnection(
                on_endheaders=replace_after_headers,
            )
            error = self._assert_upload_rejected(connection, seal)

            self.assertRegex(
                str(error),
                r"(?:Cannot open regular release asset|changed after sealing)",
            )
            self.assertEqual(connection.sent_chunks, [])

    def test_mid_stream_mutation_is_rejected_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            asset = Path(temporary_directory) / "artifact.zip"
            original = b"A" * publisher_module.STREAM_CHUNK_BYTES + b"B" * 32
            asset.write_bytes(original)
            seal = publisher_module.seal_file(
                asset,
                asset.name,
                "application/zip",
            )
            mutated = False

            def mutate_after_first_chunk(_chunk: bytes) -> None:
                nonlocal mutated
                if mutated:
                    return
                mutated = True
                with asset.open("r+b") as handle:
                    handle.seek(publisher_module.STREAM_CHUNK_BYTES)
                    handle.write(b"C")
                    handle.flush()
                    os.fsync(handle.fileno())

            connection = _FakeHttpsConnection(on_send=mutate_after_first_chunk)
            error = self._assert_upload_rejected(connection, seal)

            self.assertTrue(mutated)
            self.assertIn("changed while it was uploaded", str(error))
            streamed = b"".join(connection.sent_chunks)
            self.assertEqual(len(streamed), len(original))
            self.assertNotEqual(streamed, original)


if __name__ == "__main__":
    unittest.main()
