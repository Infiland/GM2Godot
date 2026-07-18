from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeAlias, cast

from src.conversion.architecture_policy import build_architecture_policy_report
from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.conversion_plan import build_conversion_plan, conversion_step_map
from src.conversion.generated_paths import (
    generated_flat_resource_path,
    generated_nested_resource_path,
    generated_resource_stem,
    is_snake_case_path_segment,
    res_path_segments,
    snake_case_res_path,
)
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.type_defs import JsonDict

CONVERSION_MANIFEST_RELATIVE_PATH = os.path.join("gm2godot", "conversion_manifest.json")
CONVERSION_ATTEMPT_RELATIVE_PATH = os.path.join("gm2godot", "conversion_attempt.json")
_MANIFEST_FILENAME = os.path.basename(CONVERSION_MANIFEST_RELATIVE_PATH)
_ATTEMPT_FILENAME = os.path.basename(CONVERSION_ATTEMPT_RELATIVE_PATH)
_IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"})
_AUDIO_EXTENSIONS = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"})
_FONT_EXTENSIONS = frozenset({".otf", ".ttf", ".woff", ".woff2"})

FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
PathIdentity: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class ConversionOutputSnapshot:
    """Destination state captured before a conversion starts."""

    files: Mapping[str, FileFingerprint]


