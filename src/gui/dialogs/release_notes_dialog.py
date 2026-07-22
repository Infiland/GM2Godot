from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import html
import re
from typing import cast

import markdown2  # type: ignore[reportMissingTypeStubs]
import requests

from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import THEME
from src.localization import get_localized, get_localized_list


RELEASES_API_URL = "https://api.github.com/repos/Infiland/GM2Godot/releases"
RELEASES_PER_PAGE = 10
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}
_NEXT_LINK_PATTERN = re.compile(r'<[^>]+>\s*;\s*rel="next"')


@dataclass(frozen=True)
class ReleaseNote:
    title: str
    tag: str
    body: str
    url: str


@dataclass(frozen=True)
class ReleaseNotesPage:
    notes: tuple[ReleaseNote, ...]
    has_more: bool


class ReleaseNotesFetchError(RuntimeError):
    pass


class ReleaseNotesClient:
    def fetch_page(self, page: int) -> ReleaseNotesPage:
        if page < 1:
            raise ValueError("Release page must be positive")

        response: requests.Response | None = None
        try:
            response = requests.get(
                RELEASES_API_URL,
                params={"per_page": RELEASES_PER_PAGE, "page": page},
                headers=GITHUB_API_HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            payload: object = response.json()
            link_header = response.headers.get("Link", "")
            return ReleaseNotesPage(
                notes=self._parse_notes(payload),
                has_more=_NEXT_LINK_PATTERN.search(link_header) is not None,
            )
        except ReleaseNotesFetchError:
            raise
        except (requests.RequestException, TypeError, ValueError) as error:
            raise ReleaseNotesFetchError(str(error)) from error
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _parse_notes(payload: object) -> tuple[ReleaseNote, ...]:
        if not isinstance(payload, list):
            raise ReleaseNotesFetchError("GitHub returned a non-list release payload")

        notes: list[ReleaseNote] = []
        for raw_release in cast(list[object], payload):
            if not isinstance(raw_release, dict):
                raise ReleaseNotesFetchError("GitHub returned a malformed release entry")
            release = cast(Mapping[object, object], raw_release)

            tag = release.get("tag_name")
            name = release.get("name")
            body = release.get("body")
            url = release.get("html_url")
            if not isinstance(tag, str) or not tag:
                raise ReleaseNotesFetchError("A GitHub release is missing its tag")
            if name is not None and not isinstance(name, str):
                raise ReleaseNotesFetchError(f"GitHub release {tag} has an invalid name")
            if body is not None and not isinstance(body, str):
                raise ReleaseNotesFetchError(f"GitHub release {tag} has invalid notes")
            if not isinstance(url, str) or not url:
                raise ReleaseNotesFetchError(f"GitHub release {tag} is missing its URL")

            notes.append(
                ReleaseNote(
                    title=name or tag,
                    tag=tag,
                    body=body or "",
                    url=url,
                )
            )
        return tuple(notes)


class ReleaseNotesDialog:
    def __init__(
        self,
        parent: QWidget,
        *,
        client: ReleaseNotesClient | None = None,
    ) -> None:
        self._parent = parent
        self._client = client or ReleaseNotesClient()
        self._dialog: QDialog | None = None
        self._browser: QTextBrowser | None = None
        self._show_more_button: QPushButton | None = None
        self._notes: list[ReleaseNote] = []
        self._next_page = 1

    def show(self) -> None:
        try:
            first_page = self._client.fetch_page(1)
        except ReleaseNotesFetchError as error:
            self._report_fetch_error(error, critical=True)
            return

        if not first_page.notes:
            errors = get_localized_list("ReleaseNotes_Error_NoInternet")
            QMessageBox.critical(self._parent, errors[0], errors[1])
            return

        self._display(first_page)

    def _display(self, first_page: ReleaseNotesPage) -> None:
        dialog = QDialog(self._parent)
        dialog.setWindowTitle(get_localized("ReleaseNotes_Title"))
        dialog.resize(750, 600)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            f"background-color: {THEME['bg_tertiary']}; "
            f"color: {THEME['fg_white']}; "
            f"border: none; border-radius: 6px; padding: 10px;"
        )
        layout.addWidget(browser, stretch=1)

        show_more_button = QPushButton(get_localized("ReleaseNotes_ShowMore"))
        show_more_button.setAutoDefault(False)
        show_more_button.clicked.connect(self._load_more)
        layout.addWidget(show_more_button)

        self._dialog = dialog
        self._browser = browser
        self._show_more_button = show_more_button
        self._notes = list(first_page.notes)
        self._next_page = 2
        self._render_notes()
        show_more_button.setVisible(first_page.has_more)

        dialog.exec()

    def _load_more(self, _checked: bool = False) -> None:
        button = self._show_more_button
        if button is None:
            return

        button.setEnabled(False)
        try:
            page = self._client.fetch_page(self._next_page)
        except ReleaseNotesFetchError as error:
            button.setEnabled(True)
            self._report_fetch_error(error, critical=False)
            return

        self._notes.extend(page.notes)
        self._next_page += 1
        self._render_notes()
        button.setVisible(page.has_more)
        button.setEnabled(True)

    def _render_notes(self) -> None:
        if self._browser is None:
            return

        sections: list[str] = []
        for note in self._notes:
            title = html.escape(note.title)
            tag = html.escape(note.tag)
            url = html.escape(note.url, quote=True)
            body = cast(
                str,
                markdown2.markdown(note.body, extras=["fenced-code-blocks"]),
            )
            sections.append(
                f'<section><h2><a href="{url}">{title}</a></h2>'
                f"<p><code>{tag}</code></p>{body}</section>"
            )
        self._browser.setHtml("<hr>".join(sections))

    def _report_fetch_error(
        self,
        error: ReleaseNotesFetchError,
        *,
        critical: bool,
    ) -> None:
        message = get_localized("ReleaseNotes_Error_Generic").format(error=error)
        print(message)
        errors = get_localized_list("ReleaseNotes_Error_NoInternet")
        if critical:
            QMessageBox.critical(self._parent, errors[0], errors[1])
        else:
            QMessageBox.warning(self._parent, errors[0], message)
