"""Included Files file publication ownership."""

from __future__ import annotations
import hashlib
import os
import secrets
import stat
import tempfile
from typing import BinaryIO, Callable
from src.conversion.included_files_parts.models import IncludedPayloadReceipt as _IncludedPayloadReceipt, IncludedCopyReceipt as _IncludedCopyReceipt, IncludedNoOpSourceReceipt as _IncludedNoOpSourceReceipt
from src.conversion.included_files_parts import path_validation as _included_paths
from src.conversion.included_files_parts import stat_metadata as _included_metadata
from src.conversion.included_files_parts.native_filesystem import filesystem as _included_fs
from src.conversion.included_files_parts import source_snapshots as _included_snapshots

def _ensure_included_output_project_root(project_path: str) -> tuple[int, int]:
    os.makedirs(project_path, exist_ok=True)
    project_stat = os.lstat(project_path)
    if (
        _included_fs.output_path_is_redirected(project_path, project_stat)
        or not stat.S_ISDIR(project_stat.st_mode)
    ):
        raise OSError(
            f"Refusing redirected Included File output root: {project_path}"
        )
    return (project_stat.st_dev, project_stat.st_ino)


def _verify_open_included_output_directory(
    project_path: str,
    directory_path: str,
    directory_fd: int,
) -> None:
    try:
        path_stat = os.lstat(directory_path)
        open_stat = os.fstat(directory_fd)
    except OSError as error:
        raise OSError(
            f"Included File output directory changed: {directory_path}"
        ) from error
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_real = os.path.normcase(os.path.realpath(directory_path))
    try:
        contained = (
            os.path.commonpath((project_real, directory_real))
            == project_real
        )
    except ValueError:
        contained = False
    if (
        _included_fs.output_path_is_redirected(directory_path, path_stat)
        or not stat.S_ISDIR(path_stat.st_mode)
        or (path_stat.st_dev, path_stat.st_ino)
        != (open_stat.st_dev, open_stat.st_ino)
        or not contained
    ):
        raise OSError(
            f"Refusing redirected Included File output directory: {directory_path}"
        )


def _read_included_payload_chunk(source_file: BinaryIO) -> bytes:
    return source_file.read(1024 * 1024)


def _copy_included_payload(
    source_file: BinaryIO,
    target_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedPayloadReceipt:
    expected_fingerprint = _included_metadata.included_source_fingerprint(source_stat)
    if source_file.tell() != 0:
        raise OSError("GameMaker Included File source did not start at offset zero")
    before_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(before_copy.st_mode)
        or _included_metadata.included_source_fingerprint(before_copy) != expected_fingerprint
    ):
        raise OSError("GameMaker Included File source changed before copying")

    digest = hashlib.sha256()
    byte_count = 0
    while True:
        chunk = read_included_payload_chunk(source_file)
        if not chunk:
            break
        written = target_file.write(chunk)
        if written != len(chunk):
            raise OSError("Could not write the complete Included File payload")
        digest.update(chunk)
        byte_count += len(chunk)

    after_copy = os.fstat(source_file.fileno())
    if (
        not stat.S_ISREG(after_copy.st_mode)
        or _included_metadata.included_source_fingerprint(after_copy) != expected_fingerprint
        or byte_count != source_stat.st_size
    ):
        raise OSError("GameMaker Included File source changed while copying")
    streamed_sha256 = digest.hexdigest()
    if expected_receipt is not None:
        if (
            expected_receipt.byte_count != byte_count
            or expected_receipt.sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed after its "
                "planning receipt"
            )
    else:
        source_file.seek(0)
        verified_byte_count, verified_sha256 = _included_snapshots.digest_open_included_file(
            source_file
        )
        after_verification = os.fstat(source_file.fileno())
        if (
            _included_metadata.included_source_fingerprint(after_verification)
            != expected_fingerprint
            or verified_byte_count != byte_count
            or verified_sha256 != streamed_sha256
        ):
            raise OSError(
                "GameMaker Included File source payload changed while copying"
            )
    return _IncludedPayloadReceipt(
        source_fingerprint=expected_fingerprint,
        byte_count=byte_count,
        sha256=streamed_sha256,
    )