@dataclass(frozen=True)
class GeneratedFileEntry:
    path: str
    kind: str
    sha256: str

    def to_dict(self) -> JsonDict:
        return {
            "path": self.path,
            "kind": self.kind,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class _ArtifactTargetState:
    fingerprint: FileFingerprint | None
    mode: int | None

    @property
    def identity(self) -> PathIdentity | None:
        if self.fingerprint is None:
            return None
        return self.fingerprint[:2]


@dataclass(frozen=True)
class _TemporaryArtifact:
    path: str
    identity: PathIdentity
    sha256: str
    # ``mode`` is the mode the artifact must have after publication.  On
    # Windows, a read-only destination cannot be replaced and a read-only
    # temporary file cannot be cleaned up.  ``staged_mode`` therefore records
    # the cleanup-safe mode retained while the file still has its temporary
    # name; it may differ from ``mode`` until the final replacement.
    mode: int
    staged_mode: int


@dataclass(frozen=True)
class _PublishedArtifact:
    path: str
    identity: PathIdentity
    sha256: str
    mode: int
    backup: _TemporaryArtifact | None


def write_conversion_artifacts(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
    output_snapshot: ConversionOutputSnapshot,
    manifest_outcome: ConversionOutcome | None,
    attempt_outcome: ConversionOutcome,
) -> tuple[str | None, str]:
    """Transactionally publish the final attempt and, when trustworthy, manifest.

    Every terminal attempt is written separately.  A failed or cancelled run
    without a trustworthy completed-work candidate preserves the prior
    canonical manifest; late report/finalizer outcomes may retain a matching
    candidate.  When both artifacts are published, the attempt is replaced
    first and the canonical manifest last.
    """
    enabled_converter_keys = _normalized_enabled_converter_keys(enabled_converters)
    expected_steps = _planned_step_names(enabled_converter_keys)
    _validate_outcome_plan(
        attempt_outcome,
        expected_steps,
        description="Conversion attempt",
    )
    if manifest_outcome is not None:
        _validate_canonical_outcome(
            manifest_outcome,
            expected_steps,
        )
        _validate_attempt_matches_canonical(
            manifest_outcome,
            attempt_outcome,
        )

    manifest_path = os.path.join(godot_project_path, CONVERSION_MANIFEST_RELATIVE_PATH)
    attempt_path = os.path.join(godot_project_path, CONVERSION_ATTEMPT_RELATIVE_PATH)
    (
        artifact_directory,
        initial_root_identity,
        initial_directory_identity,
    ) = _inspect_artifact_directory(godot_project_path)
    manifest_state = (
        _artifact_target_state(manifest_path)
        if initial_directory_identity is not None
        else _ArtifactTargetState(fingerprint=None, mode=None)
    )
    attempt_state = (
        _artifact_target_state(attempt_path)
        if initial_directory_identity is not None
        else _ArtifactTargetState(fingerprint=None, mode=None)
    )

    manifest_content: bytes | None = None
    if manifest_outcome is not None:
        manifest_payload = build_conversion_manifest(
            gm_project_path,
            godot_project_path,
            target_platform=target_platform,
            enabled_converters=enabled_converter_keys,
            output_snapshot=output_snapshot,
            conversion_outcome=manifest_outcome,
        )
        manifest_content = _serialize_json(manifest_payload)
        manifest_status = "updated"
        current_output_status = "verified"
        manifest_digest: str | None = _sha256_bytes(manifest_content)
    elif manifest_state.identity is not None:
        manifest_content_before = _read_artifact_bytes(manifest_path, manifest_state)
        manifest_status = "preserved"
        current_output_status = "unverified"
        manifest_digest = _sha256_bytes(manifest_content_before)
    else:
        manifest_status = "absent"
        current_output_status = "unavailable"
        manifest_digest = None

    attempt_payload: JsonDict = {
        "format_version": 1,
        "attempt": _conversion_record(attempt_outcome),
        "canonical_manifest": {
            "path": CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/"),
            "status": manifest_status,
            "updated": manifest_outcome is not None,
            "current_output": current_output_status,
            "sha256": manifest_digest,
        },
    }
    attempt_content = _serialize_json(attempt_payload)

    prepared_directory, root_identity, directory_identity = (
        _prepare_artifact_directory(godot_project_path)
    )
    if (
        prepared_directory != artifact_directory
        or root_identity != initial_root_identity
        or (
            initial_directory_identity is not None
            and directory_identity != initial_directory_identity
        )
    ):
        raise OSError("Conversion artifact directory changed before publication.")
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _verify_artifact_target_state(manifest_path, manifest_state)
    _verify_artifact_target_state(attempt_path, attempt_state)
    stale_temporary_paths = _capture_owned_stale_artifacts(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )

    publish_specs: list[tuple[str, bytes, _ArtifactTargetState]] = [
        (attempt_path, attempt_content, attempt_state),
    ]
    if manifest_content is not None and manifest_outcome is not None:
        publish_specs.append((manifest_path, manifest_content, manifest_state))

    temporary_paths: dict[str, _TemporaryArtifact] = {}
    published: list[_PublishedArtifact] = []
    active_error: BaseException | None = None

    def verify_preserved_manifest() -> None:
        if manifest_outcome is None:
            _verify_artifact_target_state(manifest_path, manifest_state)

    try:
        staged: dict[str, _TemporaryArtifact] = {}
        backups: dict[str, _TemporaryArtifact | None] = {}
        for target_path, content, target_state in publish_specs:
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            verify_preserved_manifest()
            _verify_artifact_target_state(target_path, target_state)
            staged_artifact = _stage_artifact_bytes(
                target_path,
                content,
                mode=target_state.mode,
                suffix=".tmp",
            )
            temporary_paths[staged_artifact.path] = staged_artifact
            staged[target_path] = staged_artifact

        for target_path, _content, target_state in publish_specs:
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            verify_preserved_manifest()
            backup = _stage_existing_artifact(target_path, target_state)
            backups[target_path] = backup
            if backup is not None:
                temporary_paths[backup.path] = backup

        try:
            for target_path, _content, target_state in publish_specs:
                _verify_artifact_directory(
                    godot_project_path,
                    root_identity,
                    artifact_directory,
                    directory_identity,
                )
                verify_preserved_manifest()
                _verify_artifact_target_state(target_path, target_state)
                staged_artifact = staged[target_path]
                backup = backups[target_path]
                _publish_staged_artifact(
                    staged_artifact,
                    target_path,
                    target_state,
                    backup,
                    temporary_paths,
                    published,
                )
                _fsync_artifact_directory(
                    godot_project_path,
                    root_identity,
                    artifact_directory,
                    directory_identity,
                )
                _verify_temporary_artifact(
                    staged_artifact,
                    path=target_path,
                )
                verify_preserved_manifest()
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            for published_artifact in published:
                _verify_published_artifact(published_artifact)
            verify_preserved_manifest()
        except BaseException as publish_error:
            rollback_errors = _rollback_artifacts(
                published,
                temporary_paths,
                godot_project_path=godot_project_path,
                root_identity=root_identity,
                artifact_directory=artifact_directory,
                directory_identity=directory_identity,
            )
            if rollback_errors:
                publish_error.add_note(
                    "Conversion artifact rollback also failed: "
                    + "; ".join(str(error) for error in rollback_errors)
                )
            raise
    except BaseException as error:
        active_error = error
        raise
    finally:
        if active_error is None:
            # Recovery copies from an earlier failed cleanup remain useful until
            # a later artifact pair commits.  Only then may this transaction
            # retire the rigorously recognized, identity-captured leftovers.
            for stale_path, stale_artifact in stale_temporary_paths.items():
                stale_target = _owned_temporary_artifact_target(
                    os.path.basename(stale_path)
                )
                if (
                    stale_target == _MANIFEST_FILENAME
                    and manifest_outcome is None
                ):
                    # An attempt-only commit does not supersede a canonical
                    # recovery copy left by an earlier failed rollback.
                    continue
                temporary_paths.setdefault(stale_path, stale_artifact)
        cleanup_errors = _cleanup_temporary_artifacts(
            temporary_paths,
            godot_project_path=godot_project_path,
            root_identity=root_identity,
            artifact_directory=artifact_directory,
            directory_identity=directory_identity,
        )
        if cleanup_errors:
            message = "Conversion artifact cleanup failed: " + "; ".join(
                str(error) for error in cleanup_errors
            )
            if active_error is not None:
                active_error.add_note(message)
            # Both final replacements and their directory fsyncs have already
            # completed.  Cleanup cannot make that durable commit a failed
            # conversion attempt. Recoverable leftovers are excluded from
            # generated-files accounting and retried after a later commit.

    # Cleanup performs the transaction's final directory fsync. Revalidate the
    # committed pair afterward so a concurrent change during that sync can
    # never be reported as a successful publication.
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    for published_artifact in published:
        _verify_published_artifact(published_artifact)
    verify_preserved_manifest()

    return (
        manifest_path if manifest_outcome is not None else None,
        attempt_path,
    )


def build_conversion_manifest(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
    output_snapshot: ConversionOutputSnapshot,
    conversion_outcome: ConversionOutcome,
) -> JsonDict:
    enabled_converter_keys = _normalized_enabled_converter_keys(enabled_converters)
    _validate_canonical_outcome(
        conversion_outcome,
        _planned_step_names(enabled_converter_keys),
    )
    project_manifest = load_gamemaker_project_manifest(gm_project_path, target_platform=target_platform)
    asset_entries = _asset_registry_entries(
        gm_project_path,
        godot_project_path,
        macro_configuration=target_platform,
    )
    generated_files = _generated_files(godot_project_path, output_snapshot)
    return {
        "format_version": 2,
        "conversion": _conversion_record(conversion_outcome),
        "target_platform": target_platform,
        "enabled_converters": list(enabled_converter_keys),
        "source_project": {
            "name": project_manifest.project_name,
            "yyp_path": _relative_source_path(project_manifest.yyp_path, gm_project_path),
            "resource_type": project_manifest.resource_type,
            "resource_version": project_manifest.resource_version,
            "ide_version": project_manifest.ide_version,
        },
        "resources": [entry.to_godot_dict() for entry in asset_entries],
        "generated_files": [entry.to_dict() for entry in generated_files],
        "source_maps": [
            entry.to_dict()
            for entry in generated_files
            if entry.path.endswith(".gmlmap.json")
        ],
        "architecture_policies": build_architecture_policy_report(
            gm_project_path,
            target_platform=target_platform,
            enabled_converters=enabled_converter_keys,
        ),
        "path_diagnostics": _path_diagnostics(asset_entries),
    }


def _conversion_record(outcome: ConversionOutcome) -> JsonDict:
    return {
        **outcome.to_dict(),
        "cancelled": outcome.state == "cancelled",
    }


def _normalized_enabled_converter_keys(
    enabled_converters: Iterable[str],
) -> tuple[str, ...]:
    if isinstance(enabled_converters, (str, bytes)):
        raise TypeError("Enabled converters must be an iterable of step names.")
    enabled_keys = tuple(enabled_converters)
    for key in enabled_keys:
        if type(key) is not str:
            raise TypeError("Enabled converter keys must be strings.")
        if not key:
            raise ValueError("Enabled converter keys cannot be empty.")
    known_keys = conversion_step_map()
    unknown_keys = tuple(sorted(set(enabled_keys) - known_keys.keys()))
    if unknown_keys:
        raise ValueError(
            "Unknown enabled converter key(s): " + ", ".join(unknown_keys)
        )
    return tuple(sorted(set(enabled_keys)))


def _planned_step_names(enabled_converter_keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        step.key for step in build_conversion_plan(enabled_converter_keys)
    )


def _validate_outcome_plan(
    outcome: ConversionOutcome,
    expected_steps: tuple[str, ...],
    *,
    description: str,
) -> None:
    if outcome.steps.requested != expected_steps:
        raise ValueError(
            f"{description} requested steps must match the enabled conversion plan; "
            f"expected {expected_steps!r}, got {outcome.steps.requested!r}."
        )


def _validate_canonical_outcome(
    outcome: ConversionOutcome,
    expected_steps: tuple[str, ...],
) -> None:
    if outcome.state not in {"success", "partial"}:
        raise ValueError(
            "Canonical conversion manifests require a success or partial outcome."
        )
    _validate_outcome_plan(
        outcome,
        expected_steps,
        description="Canonical conversion manifest",
    )
    if outcome.steps.completed != expected_steps:
        raise ValueError(
            "Canonical conversion manifests require every enabled converter step "
            "to complete."
        )


def _validate_attempt_matches_canonical(
    canonical_outcome: ConversionOutcome,
    attempt_outcome: ConversionOutcome,
) -> None:
    if (
        attempt_outcome.steps != canonical_outcome.steps
        or attempt_outcome.resources != canonical_outcome.resources
    ):
        raise ValueError(
            "A canonical update and its terminal attempt must describe the same "
            "executed converter and resource work."
        )
    if (
        attempt_outcome.state in {"success", "partial"}
        and attempt_outcome != canonical_outcome
    ):
        raise ValueError(
            "A successful or partial terminal attempt must match its canonical "
            "conversion outcome exactly."
        )
    if attempt_outcome.state == "failed":
        if attempt_outcome.failure_phase not in {"report", "finalizer"}:
            raise ValueError(
                "A failed terminal attempt may retain a canonical update only "
                "for a report or finalizer failure after completed conversion work."
            )
        if (
            type(attempt_outcome.failed_step) is not str
            or not attempt_outcome.failed_step
        ):
            raise ValueError(
                "A failed terminal attempt retaining a canonical update requires "
                "a named failed step."
            )


def _serialize_json(payload: JsonDict) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _inspect_artifact_directory(
    godot_project_path: str,
) -> tuple[str, PathIdentity, PathIdentity | None]:
    try:
        root_stat = os.lstat(godot_project_path)
    except OSError as error:
        raise OSError(
            f"Conversion artifact root is unavailable: {godot_project_path}"
        ) from error
    if _path_is_redirected(godot_project_path, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        raise OSError(
            f"Refusing redirected or non-directory conversion artifact root: "
            f"{godot_project_path}"
        )
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    artifact_directory = os.path.join(
        godot_project_path,
        os.path.dirname(CONVERSION_MANIFEST_RELATIVE_PATH),
    )
    try:
        directory_stat = os.lstat(artifact_directory)
    except FileNotFoundError:
        return artifact_directory, root_identity, None
    if _path_is_redirected(artifact_directory, directory_stat) or not stat.S_ISDIR(
        directory_stat.st_mode
    ):
        raise OSError(
            "Refusing redirected or non-directory conversion artifact directory: "
            f"{artifact_directory}"
        )
    directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    return artifact_directory, root_identity, directory_identity


def _prepare_artifact_directory(
    godot_project_path: str,
) -> tuple[str, PathIdentity, PathIdentity]:
    artifact_directory, root_identity, directory_identity = (
        _inspect_artifact_directory(godot_project_path)
    )
    if directory_identity is None:
        _verify_directory_path(
            godot_project_path,
            root_identity,
            description="conversion artifact root",
        )
        try:
            os.mkdir(artifact_directory)
        except FileExistsError:
            pass
        directory_stat = os.lstat(artifact_directory)
        if _path_is_redirected(
            artifact_directory,
            directory_stat,
        ) or not stat.S_ISDIR(directory_stat.st_mode):
            raise OSError(
                "Refusing redirected or non-directory conversion artifact "
                f"directory: {artifact_directory}"
            )
        directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    # Always sync the parent before using the child.  A previous publication
    # may have created the directory and then failed while syncing this root;
    # on that retry the child already exists but its directory entry still
    # needs to become durable.
    _fsync_verified_directory(
        godot_project_path,
        root_identity,
        description="conversion artifact root",
    )
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    return artifact_directory, root_identity, directory_identity


def _verify_artifact_directory(
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> None:
    _verify_directory_path(
        godot_project_path,
        root_identity,
        description="conversion artifact root",
    )
    _verify_directory_path(
        artifact_directory,
        directory_identity,
        description="conversion artifact directory",
    )


def _verify_directory_path(
    path: str,
    expected_identity: PathIdentity,
    *,
    description: str,
) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(f"{description.capitalize()} changed: {path}") from error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"{description.capitalize()} changed: {path}")


def _path_is_redirected(path: str, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    junction_candidate: object = getattr(os.path, "isjunction", None)
    if not callable(junction_candidate):
        return False
    junction_checker = cast(Callable[[str], bool], junction_candidate)
    return junction_checker(path)


def _artifact_target_state(path: str) -> _ArtifactTargetState:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return _ArtifactTargetState(fingerprint=None, mode=None)
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Refusing redirected or non-regular conversion artifact: {path}")
    return _ArtifactTargetState(
        fingerprint=_file_fingerprint(path_stat),
        mode=stat.S_IMODE(path_stat.st_mode),
    )


def _verify_artifact_target_state(
    path: str,
    expected: _ArtifactTargetState,
) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if expected.fingerprint is None:
            return
        raise OSError(f"Conversion artifact disappeared during publication: {path}")
    if (
        expected.fingerprint is None
        or _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or _file_fingerprint(path_stat) != expected.fingerprint
        or stat.S_IMODE(path_stat.st_mode) != expected.mode
    ):
        raise OSError(f"Conversion artifact changed during publication: {path}")


def _read_artifact_bytes(path: str, expected: _ArtifactTargetState) -> bytes:
    if expected.fingerprint is None:
        raise ValueError("Cannot read an absent conversion artifact.")
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, open_flags)
    try:
        open_stat_before = os.fstat(file_descriptor)
        path_stat = os.lstat(path)
        if (
            not stat.S_ISREG(open_stat_before.st_mode)
            or _file_fingerprint(open_stat_before) != expected.fingerprint
            or _file_fingerprint(path_stat) != expected.fingerprint
        ):
            raise OSError(
                f"Conversion artifact changed while reading it: {path}"
            )
        with os.fdopen(file_descriptor, "rb") as artifact_file:
            file_descriptor = -1
            content = artifact_file.read()
            open_stat_after = os.fstat(artifact_file.fileno())
        if _file_fingerprint(open_stat_after) != expected.fingerprint:
            raise OSError(f"Conversion artifact changed while reading it: {path}")
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_artifact_target_state(path, expected)
    return content


def _stage_existing_artifact(
    path: str,
    expected: _ArtifactTargetState,
) -> _TemporaryArtifact | None:
    if expected.fingerprint is None:
        return None
    content = _read_artifact_bytes(path, expected)
    _verify_artifact_target_state(path, expected)
    return _stage_artifact_bytes(
        path,
        content,
        mode=expected.mode,
        suffix=".backup",
    )


def _capture_owned_stale_artifacts(
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> dict[str, _TemporaryArtifact]:
    """Capture safe-to-retire leftovers from earlier artifact transactions."""
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    captured: dict[str, _TemporaryArtifact] = {}
    with os.scandir(artifact_directory) as entries:
        filenames = sorted(entry.name for entry in entries)
    for filename in filenames:
        if not _is_owned_temporary_artifact_filename(filename):
            continue
        path = os.path.join(artifact_directory, filename)
        try:
            target_state = _artifact_target_state(path)
            if (
                target_state.identity is None
                or target_state.mode is None
            ):
                continue
            content = _read_artifact_bytes(path, target_state)
        except OSError:
            # Redirected, non-regular, inaccessible, or concurrently changed
            # lookalikes are never candidates for automatic deletion.
            continue
        captured[path] = _TemporaryArtifact(
            path=path,
            identity=target_state.identity,
            sha256=_sha256_bytes(content),
            mode=target_state.mode,
            staged_mode=target_state.mode,
        )
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    return captured


def _is_owned_temporary_artifact_filename(filename: str) -> bool:
    return _owned_temporary_artifact_target(filename) is not None


def _owned_temporary_artifact_target(filename: str) -> str | None:
    for artifact_filename in (_MANIFEST_FILENAME, _ATTEMPT_FILENAME):
        prefix = f".{artifact_filename}."
        if not filename.startswith(prefix):
            continue
        for suffix in (".recovery.backup", ".backup", ".tmp"):
            if not filename.endswith(suffix):
                continue
            random_name = filename[len(prefix):-len(suffix)]
            if bool(random_name) and random_name.isascii() and all(
                character.isalnum() or character == "_"
                for character in random_name
            ):
                return artifact_filename
    return None


def _stage_artifact_bytes(
    path: str,
    content: bytes,
    *,
    mode: int | None,
    suffix: str,
) -> _TemporaryArtifact:
    artifact_directory = os.path.dirname(path) or os.curdir
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=artifact_directory,
        prefix=f".{os.path.basename(path)}.",
        suffix=suffix,
    )
    initial_stat = os.fstat(file_descriptor)
    staged_identity = (initial_stat.st_dev, initial_stat.st_ino)
    target_mode = (
        stat.S_IMODE(initial_stat.st_mode)
        if mode is None
        else mode
    )
    try:
        with os.fdopen(file_descriptor, "wb") as staged_file:
            file_descriptor = -1
            staged_file.write(content)
            staged_file.flush()
            if mode is not None and not (
                _uses_windows_file_attribute_modes()
                and _mode_is_read_only(mode)
            ):
                fchmod_candidate: object = getattr(os, "fchmod", None)
                if callable(fchmod_candidate):
                    fchmod = cast(Callable[[int, int], None], fchmod_candidate)
                    try:
                        fchmod(staged_file.fileno(), mode)
                    except NotImplementedError:
                        fchmod_candidate = None
                if not callable(fchmod_candidate):
                    _verify_regular_path_identity(staged_path, staged_identity)
                    os.chmod(staged_path, mode)
                    _verify_regular_path_identity(staged_path, staged_identity)
            os.fsync(staged_file.fileno())
        staged_stat = os.lstat(staged_path)
        staged_mode = stat.S_IMODE(staged_stat.st_mode)
        if (
            not _uses_windows_file_attribute_modes()
            and staged_mode != target_mode
        ) or (
            _uses_windows_file_attribute_modes()
            and _mode_is_read_only(staged_mode)
        ):
            raise OSError(
                f"Staged conversion artifact mode changed: {staged_path}"
            )
        staged_artifact = _TemporaryArtifact(
            path=staged_path,
            identity=staged_identity,
            sha256=_sha256_bytes(content),
            mode=target_mode,
            staged_mode=staged_mode,
        )
        _verify_temporary_artifact(staged_artifact)
        return staged_artifact
    except BaseException as error:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        cleanup_error = _unlink_if_identity(staged_path, staged_identity)
        if cleanup_error is not None:
            error.add_note(
                "Failed to remove incomplete conversion artifact stage "
                f"{staged_path}: {cleanup_error}"
            )
        raise


def _verify_regular_path_identity(path: str, expected: PathIdentity) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(f"Staged conversion artifact changed: {path}") from error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected
    ):
        raise OSError(f"Staged conversion artifact changed: {path}")


def _regular_path_identity(path: str) -> PathIdentity:
    path_stat = os.lstat(path)
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(f"Refusing redirected or non-regular conversion artifact: {path}")
    return (path_stat.st_dev, path_stat.st_ino)


def _read_verified_temporary_artifact(
    artifact: _TemporaryArtifact,
    *,
    path: str | None = None,
) -> bytes:
    selected_path = artifact.path if path is None else path
    expected_mode = artifact.staged_mode if path is None else artifact.mode
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(selected_path, open_flags)
    try:
        opened_before = os.fstat(file_descriptor)
        fingerprint_before = _file_fingerprint(opened_before)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or (opened_before.st_dev, opened_before.st_ino) != artifact.identity
            or stat.S_IMODE(opened_before.st_mode) != expected_mode
        ):
            raise OSError(
                f"Staged conversion artifact changed: {selected_path}"
            )
        with os.fdopen(file_descriptor, "rb") as artifact_file:
            file_descriptor = -1
            content = artifact_file.read()
            opened_after = os.fstat(artifact_file.fileno())
        path_after = os.lstat(selected_path)
        if (
            not stat.S_ISREG(opened_after.st_mode)
            or (opened_after.st_dev, opened_after.st_ino) != artifact.identity
            or stat.S_IMODE(opened_after.st_mode) != expected_mode
            or stat.S_IMODE(path_after.st_mode) != expected_mode
            or _file_fingerprint(opened_after) != fingerprint_before
            or _file_fingerprint(path_after) != fingerprint_before
            or _sha256_bytes(content) != artifact.sha256
        ):
            raise OSError(
                f"Staged conversion artifact content changed: {selected_path}"
            )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_regular_path_identity(selected_path, artifact.identity)
    return content


