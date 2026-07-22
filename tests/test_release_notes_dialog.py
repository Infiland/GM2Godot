# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from src.gui.dialogs.release_notes_dialog import (
    RELEASES_API_URL,
    RELEASES_PER_PAGE,
    ReleaseNote,
    ReleaseNotesClient,
    ReleaseNotesDialog,
    ReleaseNotesFetchError,
    ReleaseNotesPage,
)


def _release_payload(index: int) -> dict[str, object]:
    return {
        "name": f"GM2Godot v0.7.{index}",
        "tag_name": f"v0.7.{index}",
        "body": f"Changes for release {index}.",
        "html_url": f"https://github.com/Infiland/GM2Godot/releases/tag/v0.7.{index}",
    }


def _release_note(index: int) -> ReleaseNote:
    payload = _release_payload(index)
    return ReleaseNote(
        title=str(payload["name"]),
        tag=str(payload["tag_name"]),
        body=str(payload["body"]),
        url=str(payload["html_url"]),
    )


class _StubReleaseNotesClient(ReleaseNotesClient):
    def __init__(
        self,
        outcomes: Mapping[int, ReleaseNotesPage | ReleaseNotesFetchError],
    ) -> None:
        self._outcomes = outcomes
        self.requested_pages: list[int] = []

    def fetch_page(self, page: int) -> ReleaseNotesPage:
        self.requested_pages.append(page)
        outcome = self._outcomes[page]
        if isinstance(outcome, ReleaseNotesFetchError):
            raise outcome
        return outcome


class ReleaseNotesClientTests(unittest.TestCase):
    def test_fetches_ten_releases_and_detects_the_next_page(self) -> None:
        response = MagicMock()
        response.json.return_value = [_release_payload(index) for index in range(48, 38, -1)]
        response.headers = {
            "Link": (
                '<https://api.github.com/repositories/123/releases?per_page=10&page=2>; '
                'rel="next", '
                '<https://api.github.com/repositories/123/releases?per_page=10&page=5>; '
                'rel="last"'
            )
        }

        with patch(
            "src.gui.dialogs.release_notes_dialog.requests.get",
            return_value=response,
        ) as request_get:
            page = ReleaseNotesClient().fetch_page(1)

        self.assertEqual(len(page.notes), RELEASES_PER_PAGE)
        self.assertEqual(page.notes[0].tag, "v0.7.48")
        self.assertEqual(page.notes[-1].tag, "v0.7.39")
        self.assertTrue(page.has_more)
        request_get.assert_called_once_with(
            RELEASES_API_URL,
            params={"per_page": RELEASES_PER_PAGE, "page": 1},
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()
        response.close.assert_called_once_with()

    def test_accepts_nullable_release_name_and_body(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {
                "name": None,
                "tag_name": "v0.1.0",
                "body": None,
                "html_url": "https://github.com/Infiland/GM2Godot/releases/tag/v0.1.0",
            }
        ]
        response.headers = {}

        with patch(
            "src.gui.dialogs.release_notes_dialog.requests.get",
            return_value=response,
        ):
            page = ReleaseNotesClient().fetch_page(3)

        self.assertEqual(
            page.notes,
            (
                ReleaseNote(
                    title="v0.1.0",
                    tag="v0.1.0",
                    body="",
                    url="https://github.com/Infiland/GM2Godot/releases/tag/v0.1.0",
                ),
            ),
        )
        self.assertFalse(page.has_more)
        response.close.assert_called_once_with()

    def test_rejects_malformed_payload_and_closes_response(self) -> None:
        response = MagicMock()
        response.json.return_value = {"tag_name": "v0.7.48"}
        response.headers = {}

        with (
            patch(
                "src.gui.dialogs.release_notes_dialog.requests.get",
                return_value=response,
            ),
            self.assertRaisesRegex(ReleaseNotesFetchError, "non-list"),
        ):
            ReleaseNotesClient().fetch_page(1)

        response.close.assert_called_once_with()

    def test_rejects_non_positive_pages_without_a_request(self) -> None:
        with (
            patch("src.gui.dialogs.release_notes_dialog.requests.get") as request_get,
            self.assertRaisesRegex(ValueError, "positive"),
        ):
            ReleaseNotesClient().fetch_page(0)

        request_get.assert_not_called()


class ReleaseNotesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing_app = QApplication.instance()
        cls.app = existing_app if isinstance(existing_app, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.parent = QWidget()

    def tearDown(self) -> None:
        self.parent.deleteLater()

    def test_initial_history_shows_ten_notes_and_loads_more_on_click(self) -> None:
        first_page = ReleaseNotesPage(
            notes=tuple(_release_note(index) for index in range(48, 38, -1)),
            has_more=True,
        )
        second_page = ReleaseNotesPage(
            notes=tuple(_release_note(index) for index in range(38, 28, -1)),
            has_more=False,
        )
        client = _StubReleaseNotesClient({1: first_page, 2: second_page})
        release_dialog = ReleaseNotesDialog(self.parent, client=client)

        with patch.object(QDialog, "exec", return_value=0):
            release_dialog.show()

        browser = release_dialog._browser
        button = release_dialog._show_more_button
        self.assertIsNotNone(browser)
        self.assertIsNotNone(button)
        assert browser is not None
        assert button is not None
        initial_text = browser.toPlainText()
        self.assertIn("GM2Godot v0.7.48", initial_text)
        self.assertIn("GM2Godot v0.7.39", initial_text)
        self.assertNotIn("GM2Godot v0.7.38", initial_text)
        self.assertEqual(button.text(), "Show more")
        self.assertFalse(button.isHidden())

        button.click()

        expanded_text = browser.toPlainText()
        self.assertIn("GM2Godot v0.7.38", expanded_text)
        self.assertIn("GM2Godot v0.7.29", expanded_text)
        self.assertTrue(button.isHidden())
        self.assertEqual(client.requested_pages, [1, 2])

    def test_load_more_failure_preserves_history_and_allows_retry(self) -> None:
        first_page = ReleaseNotesPage(notes=(_release_note(48),), has_more=True)
        client = _StubReleaseNotesClient(
            {
                1: first_page,
                2: ReleaseNotesFetchError("temporary outage"),
            }
        )
        release_dialog = ReleaseNotesDialog(self.parent, client=client)

        with patch.object(QDialog, "exec", return_value=0):
            release_dialog.show()

        browser = release_dialog._browser
        button = release_dialog._show_more_button
        self.assertIsNotNone(browser)
        self.assertIsNotNone(button)
        assert browser is not None
        assert button is not None
        initial_text = browser.toPlainText()

        with (
            patch("src.gui.dialogs.release_notes_dialog.QMessageBox.warning") as warning,
            patch("builtins.print"),
        ):
            button.click()

        self.assertEqual(browser.toPlainText(), initial_text)
        self.assertTrue(button.isEnabled())
        self.assertFalse(button.isHidden())
        self.assertEqual(client.requested_pages, [1, 2])
        warning.assert_called_once()

    def test_initial_failure_reports_error_without_opening_dialog(self) -> None:
        client = _StubReleaseNotesClient(
            {1: ReleaseNotesFetchError("connection refused")}
        )
        release_dialog = ReleaseNotesDialog(self.parent, client=client)

        with (
            patch("src.gui.dialogs.release_notes_dialog.QMessageBox.critical") as critical,
            patch.object(QDialog, "exec") as execute,
            patch("builtins.print"),
        ):
            release_dialog.show()

        critical.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(client.requested_pages, [1])


if __name__ == "__main__":
    unittest.main()
