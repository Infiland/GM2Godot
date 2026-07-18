from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable, TypeAlias, cast

from src.conversion.resource_index import GameMakerResourceIndex, IndexedRoom
from src.conversion.runtime_managers import runtime_manager_definitions
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    resolve_project_filesystem_source_path,
)
from src.conversion.type_defs import JsonDict

ARCHITECTURE_POLICY_RELATIVE_PATH = os.path.join("gm2godot", "architecture_policy.json")
ARCHITECTURE_POLICY_VERSION = 1

ROOM_ROOT_POLICY_ID = "gm_room_node2d"
LAYER_HIERARCHY_POLICY_ID = "gm_layer_depth_node2d"
GUI_LAYER_POLICY_ID = "gm_gui_canvas_layer"
DEPTH_MAPPING_POLICY_ID = "gamemaker_depth_to_negative_z_index"

GODOT_ARCHITECTURE_SOURCES: dict[str, str] = {
    "autoload": "https://docs.godotengine.org/en/stable/getting_started/step_by_step/singletons_autoload.html",
    "canvas_layer": "https://docs.godotengine.org/en/stable/tutorials/2d/canvas_layers.html",
    "physics_2d": "https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html",
    "audio_server": "https://docs.godotengine.org/en/stable/classes/class_audioserver.html",
    "http_request": "https://docs.godotengine.org/en/stable/classes/class_httprequest.html",
    "game_maker_event_order": "https://manual.gamemaker.io/monthly/en/The_Asset_Editors/Object_Properties/Event_Order.htm",
}

_DRAW_RE = re.compile(r"\b(draw_|shader_|gpu_|font_|sprite_)", re.IGNORECASE)
_SURFACE_RE = re.compile(r"\b(surface_|application_surface)", re.IGNORECASE)
_COLLISION_RE = re.compile(r"\b(collision_|place_meeting|position_meeting|instance_place|instance_position)", re.IGNORECASE)
_PRECISE_COLLISION_RE = re.compile(r"\bcollision_[A-Za-z0-9_]*\s*\([^;]*,\s*true\s*,", re.IGNORECASE)
_AUDIO_RE = re.compile(r"\b(audio_|sound_)", re.IGNORECASE)
_NETWORK_RE = re.compile(r"\b(network_|http_|url_open|steam_ugc_download)", re.IGNORECASE)
_BUFFER_FILE_RE = re.compile(r"\b(buffer_|file_|ini_|json_)", re.IGNORECASE)

FileFingerprint: TypeAlias = tuple[int, int, int, int, int]
ReceiptFingerprint: TypeAlias = tuple[int, int, int, int]
PathIdentity: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class ArchitecturePolicySnapshot:
    """Exact architecture-policy state captured before publication."""

    content: bytes | None
    mode: int | None
    fingerprint: FileFingerprint | None
    sha256: str | None

    @property
    def present(self) -> bool:
        return self.fingerprint is not None


@dataclass(frozen=True)
class ArchitecturePolicyPublicationReceipt:
    """Identity and content committed by one report publication."""

    path: str
    content: bytes
    mode: int
    fingerprint: ReceiptFingerprint
    sha256: str


@dataclass(frozen=True)
class _PolicyTargetState:
    fingerprint: FileFingerprint | None
    mode: int | None


@dataclass(frozen=True)
class _PolicyReplaceTarget:
    identity: PathIdentity
    mode: int
    mode_changed: bool


@dataclass(frozen=True)
class _StagedPolicyFile:
    path: str
    identity: PathIdentity
    content: bytes
    # Temporary files remain replaceable on Windows even when the destination
    # is read-only. ``mode`` describes the temporary inode while
    # ``target_mode`` is applied immediately before its final replacement.
    mode: int
    target_mode: int
    sha256: str


@dataclass(frozen=True)
class ArchitectureFeatures:
    room_count: int = 0
    has_views: bool = False
    has_multiple_visible_views: bool = False
    has_instance_layers: bool = False
    has_tile_layers: bool = False
    has_background_layers: bool = False
    has_scrolling_or_tiled_backgrounds: bool = False
    has_effect_layers: bool = False
    has_physics_world: bool = False
    has_draw_code: bool = False
    has_surface_code: bool = False
    has_collision_code: bool = False
    has_precise_collision_request: bool = False
    has_audio_code: bool = False
    has_sound_assets: bool = False
    has_network_code: bool = False
    has_buffer_file_code: bool = False

    def to_dict(self) -> JsonDict:
        return {
            "room_count": self.room_count,
            "has_views": self.has_views,
            "has_multiple_visible_views": self.has_multiple_visible_views,
            "has_instance_layers": self.has_instance_layers,
            "has_tile_layers": self.has_tile_layers,
            "has_background_layers": self.has_background_layers,
            "has_scrolling_or_tiled_backgrounds": self.has_scrolling_or_tiled_backgrounds,
            "has_effect_layers": self.has_effect_layers,
            "has_physics_world": self.has_physics_world,
            "has_draw_code": self.has_draw_code,
            "has_surface_code": self.has_surface_code,
            "has_collision_code": self.has_collision_code,
            "has_precise_collision_request": self.has_precise_collision_request,
            "has_audio_code": self.has_audio_code,
            "has_sound_assets": self.has_sound_assets,
            "has_network_code": self.has_network_code,
            "has_buffer_file_code": self.has_buffer_file_code,
        }