def _verify_temporary_artifact(
    artifact: _TemporaryArtifact,
    *,
    path: str | None = None,
) -> None:
    _read_verified_temporary_artifact(artifact, path=path)


def _uses_windows_file_attribute_modes() -> bool:
    """Return whether chmod only models the Windows read-only attribute."""
    return os.name == "nt"


def _mode_is_read_only(mode: int) -> bool:
    return not bool(mode & stat.S_IWRITE)


def _set_artifact_mode_exact(
    path: str,
    expected_identity: PathIdentity,
    mode: int,
) -> None:
    _verify_regular_path_identity(path, expected_identity)
    os.chmod(path, mode)
    _verify_regular_path_identity(path, expected_identity)
    current_mode = stat.S_IMODE(os.lstat(path).st_mode)
    if current_mode != mode:
        raise OSError(f"Conversion artifact mode changed: {path}")


def _restore_artifact_mode_if_identity_matches(
    path: str,
    expected_identity: PathIdentity,
    mode: int,
) -> Exception | None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except Exception as error:
        return error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        return OSError(f"Conversion artifact changed before mode restore: {path}")
    if stat.S_IMODE(path_stat.st_mode) == mode:
        return None
    try:
        _set_artifact_mode_exact(path, expected_identity, mode)
    except Exception as error:
        return error
    return None