def _stage_included_output_at(
    directory_fd: int,
    filename: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    verify_directory: Callable[[], None],
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    verify_directory()
    output_identity = _included_metadata.included_output_state_at(directory_fd, filename)
    temporary_name = ""
    file_descriptor = -1
    for _attempt in range(100):
        temporary_name = f".gm2godot-{secrets.token_hex(8)}.tmp"
        try:
            file_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileExistsError:
            continue
    if file_descriptor < 0:
        raise OSError(f"Could not stage Included File output: {filename}")

    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    temporary_pending = True
    published_pending = False
    try:
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _included_fs.apply_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        staged_stat = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != temporary_identity
        ):
            raise OSError(f"Included File staging output changed: {filename}")
        verify_directory()
        _included_metadata.verify_included_output_state_at(
            directory_fd,
            filename,
            output_identity,
        )
        verify_directory()
        os.rename(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_pending = False
        published_pending = True
        published_stat = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(f"Included File output changed after publication: {filename}")
        verify_directory()
        published_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            opened_stat = os.fstat(published_fd)
            current_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_metadata.included_path_handle_binding(current_stat)
                != _included_metadata.included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {filename}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_metadata.included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_metadata.included_handle_state(opened_stat),
            )
        finally:
            os.close(published_fd)
        verify_directory()
        published_pending = False
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending and temporary_name:
            try:
                current_stat = os.stat(
                    temporary_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    current_stat.st_dev,
                    current_stat.st_ino,
                ) == temporary_identity:
                    os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        if published_pending:
            try:
                current_stat = os.stat(
                    filename,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISREG(current_stat.st_mode)
                    and (
                        current_stat.st_dev,
                        current_stat.st_ino,
                    )
                    == temporary_identity
                ):
                    os.unlink(filename, dir_fd=directory_fd)
            except OSError:
                pass