def write_architecture_policy_report(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> str:
    """Atomically publish the architecture-policy report and return its path."""
    return publish_architecture_policy_report(
        gm_project_path,
        godot_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
    ).path


def publish_architecture_policy_report(
    gm_project_path: str,
    godot_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> ArchitecturePolicyPublicationReceipt:
    """Atomically publish a report and return its exact committed receipt."""
    report = build_architecture_policy_report(
        gm_project_path,
        target_platform=target_platform,
        enabled_converters=enabled_converters,
    )
    content = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path = os.path.join(godot_project_path, ARCHITECTURE_POLICY_RELATIVE_PATH)
    artifact_directory, initial_root_identity, initial_directory_identity = (
        _inspect_policy_directory(godot_project_path)
    )
    initial_state = (
        _policy_target_state(report_path)
        if initial_directory_identity is not None
        else _PolicyTargetState(fingerprint=None, mode=None)
    )
    prepared_directory, root_identity, directory_identity = _prepare_policy_directory(
        godot_project_path
    )
    if (
        prepared_directory != artifact_directory
        or root_identity != initial_root_identity
        or (
            initial_directory_identity is not None
            and directory_identity != initial_directory_identity
        )
    ):
        raise OSError("Architecture-policy report directory changed before publication.")
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _verify_policy_target_state(report_path, initial_state)
    return _publish_policy_content(
        report_path,
        content,
        initial_state,
        godot_project_path=godot_project_path,
        root_identity=root_identity,
        artifact_directory=artifact_directory,
        directory_identity=directory_identity,
    )


def capture_architecture_policy_snapshot(
    godot_project_path: str,
) -> ArchitecturePolicySnapshot:
    """Capture exact report bytes, mode, and fingerprint without following links."""
    report_path = os.path.join(godot_project_path, ARCHITECTURE_POLICY_RELATIVE_PATH)
    artifact_directory, root_identity, directory_identity = _inspect_policy_directory(
        godot_project_path
    )
    if directory_identity is None:
        _verify_directory_path(
            godot_project_path,
            root_identity,
            description="architecture-policy report root",
        )
        return ArchitecturePolicySnapshot(
            content=None,
            mode=None,
            fingerprint=None,
            sha256=None,
        )
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    state = _policy_target_state(report_path)
    if state.fingerprint is None:
        _verify_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_policy_target_state(report_path, state)
        return ArchitecturePolicySnapshot(
            content=None,
            mode=None,
            fingerprint=None,
            sha256=None,
        )
    content = _read_policy_target_bytes(report_path, state)
    return ArchitecturePolicySnapshot(
        content=content,
        mode=state.mode,
        fingerprint=state.fingerprint,
        sha256=_sha256_bytes(content),
    )


def restore_architecture_policy_snapshot(
    godot_project_path: str,
    snapshot: ArchitecturePolicySnapshot,
    receipt: ArchitecturePolicyPublicationReceipt,
) -> str:
    """Restore a snapshot only while the report still exactly matches receipt."""
    _validate_policy_snapshot(snapshot)
    report_path = os.path.join(godot_project_path, ARCHITECTURE_POLICY_RELATIVE_PATH)
    if os.path.abspath(receipt.path) != os.path.abspath(report_path):
        raise ValueError("Architecture-policy publication receipt belongs to another path.")
    artifact_directory, root_identity, directory_identity = _inspect_policy_directory(
        godot_project_path
    )
    if directory_identity is None:
        raise OSError("Architecture-policy report directory disappeared before restore.")
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _verify_policy_receipt(receipt)

    restored_stage: _StagedPolicyFile | None = None
    receipt_backup = _stage_policy_bytes(
        report_path,
        receipt.content,
        mode=receipt.mode,
        suffix=".restore.backup",
    )
    temporary_files: dict[str, _StagedPolicyFile] = {
        receipt_backup.path: receipt_backup,
    }
    try:
        if snapshot.present:
            assert snapshot.content is not None
            assert snapshot.mode is not None
            restored_stage = _stage_policy_bytes(
                report_path,
                snapshot.content,
                mode=snapshot.mode,
                suffix=".restore.tmp",
            )
            temporary_files[restored_stage.path] = restored_stage
    except BaseException as error:
        cleanup_errors = _cleanup_policy_temporary_files(
            temporary_files,
            godot_project_path=godot_project_path,
            root_identity=root_identity,
            artifact_directory=artifact_directory,
            directory_identity=directory_identity,
        )
        if cleanup_errors:
            error.add_note(
                "Architecture-policy restore preparation cleanup failed: "
                + "; ".join(str(cleanup_error) for cleanup_error in cleanup_errors)
            )
        raise

    displaced_receipt = _receipt_as_staged_file(
        receipt,
        path=receipt_backup.path,
        storage_mode=receipt_backup.mode,
    )
    mutation_completed = False
    active_error: BaseException | None = None
    try:
        _verify_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_policy_receipt(receipt)
        try:
            _replace_published_receipt_with_backup(
                receipt,
                receipt_backup,
                displaced_receipt,
            )
            receipt_backup = displaced_receipt
            temporary_files[receipt_backup.path] = receipt_backup
            mutation_completed = True
        except BaseException:
            if _policy_path_matches_stage(
                displaced_receipt.path,
                displaced_receipt,
            ):
                receipt_backup = displaced_receipt
                temporary_files[receipt_backup.path] = receipt_backup
                mutation_completed = True
            raise
        if restored_stage is not None:
            mutation_completed = _replace_staged_policy_file(
                restored_stage,
                report_path,
            )
            if mutation_completed:
                temporary_files.pop(restored_stage.path, None)
        _fsync_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_restored_snapshot(report_path, snapshot, restored_stage)
    except BaseException as error:
        active_error = error
        if (
            not mutation_completed
            and restored_stage is not None
            and _policy_path_matches_stage(report_path, restored_stage)
        ):
            mutation_completed = True
            temporary_files.pop(restored_stage.path, None)
        if mutation_completed:
            rollback_error = _rollback_restore(
                report_path,
                snapshot,
                restored_stage,
                receipt_backup,
                receipt,
                temporary_files,
                godot_project_path=godot_project_path,
                root_identity=root_identity,
                artifact_directory=artifact_directory,
                directory_identity=directory_identity,
            )
            if rollback_error is not None:
                error.add_note(
                    "Architecture-policy snapshot restore rollback also failed: "
                    f"{rollback_error}"
                )
        raise
    finally:
        cleanup_errors = _cleanup_policy_temporary_files(
            temporary_files,
            godot_project_path=godot_project_path,
            root_identity=root_identity,
            artifact_directory=artifact_directory,
            directory_identity=directory_identity,
        )
        if active_error is not None and cleanup_errors:
            active_error.add_note(
                "Architecture-policy restore cleanup failed: "
                + "; ".join(str(error) for error in cleanup_errors)
            )

    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _verify_restored_snapshot(report_path, snapshot, restored_stage)
    return report_path


def _publish_policy_content(
    report_path: str,
    content: bytes,
    initial_state: _PolicyTargetState,
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> ArchitecturePolicyPublicationReceipt:
    staged = _stage_policy_bytes(
        report_path,
        content,
        mode=initial_state.mode,
        suffix=".tmp",
    )
    temporary_files: dict[str, _StagedPolicyFile] = {staged.path: staged}
    backup: _StagedPolicyFile | None = None
    publication_completed = False
    active_error: BaseException | None = None
    try:
        backup = _stage_existing_policy_file(report_path, initial_state)
        if backup is not None:
            temporary_files[backup.path] = backup
        _verify_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_policy_target_state(report_path, initial_state)
        try:
            _replace_staged_policy_file(staged, report_path)
            publication_completed = True
            temporary_files.pop(staged.path, None)
        except BaseException:
            if _policy_path_matches_stage(report_path, staged):
                publication_completed = True
                temporary_files.pop(staged.path, None)
            raise
        _fsync_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_staged_policy_file(staged, path=report_path)
    except BaseException as error:
        active_error = error
        if publication_completed:
            rollback_error = _rollback_policy_publication(
                report_path,
                staged,
                backup,
                temporary_files,
                godot_project_path=godot_project_path,
                root_identity=root_identity,
                artifact_directory=artifact_directory,
                directory_identity=directory_identity,
            )
            if rollback_error is not None:
                error.add_note(
                    "Architecture-policy report rollback also failed: "
                    f"{rollback_error}"
                )
        raise
    finally:
        cleanup_errors = _cleanup_policy_temporary_files(
            temporary_files,
            godot_project_path=godot_project_path,
            root_identity=root_identity,
            artifact_directory=artifact_directory,
            directory_identity=directory_identity,
        )
        if active_error is not None and cleanup_errors:
            active_error.add_note(
                "Architecture-policy report cleanup failed: "
                + "; ".join(str(error) for error in cleanup_errors)
            )

    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _verify_staged_policy_file(staged, path=report_path)
    report_stat = os.lstat(report_path)
    receipt = ArchitecturePolicyPublicationReceipt(
        path=report_path,
        content=content,
        mode=stat.S_IMODE(report_stat.st_mode),
        fingerprint=_receipt_fingerprint(report_stat),
        sha256=staged.sha256,
    )
    _verify_policy_receipt(receipt)
    return receipt


def _rollback_policy_publication(
    report_path: str,
    published: _StagedPolicyFile,
    backup: _StagedPolicyFile | None,
    temporary_files: dict[str, _StagedPolicyFile],
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> Exception | None:
    recovery: _StagedPolicyFile | None = None
    try:
        _verify_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_staged_policy_file(published, path=report_path)
        if backup is None:
            _unlink_finalized_policy_file(published, report_path)
        else:
            recovery = _stage_policy_bytes(
                report_path,
                backup.content,
                mode=backup.mode,
                suffix=".recovery.backup",
            )
            temporary_files[recovery.path] = recovery
            _replace_staged_policy_file(backup, report_path)
            temporary_files.pop(backup.path, None)
        _fsync_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        if backup is None:
            if os.path.lexists(report_path):
                raise OSError(
                    "Removed architecture-policy report reappeared during rollback."
                )
        else:
            _verify_staged_policy_file(backup, path=report_path)
        if recovery is not None:
            cleanup_error = _unlink_staged_policy_file(recovery)
            if cleanup_error is None:
                temporary_files.pop(recovery.path, None)
                _fsync_policy_directory(
                    godot_project_path,
                    root_identity,
                    artifact_directory,
                    directory_identity,
                )
                assert backup is not None
                _verify_staged_policy_file(backup, path=report_path)
        return None
    except Exception as error:
        recovery_path = _retain_policy_recovery(recovery, backup, temporary_files)
        if recovery_path is None:
            return error
        wrapped = OSError(
            f"{error}; previous architecture-policy report preserved at: "
            f"{recovery_path}"
        )
        wrapped.__cause__ = error
        return wrapped


def _rollback_restore(
    report_path: str,
    snapshot: ArchitecturePolicySnapshot,
    restored_stage: _StagedPolicyFile | None,
    receipt_backup: _StagedPolicyFile,
    receipt: ArchitecturePolicyPublicationReceipt,
    temporary_files: dict[str, _StagedPolicyFile],
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> Exception | None:
    recovery: _StagedPolicyFile | None = None
    try:
        _verify_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_restore_rollback_target(report_path, snapshot, restored_stage)
        recovery = _stage_policy_bytes(
            report_path,
            receipt_backup.content,
            mode=receipt_backup.mode,
            suffix=".recovery.backup",
        )
        temporary_files[recovery.path] = recovery
        _replace_staged_policy_file(receipt_backup, report_path)
        temporary_files.pop(receipt_backup.path, None)
        _fsync_policy_directory(
            godot_project_path,
            root_identity,
            artifact_directory,
            directory_identity,
        )
        _verify_policy_receipt(receipt)
        cleanup_error = _unlink_staged_policy_file(recovery)
        if cleanup_error is None:
            temporary_files.pop(recovery.path, None)
            _fsync_policy_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            _verify_policy_receipt(receipt)
        return None
    except Exception as error:
        recovery_path = _retain_policy_recovery(
            recovery,
            receipt_backup,
            temporary_files,
        )
        if recovery_path is None:
            return error
        wrapped = OSError(
            f"{error}; published architecture-policy report preserved at: "
            f"{recovery_path}"
        )
        wrapped.__cause__ = error
        return wrapped


def _retain_policy_recovery(
    recovery: _StagedPolicyFile | None,
    backup: _StagedPolicyFile | None,
    temporary_files: dict[str, _StagedPolicyFile],
) -> str | None:
    for candidate in (recovery, backup):
        if candidate is None:
            continue
        try:
            _verify_staged_policy_file(candidate)
        except OSError:
            continue
        temporary_files.pop(candidate.path, None)
        return candidate.path
    return None


def _inspect_policy_directory(
    godot_project_path: str,
) -> tuple[str, PathIdentity, PathIdentity | None]:
    try:
        root_stat = os.lstat(godot_project_path)
    except OSError as error:
        raise OSError(
            f"Architecture-policy report root is unavailable: {godot_project_path}"
        ) from error
    if _path_is_redirected(godot_project_path, root_stat) or not stat.S_ISDIR(
        root_stat.st_mode
    ):
        raise OSError(
            "Refusing redirected or non-directory architecture-policy report root: "
            f"{godot_project_path}"
        )
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    artifact_directory = os.path.join(
        godot_project_path,
        os.path.dirname(ARCHITECTURE_POLICY_RELATIVE_PATH),
    )
    try:
        directory_stat = os.lstat(artifact_directory)
    except FileNotFoundError:
        return artifact_directory, root_identity, None
    if _path_is_redirected(artifact_directory, directory_stat) or not stat.S_ISDIR(
        directory_stat.st_mode
    ):
        raise OSError(
            "Refusing redirected or non-directory architecture-policy report "
            f"directory: {artifact_directory}"
        )
    directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    return artifact_directory, root_identity, directory_identity


def _prepare_policy_directory(
    godot_project_path: str,
) -> tuple[str, PathIdentity, PathIdentity]:
    artifact_directory, root_identity, directory_identity = _inspect_policy_directory(
        godot_project_path
    )
    if directory_identity is None:
        _verify_directory_path(
            godot_project_path,
            root_identity,
            description="architecture-policy report root",
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
                "Refusing redirected or non-directory architecture-policy report "
                f"directory: {artifact_directory}"
            )
        directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    # Repeat the parent-directory durability barrier even when the managed
    # directory already exists. A previous creation may have succeeded before
    # its root fsync failed; a retry must not mistake that still-visible entry
    # for one whose creation was durably committed.
    _fsync_verified_directory(
        godot_project_path,
        root_identity,
        description="architecture-policy report root",
    )
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    return artifact_directory, root_identity, directory_identity


def _verify_policy_directory(
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> None:
    _verify_directory_path(
        godot_project_path,
        root_identity,
        description="architecture-policy report root",
    )
    _verify_directory_path(
        artifact_directory,
        directory_identity,
        description="architecture-policy report directory",
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


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _policy_mode_is_writable(mode: int) -> bool:
    return bool(mode & stat.S_IWUSR)


def _policy_modes_match(actual: int, expected: int) -> bool:
    if _is_windows_platform():
        # Windows chmod exposes only the read-only attribute. Group/other and
        # execute bits may be normalized by the filesystem and cannot be
        # preserved independently.
        return _policy_mode_is_writable(actual) == _policy_mode_is_writable(
            expected
        )
    return actual == expected


def _policy_fingerprints_match(
    actual: FileFingerprint,
    expected: FileFingerprint,
) -> bool:
    if _is_windows_platform():
        # Windows path-stat and open-handle implementations can expose
        # different st_ctime values for the same file. Keep the stable
        # identity, size, and mtime guards. Callers use this only for
        # descriptor parity or exact-content/SHA-backed staged files;
        # path-to-path transaction guards remain exact.
        return actual[:4] == expected[:4]
    return actual == expected


def _replaceable_policy_mode(mode: int) -> int:
    if not _is_windows_platform():
        return mode
    return mode | stat.S_IWUSR


def _set_policy_path_mode(
    path: str,
    expected_identity: PathIdentity,
    mode: int,
) -> int:
    """Set a mode without following a changed or redirected path."""
    _verify_regular_path_identity(path, expected_identity)
    current_mode = stat.S_IMODE(os.lstat(path).st_mode)
    if not _policy_modes_match(current_mode, mode):
        os.chmod(path, mode)
        _verify_regular_path_identity(path, expected_identity)
        current_mode = stat.S_IMODE(os.lstat(path).st_mode)
    if not _policy_modes_match(current_mode, mode):
        raise OSError(f"Architecture-policy report mode did not update: {path}")
    return current_mode


def _make_policy_target_replaceable(
    path: str,
) -> _PolicyReplaceTarget | None:
    """Clear a Windows read-only destination after capturing its identity."""
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(
            f"Refusing redirected or non-regular architecture-policy report: {path}"
        )
    identity = (path_stat.st_dev, path_stat.st_ino)
    mode = stat.S_IMODE(path_stat.st_mode)
    mode_changed = _is_windows_platform() and not _policy_mode_is_writable(mode)
    if mode_changed:
        _set_policy_path_mode(path, identity, _replaceable_policy_mode(mode))
    return _PolicyReplaceTarget(
        identity=identity,
        mode=mode,
        mode_changed=mode_changed,
    )


def _restore_replace_target_mode(
    path: str,
    target: _PolicyReplaceTarget | None,
    error: BaseException,
) -> None:
    if target is None or not target.mode_changed:
        return
    try:
        _set_policy_path_mode(path, target.identity, target.mode)
    except Exception as mode_error:
        error.add_note(
            "Failed to restore the replaced architecture-policy target mode: "
            f"{mode_error}"
        )


def _policy_target_state(path: str) -> _PolicyTargetState:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return _PolicyTargetState(fingerprint=None, mode=None)
    if _path_is_redirected(path, path_stat) or not stat.S_ISREG(path_stat.st_mode):
        raise OSError(
            f"Refusing redirected or non-regular architecture-policy report: {path}"
        )
    return _PolicyTargetState(
        fingerprint=_file_fingerprint(path_stat),
        mode=stat.S_IMODE(path_stat.st_mode),
    )


def _verify_policy_target_state(path: str, expected: _PolicyTargetState) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if expected.fingerprint is None:
            return
        raise OSError(f"Architecture-policy report disappeared: {path}")
    if (
        expected.fingerprint is None
        or _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or _file_fingerprint(path_stat) != expected.fingerprint
        or expected.mode is None
        or not _policy_modes_match(
            stat.S_IMODE(path_stat.st_mode),
            expected.mode,
        )
    ):
        raise OSError(f"Architecture-policy report changed: {path}")


def _read_policy_target_bytes(path: str, expected: _PolicyTargetState) -> bytes:
    if expected.fingerprint is None:
        raise ValueError("Cannot read an absent architecture-policy report.")
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, open_flags)
    try:
        opened_before = os.fstat(file_descriptor)
        path_before = os.lstat(path)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or not _policy_fingerprints_match(
                _file_fingerprint(opened_before),
                expected.fingerprint,
            )
            or _file_fingerprint(path_before) != expected.fingerprint
        ):
            raise OSError(f"Architecture-policy report changed while reading: {path}")
        with os.fdopen(file_descriptor, "rb") as report_file:
            file_descriptor = -1
            content = report_file.read()
            opened_after = os.fstat(report_file.fileno())
        if not _policy_fingerprints_match(
            _file_fingerprint(opened_after),
            expected.fingerprint,
        ):
            raise OSError(f"Architecture-policy report changed while reading: {path}")
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_policy_target_state(path, expected)
    return content


def _stage_existing_policy_file(
    path: str,
    expected: _PolicyTargetState,
) -> _StagedPolicyFile | None:
    if expected.fingerprint is None:
        return None
    content = _read_policy_target_bytes(path, expected)
    _verify_policy_target_state(path, expected)
    return _stage_policy_bytes(
        path,
        content,
        mode=expected.mode,
        suffix=".backup",
    )


def _stage_policy_bytes(
    path: str,
    content: bytes,
    *,
    mode: int | None,
    suffix: str,
) -> _StagedPolicyFile:
    artifact_directory = os.path.dirname(path) or os.curdir
    file_descriptor, staged_path = tempfile.mkstemp(
        dir=artifact_directory,
        prefix=f".{os.path.basename(path)}.",
        suffix=suffix,
    )
    initial_stat = os.fstat(file_descriptor)
    identity = (initial_stat.st_dev, initial_stat.st_ino)
    target_mode = stat.S_IMODE(initial_stat.st_mode) if mode is None else mode
    staging_mode = _replaceable_policy_mode(target_mode)
    try:
        with os.fdopen(file_descriptor, "wb") as staged_file:
            file_descriptor = -1
            staged_file.write(content)
            staged_file.flush()
            if not _policy_modes_match(
                stat.S_IMODE(os.fstat(staged_file.fileno()).st_mode),
                staging_mode,
            ):
                fchmod_candidate: object = getattr(os, "fchmod", None)
                if callable(fchmod_candidate):
                    fchmod = cast(Callable[[int, int], None], fchmod_candidate)
                    fchmod(staged_file.fileno(), staging_mode)
                else:
                    _verify_regular_path_identity(staged_path, identity)
                    os.chmod(staged_path, staging_mode)
                    _verify_regular_path_identity(staged_path, identity)
            os.fsync(staged_file.fileno())
        staged_stat = os.lstat(staged_path)
        staged_mode = stat.S_IMODE(staged_stat.st_mode)
        if not _policy_modes_match(staged_mode, staging_mode):
            raise OSError(
                f"Staged architecture-policy report mode changed: {staged_path}"
            )
        staged = _StagedPolicyFile(
            path=staged_path,
            identity=identity,
            content=content,
            mode=staged_mode,
            target_mode=target_mode,
            sha256=_sha256_bytes(content),
        )
        _verify_staged_policy_file(staged)
        return staged
    except BaseException as error:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        cleanup_error = _unlink_if_identity(staged_path, identity)
        if cleanup_error is not None:
            error.add_note(
                "Failed to remove incomplete architecture-policy report stage "
                f"{staged_path}: {cleanup_error}"
            )
        raise


def _read_staged_policy_file(
    staged: _StagedPolicyFile,
    *,
    path: str | None = None,
    verify_mode: bool = True,
) -> bytes:
    selected_path = staged.path if path is None else path
    expected_mode = (
        staged.mode
        if os.path.abspath(selected_path) == os.path.abspath(staged.path)
        else staged.target_mode
    )
    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(selected_path, open_flags)
    try:
        opened_before = os.fstat(file_descriptor)
        fingerprint_before = _file_fingerprint(opened_before)
        if (
            not stat.S_ISREG(opened_before.st_mode)
            or (opened_before.st_dev, opened_before.st_ino) != staged.identity
            or (
                verify_mode
                and not _policy_modes_match(
                    stat.S_IMODE(opened_before.st_mode),
                    expected_mode,
                )
            )
        ):
            raise OSError(f"Staged architecture-policy report changed: {selected_path}")
        with os.fdopen(file_descriptor, "rb") as staged_file:
            file_descriptor = -1
            content = staged_file.read()
            opened_after = os.fstat(staged_file.fileno())
        path_after = os.lstat(selected_path)
        if (
            not stat.S_ISREG(opened_after.st_mode)
            or (opened_after.st_dev, opened_after.st_ino) != staged.identity
            or (
                verify_mode
                and not _policy_modes_match(
                    stat.S_IMODE(opened_after.st_mode),
                    expected_mode,
                )
            )
            or (
                verify_mode
                and not _policy_modes_match(
                    stat.S_IMODE(path_after.st_mode),
                    expected_mode,
                )
            )
            or not _policy_fingerprints_match(
                _file_fingerprint(opened_after),
                fingerprint_before,
            )
            or not _policy_fingerprints_match(
                _file_fingerprint(path_after),
                fingerprint_before,
            )
            or content != staged.content
            or _sha256_bytes(content) != staged.sha256
        ):
            raise OSError(
                f"Staged architecture-policy report content changed: {selected_path}"
            )
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    _verify_regular_path_identity(selected_path, staged.identity)
    return content


def _verify_staged_policy_file(
    staged: _StagedPolicyFile,
    *,
    path: str | None = None,
) -> None:
    _read_staged_policy_file(staged, path=path)


def _replace_staged_policy_file(
    staged: _StagedPolicyFile,
    target_path: str,
) -> bool:
    _verify_staged_policy_file(staged)
    target_state = _make_policy_target_replaceable(target_path)
    try:
        # Keep temporary files writable until the last possible moment. On
        # Windows a read-only destination blocks replacement, while applying
        # the desired attribute to the source before the rename makes the
        # final mode part of the same visible transition.
        _set_policy_path_mode(staged.path, staged.identity, staged.target_mode)
        os.replace(staged.path, target_path)
    except BaseException as error:
        if not _policy_path_matches_stage(target_path, staged):
            try:
                _set_policy_path_mode(staged.path, staged.identity, staged.mode)
            except Exception as mode_error:
                error.add_note(
                    "Failed to restore the replaceable architecture-policy "
                    f"stage mode: {mode_error}"
                )
            _restore_replace_target_mode(target_path, target_state, error)
        raise
    _verify_staged_policy_file(staged, path=target_path)
    return True


def _policy_path_matches_stage(path: str, staged: _StagedPolicyFile) -> bool:
    try:
        _read_staged_policy_file(staged, path=path, verify_mode=False)
    except OSError:
        return False
    return True


def _receipt_as_staged_file(
    receipt: ArchitecturePolicyPublicationReceipt,
    *,
    path: str,
    storage_mode: int,
) -> _StagedPolicyFile:
    return _StagedPolicyFile(
        path=path,
        identity=(receipt.fingerprint[0], receipt.fingerprint[1]),
        content=receipt.content,
        mode=storage_mode,
        target_mode=receipt.mode,
        sha256=receipt.sha256,
    )


def _replace_published_receipt_with_backup(
    receipt: ArchitecturePolicyPublicationReceipt,
    staged_copy: _StagedPolicyFile,
    displaced_receipt: _StagedPolicyFile,
) -> None:
    """Park the published inode at the prepared backup path before restore."""
    _verify_policy_receipt(receipt)
    _verify_staged_policy_file(staged_copy)
    target_state = _make_policy_target_replaceable(receipt.path)
    try:
        os.replace(receipt.path, staged_copy.path)
    except BaseException as error:
        if not _policy_path_matches_stage(
            displaced_receipt.path,
            displaced_receipt,
        ):
            _restore_replace_target_mode(receipt.path, target_state, error)
        raise
    _verify_staged_policy_file(displaced_receipt)


def _unlink_finalized_policy_file(
    staged: _StagedPolicyFile,
    path: str,
) -> None:
    """Remove a finalized file without leaving a failed target writable."""
    _verify_staged_policy_file(staged, path=path)
    target_state = _make_policy_target_replaceable(path)
    try:
        os.unlink(path)
    except BaseException as error:
        if not os.path.lexists(path):
            return
        _restore_replace_target_mode(path, target_state, error)
        raise
    if os.path.lexists(path):
        error = OSError(f"Architecture-policy report remained after unlink: {path}")
        _restore_replace_target_mode(path, target_state, error)
        raise error


def _verify_policy_receipt(receipt: ArchitecturePolicyPublicationReceipt) -> None:
    state = _policy_target_state(receipt.path)
    if (
        state.fingerprint is None
        or _stable_fingerprint(state.fingerprint) != receipt.fingerprint
        or state.mode is None
        or not _policy_modes_match(state.mode, receipt.mode)
        or _sha256_bytes(receipt.content) != receipt.sha256
    ):
        raise OSError(
            "Architecture-policy report no longer matches its publication receipt: "
            f"{receipt.path}"
        )
    content = _read_policy_target_bytes(receipt.path, state)
    if content != receipt.content or _sha256_bytes(content) != receipt.sha256:
        raise OSError(
            "Architecture-policy report no longer matches its publication receipt: "
            f"{receipt.path}"
        )


def _validate_policy_snapshot(snapshot: ArchitecturePolicySnapshot) -> None:
    if snapshot.present:
        if (
            snapshot.content is None
            or snapshot.mode is None
            or snapshot.sha256 is None
        ):
            raise ValueError("A present architecture-policy snapshot is incomplete.")
        assert snapshot.fingerprint is not None
        if (
            len(snapshot.content) != snapshot.fingerprint[2]
            or _sha256_bytes(snapshot.content) != snapshot.sha256
        ):
            raise ValueError(
                "Architecture-policy snapshot content does not match its fingerprint."
            )
        return
    if (
        snapshot.content is not None
        or snapshot.mode is not None
        or snapshot.sha256 is not None
    ):
        raise ValueError("An absent architecture-policy snapshot cannot contain file data.")


def _verify_restored_snapshot(
    report_path: str,
    snapshot: ArchitecturePolicySnapshot,
    restored_stage: _StagedPolicyFile | None,
) -> None:
    if not snapshot.present:
        if os.path.lexists(report_path):
            raise OSError(
                f"Architecture-policy report should have been absent: {report_path}"
            )
        return
    if restored_stage is None:
        raise ValueError("A present snapshot requires a staged restore artifact.")
    _verify_staged_policy_file(restored_stage, path=report_path)


def _verify_restore_rollback_target(
    report_path: str,
    snapshot: ArchitecturePolicySnapshot,
    restored_stage: _StagedPolicyFile | None,
) -> None:
    if not os.path.lexists(report_path):
        return
    _verify_restored_snapshot(report_path, snapshot, restored_stage)


def _cleanup_policy_temporary_files(
    temporary_files: dict[str, _StagedPolicyFile],
    *,
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> list[Exception]:
    errors: list[Exception] = []
    removed = False
    for temporary_path, staged in tuple(temporary_files.items()):
        try:
            _verify_policy_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
            if not os.path.lexists(temporary_path):
                temporary_files.pop(temporary_path, None)
                continue
            _verify_staged_policy_file(staged)
            os.unlink(temporary_path)
            temporary_files.pop(temporary_path, None)
            removed = True
        except Exception as error:
            errors.append(error)
    if removed:
        try:
            _fsync_policy_directory(
                godot_project_path,
                root_identity,
                artifact_directory,
                directory_identity,
            )
        except Exception as error:
            errors.append(error)
    return errors


def _unlink_staged_policy_file(staged: _StagedPolicyFile) -> Exception | None:
    try:
        _verify_staged_policy_file(staged)
        os.unlink(staged.path)
    except Exception as error:
        return error
    return None


def _unlink_if_identity(path: str, expected_identity: PathIdentity) -> Exception | None:
    try:
        _verify_regular_path_identity(path, expected_identity)
        os.unlink(path)
    except Exception as error:
        return error
    return None


def _verify_regular_path_identity(path: str, expected_identity: PathIdentity) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise OSError(f"Staged architecture-policy report changed: {path}") from error
    if (
        _path_is_redirected(path, path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino) != expected_identity
    ):
        raise OSError(f"Staged architecture-policy report changed: {path}")


def _fsync_verified_directory(
    path: str,
    expected_identity: PathIdentity,
    *,
    description: str,
) -> None:
    _verify_directory_path(path, expected_identity, description=description)
    if os.name == "nt":
        return
    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
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
    _verify_directory_path(path, expected_identity, description=description)


def _fsync_policy_directory(
    godot_project_path: str,
    root_identity: PathIdentity,
    artifact_directory: str,
    directory_identity: PathIdentity,
) -> None:
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )
    _fsync_verified_directory(
        artifact_directory,
        directory_identity,
        description="architecture-policy report directory",
    )
    _verify_policy_directory(
        godot_project_path,
        root_identity,
        artifact_directory,
        directory_identity,
    )


def _file_fingerprint(path_stat: os.stat_result) -> FileFingerprint:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _receipt_fingerprint(path_stat: os.stat_result) -> ReceiptFingerprint:
    return _stable_fingerprint(_file_fingerprint(path_stat))


def _stable_fingerprint(fingerprint: FileFingerprint) -> ReceiptFingerprint:
    # Moving the same inode aside and back updates ctime on POSIX filesystems.
    # Receipts therefore treat ctime as a concurrency hint rather than identity;
    # verification still requires the exact device, inode, size, mtime, mode,
    # bytes, and SHA-256 digest published by this receipt.
    return fingerprint[:4]


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def build_architecture_policy_report(
    gm_project_path: str,
    *,
    target_platform: str,
    enabled_converters: Iterable[str],
) -> JsonDict:
    features = inspect_architecture_features(gm_project_path)
    return {
        "format_version": ARCHITECTURE_POLICY_VERSION,
        "target_platform": target_platform,
        "enabled_converters": sorted(set(enabled_converters)),
        "documentation_sources": GODOT_ARCHITECTURE_SOURCES,
        "project_features": features.to_dict(),
        "room_root": room_root_policy(),
        "layer_hierarchy": layer_hierarchy_policy(),
        "renderer": renderer_backend_policy(features),
        "collision": collision_backend_policy(features),
        "audio": audio_backend_policy(features),
        "file_buffer_network": file_buffer_network_policy(features),
        "runtime_managers": runtime_manager_policy(),
        "signal_queue_policy": signal_queue_policy(),
    }


def inspect_architecture_features(gm_project_path: str) -> ArchitectureFeatures:
    index = GameMakerResourceIndex(
        gm_project_path,
        "",
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        conversion_running=lambda: True,
    ).build()
    rooms = index.ordered_rooms()
    script_text = _read_gml_sources(gm_project_path)

    return ArchitectureFeatures(
        room_count=len(rooms),
        has_views=any(_room_has_visible_views(room) for room in rooms),
        has_multiple_visible_views=any(_room_visible_view_count(room) > 1 for room in rooms),
        has_instance_layers=any(_room_has_layer(room, "GMRInstanceLayer") for room in rooms),
        has_tile_layers=any(_room_has_layer(room, "GMRTileLayer") for room in rooms),
        has_background_layers=any(_room_has_layer(room, "GMRBackgroundLayer") for room in rooms),
        has_scrolling_or_tiled_backgrounds=any(_room_has_scrolling_background(room) for room in rooms),
        has_effect_layers=any(_room_has_layer(room, "GMREffectLayer") for room in rooms),
        has_physics_world=any(bool(room.physics_settings.get("PhysicsWorld", False)) for room in rooms),
        has_draw_code=_matches(script_text, _DRAW_RE),
        has_surface_code=_matches(script_text, _SURFACE_RE),
        has_collision_code=_matches(script_text, _COLLISION_RE),
        has_precise_collision_request=_matches(script_text, _PRECISE_COLLISION_RE),
        has_audio_code=_matches(script_text, _AUDIO_RE),
        has_sound_assets=bool(index.resources.get("sounds")),
        has_network_code=_matches(script_text, _NETWORK_RE),
        has_buffer_file_code=_matches(script_text, _BUFFER_FILE_RE),
    )


def room_root_policy() -> JsonDict:
    return {
        "id": ROOM_ROOT_POLICY_ID,
        "godot_node": "Node2D",
        "script": "res://gm2godot/gml_room_node.gd",
        "main_scene_source": "first GameMaker RoomOrderNodes entry",
        "gui_layer_policy": GUI_LAYER_POLICY_ID,
        "rationale": "Rooms need stable 2D transforms and a generated entry hook while GameMaker lifecycle dispatch stays in GMRuntime/GMEvents.",
    }


def layer_hierarchy_policy() -> JsonDict:
    return {
        "id": LAYER_HIERARCHY_POLICY_ID,
        "layer_node": "Node2D",
        "depth_mapping": DEPTH_MAPPING_POLICY_ID,
        "depth_expression": "Node2D.z_index = -GameMaker layer depth",
        "gui_layer": {
            "id": GUI_LAYER_POLICY_ID,
            "godot_node": "CanvasLayer",
            "name": "GMGUI",
            "layer": 1000,
        },
        "tilemap_node": "TileMapLayer",
        "rationale": "GameMaker lower depth draws later; Godot higher z_index draws later, so depth is inverted on generated layer nodes.",
    }


def renderer_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    if features.has_surface_code:
        mode = "surface_viewport"
        fidelity = "high"
        rationale = "Surface/application-surface APIs require a SubViewport/ViewportTexture-capable draw manager path."
    elif features.has_draw_code or features.has_effect_layers:
        mode = "central_canvas_draw_manager"
        fidelity = "medium"
        rationale = "Draw/shader/effect code needs ordered CanvasItem draw dispatch through GMDraw."
    else:
        mode = "godot_node_scene"
        fidelity = "medium"
        rationale = "Projects without explicit draw/surface usage can prefer generated Godot nodes and per-layer z ordering."
    return {
        "domain": "render",
        "mode": mode,
        "fidelity": fidelity,
        "manager": "GMDraw",
        "queue_redraw": features.has_draw_code or features.has_surface_code,
        "uses_canvas_layer_for_gui": True,
        "uses_subviewport_for_surfaces": features.has_surface_code,
        "rationale": rationale,
    }


def collision_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    if features.has_physics_world:
        mode = "godot_physics_world_bridge"
        rationale = "Rooms with GameMaker physics enabled are routed through Godot 2D physics primitives plus compatibility metadata."
    elif features.has_collision_code:
        mode = "generated_bounds_direct_queries"
        rationale = "Query-style collision APIs are evaluated against generated bounds in the GameMaker event scheduler."
    else:
        mode = "generated_bounds_idle"
        rationale = "No collision API usage was detected; generated bounds remain available for later instance APIs."
    return {
        "domain": "collision",
        "mode": mode,
        "manager": "GMEvents",
        "query_api": "generated bounds and direct runtime queries",
        "godot_native_signals": "queued through GMEvents when used",
        "precise_masks": "planned_custom_mask_backend" if features.has_precise_collision_request else "bounds_compatible",
        "rationale": rationale,
    }


def audio_backend_policy(features: ArchitectureFeatures) -> JsonDict:
    active = features.has_audio_code or features.has_sound_assets
    return {
        "domain": "audio",
        "mode": "pooled_audio_stream_players" if active else "runtime_audio_manager_idle",
        "manager": "GMAudio",
        "godot_nodes": ["AudioStreamPlayer", "AudioStreamPlayer2D"],
        "godot_server": "AudioServer",
        "async_callbacks": "queued through GMAsync",
        "rationale": "Sound handles, loop/gain/pitch state, audio groups, and playback-ended signals need GameMaker-compatible runtime state.",
    }


def file_buffer_network_policy(features: ArchitectureFeatures) -> JsonDict:
    network_mode = "gm_async_socket_wrappers" if features.has_network_code else "runtime_network_idle"
    return {
        "domain": "file_buffer_network",
        "file_access": "FileAccess/DirAccess with GM2Godot path mapping",
        "buffers": "PackedByteArray with explicit endian/alignment helpers",
        "http": "HTTPRequest/HTTPClient events queued through GMAsync",
        "network": network_mode,
        "network_primitives": ["StreamPeerTCP", "TCPServer", "PacketPeerUDP", "WebSocketPeer"],
        "godot_multiplayer_api": "not used as a direct replacement for GameMaker sockets",
        "has_file_or_buffer_code": features.has_buffer_file_code,
        "rationale": "GameMaker networking and async file APIs expose event payloads rather than Godot-native signal order.",
    }


def runtime_manager_policy() -> list[JsonDict]:
    return [
        {
            "name": definition.name,
            "domain": definition.domain,
            "order": definition.order,
            "dependencies": list(definition.dependencies),
            "state_keys": list(definition.state_keys),
            "queued_godot_signals": list(definition.queued_godot_signals),
        }
        for definition in runtime_manager_definitions()
    ]


def signal_queue_policy() -> list[JsonDict]:
    policies: list[JsonDict] = []
    for definition in runtime_manager_definitions():
        for signal_name in definition.queued_godot_signals:
            policies.append({
                "godot_signal": signal_name,
                "runtime_manager": definition.name,
                "domain": definition.domain,
                "queue": _queue_name_for_signal(signal_name, definition.name),
            })
    return policies


def room_root_metadata_lines() -> list[str]:
    return [
        f"metadata/gm2godot_architecture_policy_version = {ARCHITECTURE_POLICY_VERSION}",
        f"metadata/gm2godot_room_root_policy = {json.dumps(ROOM_ROOT_POLICY_ID)}",
        f"metadata/gm2godot_layer_hierarchy_policy = {json.dumps(LAYER_HIERARCHY_POLICY_ID)}",
        f"metadata/gm2godot_depth_mapping_policy = {json.dumps(DEPTH_MAPPING_POLICY_ID)}",
        f"metadata/gm2godot_gui_layer_policy = {json.dumps(GUI_LAYER_POLICY_ID)}",
    ]


def gui_canvas_layer_node_lines(parent_path: str = ".") -> list[str]:
    return [
        f'[node name="GMGUI" type="CanvasLayer" parent={json.dumps(parent_path)}]',
        "layer = 1000",
        f"metadata/gm2godot_gui_layer_policy = {json.dumps(GUI_LAYER_POLICY_ID)}",
        'metadata/gamemaker_layer_element_type = "draw_gui"',
        "metadata/gamemaker_event_queue = \"GMDraw\"",
        "",
    ]


def layer_policy_metadata_lines() -> list[str]:
    return [
        f"metadata/gm2godot_layer_policy = {json.dumps(LAYER_HIERARCHY_POLICY_ID)}",
        f"metadata/gm2godot_depth_mapping_policy = {json.dumps(DEPTH_MAPPING_POLICY_ID)}",
    ]


def _read_gml_sources(gm_project_path: str) -> str:
    chunks: list[str] = []
    for root, dirs, files in os.walk(gm_project_path):
        dirs[:] = sorted(dirs)
        for filename in sorted(files):
            if not filename.endswith(".gml"):
                continue
            path = os.path.join(root, filename)
            try:
                resolved = resolve_project_filesystem_source_path(
                    gm_project_path,
                    path,
                )
                with open(
                    resolved.filesystem_path,
                    "r",
                    encoding="utf-8",
                ) as source_file:
                    chunks.append(source_file.read())
            except (OSError, ProjectSourcePathError):
                continue
    return "\n".join(chunks)


def _matches(value: str, pattern: re.Pattern[str]) -> bool:
    return pattern.search(value) is not None


def _room_has_visible_views(room: IndexedRoom) -> bool:
    if not bool(room.view_settings.get("enableViews", False)):
        return False
    return _room_visible_view_count(room) > 0


def _room_visible_view_count(room: IndexedRoom) -> int:
    visible_count = 0
    for view in room.views:
        if not isinstance(view, dict):
            continue
        typed_view = cast(JsonDict, view)
        if bool(typed_view.get("visible", False)):
            visible_count += 1
    return visible_count


def _room_has_layer(room: IndexedRoom, resource_type: str) -> bool:
    return any(_layer_resource_type(layer) == resource_type for layer in _iter_layers(room.layers))


def _room_has_scrolling_background(room: IndexedRoom) -> bool:
    for layer in _iter_layers(room.layers):
        if _layer_resource_type(layer) != "GMRBackgroundLayer":
            continue
        if any(bool(layer.get(key, False)) for key in ("htiled", "vtiled", "stretch")):
            return True
        if _number(layer.get("hspeed")) != 0.0 or _number(layer.get("vspeed")) != 0.0:
            return True
    return False


def _iter_layers(layers: object) -> Iterable[JsonDict]:
    if not isinstance(layers, list):
        return
    for item in cast(list[object], layers):
        if not isinstance(item, dict):
            continue
        layer = cast(JsonDict, item)
        yield layer
        children = layer.get("layers") or layer.get("children")
        yield from _iter_layers(children)


def _layer_resource_type(layer: JsonDict) -> str:
    resource_type = layer.get("resourceType")
    if isinstance(resource_type, str) and resource_type:
        return resource_type
    for key in layer:
        if key.startswith("$GMR"):
            return key[1:]
    return "UnknownLayer"


def _number(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _queue_name_for_signal(signal_name: str, manager_name: str) -> str:
    if manager_name == "GMAsync":
        return "gml_async_enqueue_from_signal"
    if manager_name == "GMEvents":
        return "gml_event_scheduler_frame"
    return "manager_state_queue"