def _make_windows_destination_writable(
    path: str,
    expected_identity: PathIdentity | None,
    expected_mode: int | None,
) -> bool:
    """Temporarily clear a destination's Windows read-only attribute."""
    if (
        not _uses_windows_file_attribute_modes()
        or expected_identity is None
        or expected_mode is None
        or not _mode_is_read_only(expected_mode)
    ):
        return False
    _verify_regular_path_identity(path, expected_identity)
    writable_mode = expected_mode | stat.S_IWRITE
    try:
        os.chmod(path, writable_mode)
        _verify_regular_path_identity(path, expected_identity)
        current_mode = stat.S_IMODE(os.lstat(path).st_mode)
        if _mode_is_read_only(current_mode):
            raise OSError(f"Conversion artifact remained read-only: {path}")
    except BaseException as error:
        restore_error = _restore_artifact_mode_if_identity_matches(
            path,
            expected_identity,
            expected_mode,
        )
        if restore_error is not None:
            error.add_note(
                "Failed to restore read-only conversion artifact after mode "
                f"preparation failure: {restore_error}"
            )
        raise
    return True


def _activate_windows_artifact_mode(artifact: _TemporaryArtifact) -> bool:
    """Apply a staged artifact's final Windows mode immediately before rename."""
    if (
        not _uses_windows_file_attribute_modes()
        or artifact.staged_mode == artifact.mode
    ):
        return False
    try:
        _set_artifact_mode_exact(
            artifact.path,
            artifact.identity,
            artifact.mode,
        )
    except BaseException as error:
        restore_error = _restore_artifact_mode_if_identity_matches(
            artifact.path,
            artifact.identity,
            artifact.staged_mode,
        )
        if restore_error is not None:
            error.add_note(
                "Failed to restore writable conversion artifact stage after "
                f"mode activation failure: {restore_error}"
            )
        raise
    return True