def _publish_included_output_at(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    project_fd = os.open(project_path, directory_flags)
    current_fd = project_fd
    try:
        verify_open_included_output_directory(
            project_path,
            project_path,
            project_fd,
        )
        for component in components[:-1]:
            child_fd = _included_fs.open_or_create_output_directory(
                current_fd,
                component,
                directory_flags,
            )
            if current_fd != project_fd:
                os.close(current_fd)
            current_fd = child_fd

        output_directory = os.path.join(project_path, *components[:-1])
        def verify_output_directory() -> None:
            verify_open_included_output_directory(
                project_path,
                output_directory,
                current_fd,
            )

        verify_output_directory()
        receipt = stage_included_output_at(
            current_fd,
            components[-1],
            source_file,
            source_stat,
            verify_output_directory,
            expected_receipt,
        )
        verify_output_directory()
        return receipt
    finally:
        if current_fd != project_fd:
            os.close(current_fd)
        os.close(project_fd)


def _prepare_included_output_directories_fallback(
    project_path: str,
    directory_components: tuple[str, ...],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    project_real = os.path.normcase(os.path.realpath(project_path))
    directory_path = project_path
    identities: list[tuple[str, tuple[int, int]]] = []
    for component in (None, *directory_components):
        if component is not None:
            directory_path = os.path.join(directory_path, component)
            try:
                directory_stat = os.lstat(directory_path)
            except FileNotFoundError:
                try:
                    os.mkdir(directory_path)
                except FileExistsError:
                    pass
                directory_stat = os.lstat(directory_path)
        else:
            directory_stat = os.lstat(directory_path)
        directory_real = os.path.normcase(os.path.realpath(directory_path))
        try:
            contained = (
                os.path.commonpath((project_real, directory_real))
                == project_real
            )
        except ValueError:
            contained = False
        if (
            _included_fs.output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or not contained
        ):
            raise OSError(
                "Refusing redirected Included File output directory: "
                f"{directory_path}"
            )
        identities.append(
            (
                directory_path,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
        )
    return tuple(identities)


def _verify_included_output_directories_fallback(
    identities: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for directory_path, expected_identity in identities:
        try:
            directory_stat = os.lstat(directory_path)
        except OSError as error:
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            ) from error
        if (
            _included_fs.output_path_is_redirected(directory_path, directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or (directory_stat.st_dev, directory_stat.st_ino)
            != expected_identity
        ):
            raise OSError(
                f"Included File output directory changed: {directory_path}"
            )


def _verify_included_output_stage_fallback(
    staged_path: str,
    expected_identity: tuple[int, int],
    expected_project_identity: tuple[int, int],
) -> None:
    try:
        staged_stat = os.lstat(staged_path)
        parent_path = os.path.dirname(staged_path) or os.curdir
        parent_stat = os.lstat(parent_path)
    except OSError as error:
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        ) from error
    if (
        _included_fs.output_path_is_redirected(staged_path, staged_stat)
        or not stat.S_ISREG(staged_stat.st_mode)
        or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        or _included_fs.output_path_is_redirected(parent_path, parent_stat)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or (parent_stat.st_dev, parent_stat.st_ino)
        != expected_project_identity
    ):
        raise OSError(
            f"Included File staging output changed: {staged_path}"
        )


def _remove_included_output_stage_fallback(
    staged_paths: tuple[str, ...],
    expected_identity: tuple[int, int],
) -> None:
    checked_paths: set[str] = set()
    for staged_path in staged_paths:
        normalized_path = os.path.normcase(os.path.abspath(staged_path))
        if normalized_path in checked_paths:
            continue
        checked_paths.add(normalized_path)
        try:
            staged_stat = os.lstat(staged_path)
        except OSError:
            continue
        if (
            not stat.S_ISREG(staged_stat.st_mode)
            or (staged_stat.st_dev, staged_stat.st_ino) != expected_identity
        ):
            continue
        try:
            os.unlink(staged_path)
        except PermissionError:
            if os.name != "nt":
                raise
            os.chmod(staged_path, stat.S_IWRITE)
            writable_stat = os.lstat(staged_path)
            if (
                not stat.S_ISREG(writable_stat.st_mode)
                or (writable_stat.st_dev, writable_stat.st_ino)
                != expected_identity
            ):
                raise OSError(
                    f"Included File staging output changed: {staged_path}"
                )
            os.unlink(staged_path)
        return


def _publish_included_output_fallback(
    project_path: str,
    components: tuple[str, ...],
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    directory_identities = prepare_included_output_directories_fallback(
        project_path,
        components[:-1],
    )
    output_directory = os.path.join(project_path, *components[:-1])
    output_path = os.path.join(output_directory, components[-1])
    output_identity = _included_metadata.included_output_state(output_path)
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=project_path,
        prefix=".gm2godot-",
        suffix=".tmp",
    )
    temporary_stat = os.fstat(file_descriptor)
    temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
    resolved_temporary_path = temporary_path
    temporary_pending = True
    try:
        resolved_temporary_path = os.path.realpath(temporary_path)
        verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        verify_included_output_directories_fallback(
            directory_identities[:1]
        )
        with os.fdopen(file_descriptor, "wb") as target_file:
            file_descriptor = -1
            payload_receipt = copy_included_payload(
                source_file,
                target_file,
                source_stat,
                expected_receipt,
            )
            target_file.flush()
            _included_fs.apply_output_metadata(
                target_file.fileno(),
                source_stat,
            )
            os.fsync(target_file.fileno())
        verify_included_output_directories_fallback(directory_identities)
        verify_included_output_stage_fallback(
            resolved_temporary_path,
            temporary_identity,
            directory_identities[0][1],
        )
        _included_metadata.verify_included_output_state(output_path, output_identity)
        verify_included_output_directories_fallback(directory_identities)
        os.replace(resolved_temporary_path, output_path)
        temporary_pending = False
        published_stat = os.lstat(output_path)
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or (published_stat.st_dev, published_stat.st_ino)
            != temporary_identity
        ):
            raise OSError(
                f"Included File output changed after publication: {output_path}"
            )
        with _included_fs.open_validation_stream(
            output_path,
            deny_writes=False,
            no_follow=True,
        ) as published_file:
            opened_stat = os.fstat(published_file.fileno())
            current_stat = os.lstat(output_path)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not os.path.samestat(opened_stat, current_stat)
                or _included_metadata.included_path_handle_binding(current_stat)
                != _included_metadata.included_path_handle_binding(opened_stat)
                or (current_stat.st_dev, current_stat.st_ino)
                != temporary_identity
                or current_stat.st_nlink != 1
                or current_stat.st_size != payload_receipt.byte_count
            ):
                raise OSError(
                    f"Included File output changed after publication: {output_path}"
                )
            copy_receipt = _IncludedCopyReceipt(
                payload=payload_receipt,
                output_fingerprint=_included_metadata.included_path_fingerprint(current_stat),
                output_ctime_ns=current_stat.st_ctime_ns,
                output_handle_state=_included_metadata.included_handle_state(opened_stat),
            )
        return copy_receipt
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_pending:
            try:
                remove_included_output_stage_fallback(
                    (resolved_temporary_path, temporary_path),
                    temporary_identity,
                )
            except OSError:
                pass


def _publish_confined_included_output(
    project_path: str,
    output_path: str,
    source_file: BinaryIO,
    source_stat: os.stat_result,
    expected_receipt: _IncludedNoOpSourceReceipt | None = None,
) -> _IncludedCopyReceipt:
    components = _included_paths.included_output_components(project_path, output_path)
    ensure_included_output_project_root(project_path)
    if _included_fs.confined_output_supported():
        return publish_included_output_at(
            project_path,
            components,
            source_file,
            source_stat,
            expected_receipt,
        )
    return publish_included_output_fallback(
        project_path,
        components,
        source_file,
        source_stat,
        expected_receipt,
    )


ensure_included_output_project_root = _ensure_included_output_project_root
verify_open_included_output_directory = _verify_open_included_output_directory
read_included_payload_chunk = _read_included_payload_chunk
copy_included_payload = _copy_included_payload
stage_included_output_at = _stage_included_output_at
publish_included_output_at = _publish_included_output_at
prepare_included_output_directories_fallback = _prepare_included_output_directories_fallback
verify_included_output_directories_fallback = _verify_included_output_directories_fallback
verify_included_output_stage_fallback = _verify_included_output_stage_fallback
remove_included_output_stage_fallback = _remove_included_output_stage_fallback
publish_included_output_fallback = _publish_included_output_fallback
publish_confined_included_output = _publish_confined_included_output