def _replace_temporary_artifact(
    artifact: _TemporaryArtifact,
    target_path: str,
    *,
    expected_target_identity: PathIdentity | None,
    expected_target_mode: int | None,
) -> BaseException | None:
    """Replace a target while preserving Windows read-only semantics.

    A non-``None`` return means ``os.replace`` reported an error after the
    staged inode nevertheless reached the target.  The caller can verify the
    committed inode before deciding whether that error remains primary.
    """
    destination_mode_changed = False
    staged_mode_changed = False
    try:
        destination_mode_changed = _make_windows_destination_writable(
            target_path,
            expected_target_identity,
            expected_target_mode,
        )
        staged_mode_changed = _activate_windows_artifact_mode(artifact)
        os.replace(artifact.path, target_path)
    except BaseException as error:
        try:
            replacement_completed = (
                _regular_path_identity(target_path) == artifact.identity
            )
        except OSError:
            replacement_completed = False
        if replacement_completed:
            return error

        restore_errors: list[Exception] = []
        if staged_mode_changed:
            restore_error = _restore_artifact_mode_if_identity_matches(
                artifact.path,
                artifact.identity,
                artifact.staged_mode,
            )
            if restore_error is not None:
                restore_errors.append(restore_error)
        if destination_mode_changed:
            assert expected_target_identity is not None
            assert expected_target_mode is not None
            restore_error = _restore_artifact_mode_if_identity_matches(
                target_path,
                expected_target_identity,
                expected_target_mode,
            )
            if restore_error is not None:
                restore_errors.append(restore_error)
        if restore_errors:
            error.add_note(
                "Conversion artifact mode restoration also failed: "
                + "; ".join(str(restore_error) for restore_error in restore_errors)
            )
        raise
    return None


def _publish_staged_artifact(
    staged_artifact: _TemporaryArtifact,
    target_path: str,
    expected_target_state: _ArtifactTargetState,
    backup: _TemporaryArtifact | None,
    temporary_paths: dict[str, _TemporaryArtifact],
    published: list[_PublishedArtifact],
) -> None:
    _verify_temporary_artifact(staged_artifact)
    replacement_error = _replace_temporary_artifact(
        staged_artifact,
        target_path,
        expected_target_identity=expected_target_state.identity,
        expected_target_mode=expected_target_state.mode,
    )
    temporary_paths.pop(staged_artifact.path, None)
    published.append(
        _PublishedArtifact(
            path=target_path,
            identity=staged_artifact.identity,
            sha256=staged_artifact.sha256,
            mode=staged_artifact.mode,
            backup=backup,
        )
    )
    try:
        _verify_temporary_artifact(staged_artifact, path=target_path)
    except BaseException as integrity_error:
        if replacement_error is not None:
            replacement_error.add_note(
                "Published conversion artifact also failed integrity "
                f"verification: {integrity_error}"
            )
            raise replacement_error
        raise
    if replacement_error is not None:
        raise replacement_error


def _verify_published_artifact(artifact: _PublishedArtifact) -> None:
    _verify_temporary_artifact(
        _TemporaryArtifact(
            path=artifact.path,
            identity=artifact.identity,
            sha256=artifact.sha256,
            mode=artifact.mode,
            staged_mode=artifact.mode,
        )
    )


def _remove_published_artifact(artifact: _PublishedArtifact) -> None:
    destination_mode_changed = _make_windows_destination_writable(
        artifact.path,
        artifact.identity,
        artifact.mode,
    )
    try:
        os.unlink(artifact.path)
    except BaseException as error:
        if not os.path.lexists(artifact.path):
            return
        if destination_mode_changed:
            restore_error = _restore_artifact_mode_if_identity_matches(
                artifact.path,
                artifact.identity,
                artifact.mode,
            )
            if restore_error is not None:
                error.add_note(
                    "Failed to restore conversion artifact mode after removal "
                    f"failure: {restore_error}"
                )
        raise


def _rollback_artifacts(
    published: list[_PublishedArtifact],
    temporary_paths: dict[str, _TemporaryArtifact],
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> list[BaseException]:
    errors: list[BaseException] = []
    restored: list[
        tuple[_PublishedArtifact, _TemporaryArtifact | None]
    ] = []
    for artifact in reversed(published):
        recovery_artifact: _TemporaryArtifact | None = None
        try:
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            _verify_published_artifact(artifact)
            if artifact.backup is None:
                _remove_published_artifact(artifact)
            else:
                backup_content = _read_verified_temporary_artifact(
                    artifact.backup,
                )
                recovery_artifact = _stage_artifact_bytes(
                    artifact.path,
                    backup_content,
                    mode=artifact.backup.mode,
                    suffix=".recovery.backup",
                )
                temporary_paths[recovery_artifact.path] = recovery_artifact
                _replace_temporary_artifact(
                    artifact.backup,
                    artifact.path,
                    expected_target_identity=artifact.identity,
                    expected_target_mode=artifact.mode,
                )
                temporary_paths.pop(artifact.backup.path, None)
                _verify_temporary_artifact(
                    artifact.backup,
                    path=artifact.path,
                )
            _fsync_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            if artifact.backup is None:
                if os.path.lexists(artifact.path):
                    raise OSError(
                        "Removed conversion artifact reappeared during rollback: "
                        f"{artifact.path}"
                    )
            else:
                _verify_temporary_artifact(
                    artifact.backup,
                    path=artifact.path,
                )
            restored.append((artifact, recovery_artifact))
        except BaseException as error:
            recovery_path: str | None = None
            if recovery_artifact is not None:
                try:
                    _verify_temporary_artifact(recovery_artifact)
                except OSError:
                    pass
                else:
                    recovery_path = recovery_artifact.path
            if recovery_path is None and artifact.backup is not None:
                try:
                    _verify_temporary_artifact(artifact.backup)
                except OSError:
                    pass
                else:
                    recovery_path = artifact.backup.path
            if recovery_path is not None:
                temporary_paths.pop(recovery_path, None)
                rollback_error = OSError(
                    f"{error}; previous conversion artifact preserved at: "
                    f"{recovery_path}"
                )
                rollback_error.__cause__ = error
                errors.append(rollback_error)
            else:
                errors.append(error)
    for artifact, recovery_artifact in restored:
        try:
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            if artifact.backup is None:
                if os.path.lexists(artifact.path):
                    raise OSError(
                        "Removed conversion artifact reappeared after rollback: "
                        f"{artifact.path}"
                    )
            else:
                _verify_temporary_artifact(
                    artifact.backup,
                    path=artifact.path,
                )
        except BaseException as error:
            recovery_path: str | None = None
            if recovery_artifact is not None:
                try:
                    _verify_temporary_artifact(recovery_artifact)
                except OSError:
                    pass
                else:
                    recovery_path = recovery_artifact.path
            if recovery_path is not None:
                temporary_paths.pop(recovery_path, None)
                rollback_error = OSError(
                    f"{error}; previous conversion artifact preserved at: "
                    f"{recovery_path}"
                )
                rollback_error.__cause__ = error
                errors.append(rollback_error)
            else:
                errors.append(error)
    return errors


def _cleanup_temporary_artifacts(
    temporary_paths: dict[str, _TemporaryArtifact],
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> list[Exception]:
    errors: list[Exception] = []
    removed = False
    for temporary_path, temporary_artifact in tuple(temporary_paths.items()):
        try:
            _verify_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            if not os.path.lexists(temporary_path):
                temporary_paths.pop(temporary_path, None)
                continue
            _verify_temporary_artifact(temporary_artifact)
            try:
                os.unlink(temporary_path)
            except Exception:
                if os.path.lexists(temporary_path):
                    raise
            temporary_paths.pop(temporary_path, None)
            removed = True
        except Exception as error:
            errors.append(error)
    if removed:
        try:
            _fsync_artifact_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
        except Exception as error:
            errors.append(error)
    return errors


def _unlink_if_identity(
    path: str,
    expected_identity: PathIdentity,
) -> Exception | None:
    try:
        _verify_regular_path_identity(path, expected_identity)
        os.unlink(path)
    except Exception as error:
        return error
    return None


def _fsync_verified_directory(
    path: str,
    expected_identity: PathIdentity,
    *,
    description: str,
) -> None:
    _verify_directory_path(
        path,
        expected_identity,
        description=description,
    )
    if os.name == "nt":
        return
    open_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os,
        "O_NOFOLLOW",
        0,
    )
    directory_descriptor = os.open(path, open_flags)
    try:
        opened_stat = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino) != expected_identity
        ):
            raise OSError(f"{description.capitalize()} changed: {path}")
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    _verify_directory_path(
        path,
        expected_identity,
        description=description,
    )


def _fsync_artifact_directory(
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> None:
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _fsync_verified_directory(
        artifact_directory,
        directory_identity,
        description="conversion artifact directory",
    )
    _verify_artifact_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )


def _asset_registry_entries(
    gm_project_path: str,
    godot_project_path: str,
    *,
    macro_configuration: str | None = None,
) -> tuple[AssetRegistryEntry, ...]:
    converter = AssetRegistryConverter(
        gm_project_path,
        godot_project_path,
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
        macro_configuration=macro_configuration,
    )
    return converter.build_entries()


def capture_conversion_output_snapshot(godot_project_path: str) -> ConversionOutputSnapshot:
    """Capture destination files before conversion so emitted outputs are identifiable."""
    files = {
        relative_path: fingerprint
        for _path, relative_path, fingerprint in _destination_files(godot_project_path)
    }
    return ConversionOutputSnapshot(files=files)


def _generated_files(
    godot_project_path: str,
    output_snapshot: ConversionOutputSnapshot,
) -> tuple[GeneratedFileEntry, ...]:
    entries: list[GeneratedFileEntry] = []
    manifest_relative_path = CONVERSION_MANIFEST_RELATIVE_PATH.replace(os.sep, "/")
    for path, relative_path, fingerprint in _destination_files(godot_project_path):
        if (
            relative_path == manifest_relative_path
            or _is_auxiliary_conversion_artifact(relative_path)
        ):
            continue
        if output_snapshot.files.get(relative_path) == fingerprint:
            continue
        entries.append(
            GeneratedFileEntry(
                path=relative_path,
                kind=_generated_file_kind(relative_path),
                sha256=_sha256_file(path),
            )
        )
    entries.append(
        GeneratedFileEntry(
            path=manifest_relative_path,
            kind="manifest",
            sha256="self",
        )
    )
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _is_auxiliary_conversion_artifact(relative_path: str) -> bool:
    normalized_path = relative_path.replace("\\", "/")
    attempt_relative_path = CONVERSION_ATTEMPT_RELATIVE_PATH.replace(os.sep, "/")
    if normalized_path == attempt_relative_path:
        return True
    artifact_directory = os.path.dirname(attempt_relative_path)
    relative_directory, filename = os.path.split(normalized_path)
    if relative_directory != artifact_directory:
        return False
    return any(
        filename.startswith(f".{artifact_filename}.")
        and filename.endswith((".tmp", ".backup"))
        for artifact_filename in (_MANIFEST_FILENAME, _ATTEMPT_FILENAME)
    )


def _destination_files(
    godot_project_path: str,
) -> Iterable[tuple[str, str, FileFingerprint]]:
    if os.path.islink(godot_project_path) or not os.path.isdir(godot_project_path):
        return
    for root, dirs, files in os.walk(godot_project_path):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if directory != ".godot"
            and not os.path.islink(os.path.join(root, directory))
        )
        for filename in sorted(files):
            path = os.path.join(root, filename)
            try:
                path_stat = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(path_stat.st_mode):
                continue
            relative_path = os.path.relpath(path, godot_project_path).replace(os.sep, "/")
            yield path, relative_path, _file_fingerprint(path_stat)


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _generated_file_kind(relative_path: str) -> str:
    if relative_path == "project.godot":
        return "project"
    if relative_path.endswith(".gmlmap.json"):
        return "source_map"
    if relative_path.endswith(".json"):
        return "report"
    if relative_path.endswith(".gd"):
        return "gdscript"
    if relative_path.endswith(".gdshader"):
        return "shader"
    if relative_path.endswith(".tscn"):
        return "scene"
    if relative_path.endswith(".tres"):
        return "resource"
    extension = os.path.splitext(relative_path)[1].lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _FONT_EXTENSIONS:
        return "font"
    if extension == ".import":
        return "import_metadata"
    return "file"


def _path_diagnostics(entries: tuple[AssetRegistryEntry, ...]) -> list[JsonDict]:
    diagnostics: list[JsonDict] = []
    paths_by_casefold: dict[str, list[AssetRegistryEntry]] = {}
    base_paths_by_casefold: dict[str, list[tuple[AssetRegistryEntry, str]]] = {}
    for entry in entries:
        if not entry.godot_path:
            continue
        paths_by_casefold.setdefault(entry.godot_path.casefold(), []).append(entry)
        base_path = _base_generated_path(entry)
        if base_path:
            base_paths_by_casefold.setdefault(base_path.casefold(), []).append((entry, base_path))
        unsafe_segments = _unsafe_segments(entry.godot_path)
        if unsafe_segments:
            diagnostics.append({
                "code": "GM2GD-PATH-NON-SNAKE-CASE",
                "severity": "info",
                "resource": entry.name,
                "resource_type": entry.kind,
                "godot_path": entry.godot_path,
                "unsafe_segments": unsafe_segments,
                "stable_suggestion": snake_case_res_path(entry.godot_path),
                "message": "Generated path contains non-snake-case segments; source metadata preserves the original GameMaker name.",
            })

    for folded_path, colliding_items in sorted(base_paths_by_casefold.items()):
        if len(colliding_items) < 2:
            continue
        diagnostics.append({
            "code": "GM2GD-PATH-COLLISION-RENAMED",
            "severity": "warning",
            "base_godot_path_casefold": folded_path,
            "resources": [
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "source_path": entry.source_path,
                    "base_godot_path": base_path,
                    "stable_godot_path": entry.godot_path,
                }
                for entry, base_path in sorted(
                    colliding_items,
                    key=lambda item: (item[0].kind, item[0].name, item[0].source_path),
                )
            ],
            "message": "Multiple GameMaker resources map to the same Godot-friendly path; stable suffixes were applied deterministically.",
        })

    for folded_path, colliding_entries in sorted(paths_by_casefold.items()):
        if len(colliding_entries) < 2:
            continue
        diagnostics.append({
            "code": "GM2GD-PATH-CASE-COLLISION",
            "severity": "warning",
            "godot_path_casefold": folded_path,
            "resources": [
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "source_path": entry.source_path,
                    "godot_path": entry.godot_path,
                }
                for entry in sorted(colliding_entries, key=lambda item: (item.kind, item.name, item.source_path))
            ],
            "stable_suggestions": [
                _collision_safe_path(entry.godot_path, index)
                for index, entry in enumerate(sorted(colliding_entries, key=lambda item: (item.kind, item.name, item.source_path)))
            ],
            "message": "Generated paths collide on case-insensitive file systems; suggestions are deterministic for project-specific remapping.",
        })
    return diagnostics


def _base_generated_path(entry: AssetRegistryEntry) -> str:
    segments = res_path_segments(entry.godot_path)
    if len(segments) < 2:
        return ""
    kind = segments[0]
    if kind in {"sprites", "objects", "rooms", "tilesets", "paths"} and len(segments) >= 3:
        extension = os.path.splitext(segments[-1])[1]
        subfolder = "/".join(segments[1:-2])
        return generated_nested_resource_path(kind, subfolder, entry.name, extension)
    if kind in {"scripts", "shaders", "fonts"}:
        extension = os.path.splitext(segments[-1])[1]
        subfolder = "/".join(segments[1:-1])
        return generated_flat_resource_path(kind, subfolder, entry.name, extension)
    if kind == "sounds" and len(segments) >= 3:
        base_segments = list(segments)
        base_segments[-2] = generated_resource_stem(entry.name)
        return "res://" + "/".join(base_segments)
    return entry.godot_path


def _unsafe_segments(res_path: str) -> list[str]:
    segments = res_path_segments(res_path)
    return [
        segment
        for segment in segments
        if not is_snake_case_path_segment(segment)
    ]


def _collision_safe_path(res_path: str, index: int) -> str:
    if index == 0:
        return snake_case_res_path(res_path)
    snake_path = snake_case_res_path(res_path)
    stem, extension = os.path.splitext(snake_path)
    return f"{stem}_{index + 1}{extension}"


def _relative_source_path(path: str | None, gm_project_path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path, gm_project_path).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
