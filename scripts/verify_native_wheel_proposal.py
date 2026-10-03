#!/usr/bin/env python3
"""Independently inspect four source-bound original native wheel proposal ZIPs.

Only trusted source-owned publication code is loaded. Artifact bytes are never
extracted, imported, or executed. Native tag observations are authenticated by
source/job provenance externally; this verifier checks their internal bindings.
"""
from __future__ import annotations

import argparse
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import importlib.util
import itertools
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from types import MappingProxyType
from typing import Any, BinaryIO, Callable, cast
import unicodedata
import zipfile

HOSTS: Mapping[str, Mapping[str, str]] = MappingProxyType({
    'linux-x64': MappingProxyType(dict(python_version='3.12.13', sys_platform='linux', os_name='posix', system='Linux', machine='x86_64', seed='constraints/requirements-linux-py312.lock', companion='constraints/requirements-linux-x64-py312.wheels.lock')),
    'macos-arm64': MappingProxyType(dict(python_version='3.12.10', sys_platform='darwin', os_name='posix', system='Darwin', machine='arm64', seed='constraints/requirements-macos-py312.lock', companion='constraints/requirements-macos-arm64-py312.wheels.lock')),
    'macos-x64': MappingProxyType(dict(python_version='3.12.10', sys_platform='darwin', os_name='posix', system='Darwin', machine='x86_64', seed='constraints/requirements-macos-py312.lock', companion='constraints/requirements-macos-x64-py312.wheels.lock')),
    'windows-x64': MappingProxyType(dict(python_version='3.12.10', sys_platform='win32', os_name='nt', system='Windows', machine='AMD64', seed='constraints/requirements-windows-py312.lock', companion='constraints/requirements-windows-x64-py312.wheels.lock')),
})
PHASE_ORDER = ('native-preflight', 'current-preflight', 'current-generator', 'candidate-compile', 'candidate-preflight', 'first-download', 'first-observation', 'second-download', 'second-observation', 'candidate-generator', 'selfhost-compile', 'fresh-1', 'fresh-2')
SOURCE_HELPERS = ('scripts/propose_native_wheels.py', 'scripts/verify_native_wheel_proposal.py', 'scripts/compile_dependency_lock.py', 'scripts/verify_dependency_environment.py', 'scripts/verify_dependency_bootstrap.py', 'scripts/_anchored_output.py', 'scripts/_anchored_receipt_posix.py', 'scripts/_anchored_receipt_windows.py')
REQUIREMENT_ROOTS = ('requirements-bootstrap.txt', 'requirements.txt', 'requirements-tooling.txt', 'requirements-lock.in')
WORKFLOW_PATH = '.github/workflows/native-wheel-proposals.yml'
POSITIVE_MEMBERS = ('proposal.json', 'inputs/source-bindings.json', 'inputs/seed.lock', 'candidate/version.lock', 'selfhost/version.lock', 'candidate/companion.wheels.lock', 'downloads/first-wheel-inventory.json', 'downloads/second-wheel-inventory.json', 'downloads/second-companion.wheels.lock', 'receipts/current-preflight.json', 'receipts/current-generator.json', 'receipts/candidate-preflight.json', 'receipts/candidate-generator.json', 'receipts/fresh-1.json', 'receipts/fresh-2.json', 'logs/commands.jsonl')
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 2 * 1024**3
MAX_WHEEL_BYTES = 512 * 1024**2
MAX_OUTER_MEMBERS = 512
MAX_WHEEL_MEMBERS = 100000
MAX_JSON_BYTES = 16 * 1024**2
MAX_LOCK_BYTES = 1024**2
MAX_METADATA_BYTES = 4 * 1024**2
MAX_ZIP_READ_BYTES = 32 * 1024**2
READ_CHUNK_BYTES = 1024**2
MAX_TAGS = 8192
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SOURCE_SHA = re.compile(r'[0-9a-f]{40}\Z')
_NAME = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z', re.ASCII)
_PIN = re.compile(r'([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)\Z', re.ASCII)
_TAG = re.compile(r'[a-z0-9_]+-[a-z0-9_]+-[a-z0-9_]+\Z', re.ASCII)
_COMPILE_FLAGS = ('--resolver=backtracking', '--strip-extras', '--allow-unsafe', '--no-emit-index-url', '--no-emit-trusted-host', '--no-emit-find-links', '--no-emit-options', '--no-config', '--pip-args=--isolated --disable-pip-version-check --no-input --no-cache-dir --only-binary=:all:')


class ProposalError(ValueError):
    """An artifact or its independently supplied provenance failed policy."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProposalError(message)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_name(name: str) -> str:
    _require(_NAME.fullmatch(name) is not None, 'invalid distribution name')
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_version_lock(content: bytes) -> dict[str, str]:
    _require(0 < len(content) <= MAX_LOCK_BYTES, 'version lock size invalid')
    try:
        text = content.decode('utf-8')
    except UnicodeError as error:
        raise ProposalError('version lock is not UTF-8') from error
    pins: dict[str, str] = {}
    for line in text.splitlines():
        _require('\\' not in line, 'version lock continuation forbidden')
        value = line.split('#', 1)[0].strip()
        if not value:
            continue
        match = _PIN.fullmatch(value)
        _require(match is not None, 'version lock must contain only exact pins')
        assert match is not None
        name, version = normalize_name(match[1]), match[2]
        _require(name not in pins, 'version lock normalized name duplicate')
        pins[name] = version
    _require(bool(pins), 'version lock empty')
    return pins


def pin_fingerprint(pins: Mapping[str, str]) -> str:
    return sha256(''.join(f'{name}=={pins[name]}\n' for name in sorted(pins)).encode())


def canonical_companion(pins: Mapping[str, str], wheel_hashes: Mapping[str, str]) -> bytes:
    _require(set(pins) == set(wheel_hashes), 'companion wheel pin set mismatch')
    _require(all(_SHA.fullmatch(value) is not None for value in wheel_hashes.values()), 'invalid companion digest')
    return ''.join(f'{name}=={pins[name]} --hash=sha256:{wheel_hashes[name]}\n' for name in sorted(pins)).encode('ascii')


def canonical_compile_command(seed: str) -> str:
    quoted_flags = ' '.join(_COMPILE_FLAGS[:-1])
    return f'python -I scripts/compile_dependency_lock.py {quoted_flags} "{_COMPILE_FLAGS[-1]}" --output-file={seed} requirements-lock.in'


def _object(value: Any, keys: Sequence[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f'{label}: expected object')
    result = cast(dict[str, Any], value)
    _require(set(result) == set(keys), f'{label}: unexpected object keys')
    return result


def _list(value: Any, label: str) -> list[Any]:
    _require(isinstance(value, list), f'{label}: expected list')
    return cast(list[Any], value)


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    _require(type(value) is int and (value > 0 if positive else value >= 0), f'{label}: expected exact integer')
    return cast(int, value)


def _string(value: Any, label: str, *, empty: bool = False) -> str:
    _require(isinstance(value, str) and (bool(value) or empty) and '\x00' not in value, f'{label}: invalid string')
    return cast(str, value)


def _digest(value: Any, label: str) -> str:
    result = _string(value, label)
    _require(_SHA.fullmatch(result) is not None, f'{label}: invalid SHA256')
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ProposalError(f'nonfinite JSON constant {value}')


def parse_json(content: bytes, label: str) -> Any:
    _require(0 < len(content) <= MAX_JSON_BYTES, f'{label}: JSON size invalid')
    try:
        return json.loads(content.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ProposalError(f'{label}: invalid strict UTF-8 JSON') from error


def _stat_key(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _same_file_views(named: os.stat_result, opened: os.stat_result) -> bool:
    if sys.platform != 'win32':
        return _stat_key(named) == _stat_key(opened)
    named_birth = getattr(named, 'st_birthtime_ns', None)
    opened_birth = getattr(opened, 'st_birthtime_ns', None)
    return (_stat_key(named)[:6] == _stat_key(opened)[:6]
            and type(named_birth) is int and type(opened_birth) is int
            and named_birth == opened_birth)


@contextmanager
def _regular_file(path: Path, maximum: int) -> Generator[tuple[BinaryIO, os.stat_result]]:
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum, f'{path}: physical bounded regular file required')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    primary: BaseException | None = None
    try:
        opened = os.fstat(fd)
        _require(_same_file_views(before, opened), f'{path}: file identity changed before read; expected={_stat_key(before)!r}; observed={_stat_key(opened)!r}')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            yield stream, opened
        _require(_stat_key(os.fstat(fd)) == _stat_key(opened) and _stat_key(path.lstat()) == _stat_key(before), f'{path}: file changed during read')
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note(f'File close failed: {str(error)[:512]}')


def _source_bytes(root: Path, relative: str, maximum: int = MAX_JSON_BYTES) -> bytes:
    _safe_member(relative)
    path = root / relative
    current = root
    _require(stat.S_ISDIR(current.lstat().st_mode) and not current.is_symlink(), 'source root must be a physical directory')
    for component in Path(relative).parts[:-1]:
        current /= component
        _require(stat.S_ISDIR(current.lstat().st_mode) and not current.is_symlink(), f'{relative}: source ancestor must be physical')
    with _regular_file(path, maximum) as (stream, before):
        result = stream.read(maximum + 1)
        _require(len(result) == before.st_size and len(result) <= maximum, f'{relative}: source size drift')
        return result


class _BoundedReader:
    """A borrowed seekable stream with fixed EOF and bounded read requests."""

    def __init__(self, stream: BinaryIO, size: int) -> None:
        self.stream = stream
        self.size = size

    def read(self, size: int = -1) -> bytes:
        remaining = self.size - self.tell()
        requested = remaining if size < 0 else min(size, remaining)
        _require(0 <= requested <= MAX_ZIP_READ_BYTES, 'ZIP read request exceeds independent bound')
        content = self.stream.read(requested)
        _require(len(content) == requested, 'ZIP truncated during bounded read')
        return content

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        target = offset if whence == os.SEEK_SET else self.tell() + offset if whence == os.SEEK_CUR else self.size + offset if whence == os.SEEK_END else -1
        _require(0 <= target <= self.size, 'ZIP seek outside fixed file bounds')
        return self.stream.seek(target, os.SEEK_SET)

    def tell(self) -> int:
        return self.stream.tell()

    def seekable(self) -> bool:
        return True


def _safe_member(name: str) -> str:
    _require(bool(name) and '\x00' not in name and '\\' not in name and not name.startswith('/') and ':' not in name, 'unsafe ZIP member path')
    stripped = name[:-1] if name.endswith('/') else name
    _require(bool(stripped) and all(part not in ('', '.', '..') for part in stripped.split('/')), 'unsafe ZIP path components')
    _require(unicodedata.normalize('NFC', stripped) == stripped, 'ZIP path must use canonical Unicode')
    return stripped


def _zip_members(archive: zipfile.ZipFile, *, maximum: int, total_limit: int) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    _require(0 < len(infos) <= maximum, 'ZIP member count exceeds bound')
    members: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    total = 0
    for info in infos:
        _require(info.filename == info.orig_filename, 'ZIP filename was truncated')
        name = _safe_member(info.filename)
        _require(name not in members and name.casefold() not in folded, 'ZIP duplicate or case-colliding member')
        _require(not info.flag_bits & 1, 'encrypted ZIP member forbidden')
        mode = info.external_attr >> 16
        member_type = stat.S_IFMT(mode)
        _require(member_type in (0, stat.S_IFREG, stat.S_IFDIR), 'ZIP symlink/special member forbidden')
        _require(member_type != stat.S_IFDIR or info.is_dir(), 'ZIP directory mode mismatch')
        _require(member_type != stat.S_IFREG or not info.is_dir(), 'ZIP regular mode mismatch')
        _require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'unsupported ZIP compression')
        _require(0 <= info.file_size <= total_limit, 'ZIP member size exceeds bound')
        if info.is_dir():
            _require(info.file_size == 0, 'ZIP directory data forbidden')
        total += info.file_size
        _require(total <= total_limit, 'ZIP uncompressed total exceeds bound')
        members[name] = info
        folded.add(name.casefold())
    for name in members:
        for ancestor in _ancestors(name):
            _require(ancestor not in members or members[ancestor].is_dir(), 'ZIP file used as parent')
    return members


def _ancestors(name: str) -> list[str]:
    parts = name.split('/')
    return ['/'.join(parts[:count]) for count in range(1, len(parts))]


def _member_bytes(archive: zipfile.ZipFile, info: zipfile.ZipInfo, maximum: int) -> bytes:
    _require(not info.is_dir() and 0 < info.file_size <= maximum, f'{info.filename}: member size invalid')
    with archive.open(info) as stream:
        content = stream.read(maximum + 1)
        _require(len(content) == info.file_size, f'{info.filename}: member size drift')
        _require(not stream.read(1), f'{info.filename}: trailing bytes')
        return content


def _member_digest(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    count = 0
    with archive.open(info) as stream:
        while chunk := stream.read(READ_CHUNK_BYTES):
            count += len(chunk)
            _require(count <= info.file_size, 'ZIP streamed member grew')
            digest.update(chunk)
    _require(count == info.file_size, 'ZIP streamed member truncated')
    return digest.hexdigest()


def _file_record(content: bytes) -> dict[str, Any]:
    return {'sha256': sha256(content), 'bytes': len(content)}


def _file_records(value: Any, expected: Mapping[str, dict[str, Any]], label: str) -> None:
    _require(isinstance(value, dict), f'{label}: expected file records object')
    records = cast(dict[str, Any], value)
    _require(set(records) == set(expected), f'{label}: file set mismatch')
    for name, record in expected.items():
        observed = _object(records[name], ('sha256', 'bytes'), f'{label}.{name}')
        _digest(observed['sha256'], label)
        _integer(observed['bytes'], label, positive=True)
        _require(observed == record, f'{label}.{name}: source/size/hash mismatch')


def native_tuple(platform: str) -> dict[str, str]:
    host = HOSTS[platform]
    return {key: host[key] for key in ('python_version', 'sys_platform', 'os_name', 'system', 'machine')} | {'implementation': 'cpython'}


def _tags(value: Any, *, ordered: bool, label: str) -> list[str]:
    items = _list(value, label)
    _require(0 < len(items) <= MAX_TAGS and all(isinstance(item, str) and _TAG.fullmatch(item) for item in items), f'{label}: invalid tags')
    tags = cast(list[str], items)
    _require(len(tags) == len(set(tags)), f'{label}: duplicate tags')
    _require(ordered or tags == sorted(tags), f'{label}: tags must be sorted')
    return tags


def _tag_observation(value: Any, pins: Mapping[str, str]) -> dict[str, Any]:
    result = _object(value, ('packaging_version', 'packaging_tags_sha256', 'packaging_utils_sha256', 'tags', 'tags_sha256'), 'tag observation')
    _require(result['packaging_version'] == pins.get('packaging'), 'native Packaging version does not match candidate')
    _digest(result['packaging_tags_sha256'], 'Packaging tags module')
    _digest(result['packaging_utils_sha256'], 'Packaging utils module')
    tags = _tags(result['tags'], ordered=True, label='native tags')
    _require(result['tags_sha256'] == sha256(('\n'.join(tags) + '\n').encode()), 'native tags digest mismatch')
    return result


def _filename_identity(filename: str) -> tuple[str, str, list[str]]:
    _require(filename.endswith('.whl') and '/' not in filename and '\\' not in filename, 'invalid wheel basename')
    parts = filename[:-4].split('-')
    _require(len(parts) in (5, 6), 'invalid wheel filename components')
    if len(parts) == 6:
        _require(re.fullmatch(r'[0-9][A-Za-z0-9_]*', parts[2]) is not None, 'invalid wheel build tag')
    name, version = normalize_name(parts[0]), parts[1]
    _require(_PIN.fullmatch(f'{name}=={version}') is not None, 'invalid wheel filename version')
    groups = [part.split('.') for part in parts[-3:]]
    _require(all(group and all(re.fullmatch(r'[a-z0-9_]+', tag) for tag in group) for group in groups), 'invalid compressed wheel tags')
    _require(len(groups[0]) * len(groups[1]) * len(groups[2]) <= MAX_TAGS, 'wheel tag expansion exceeds bound')
    tags = sorted({'-'.join(combination) for combination in itertools.product(*groups)})
    return name, version, tags


def inspect_wheel(stream: BinaryIO, size: int, filename: str) -> dict[str, Any]:
    """Inspect nested wheel metadata without extraction or wheel execution."""
    _require(0 < size <= MAX_WHEEL_BYTES, 'wheel size exceeds bound')
    name, version, tags = _filename_identity(filename)
    with zipfile.ZipFile(cast(Any, _BoundedReader(stream, size))) as archive:
        members = _zip_members(archive, maximum=MAX_WHEEL_MEMBERS, total_limit=MAX_TOTAL_BYTES)
        metadata_names = [key for key in members if key.endswith('.dist-info/METADATA') and key.count('/') == 1]
        _require(len(metadata_names) == 1, 'wheel requires exactly one METADATA')
        wheel_names = [key for key in members if key.endswith('.dist-info/WHEEL') and key.count('/') == 1]
        _require(len(wheel_names) == 1, 'wheel requires exactly one WHEEL')
        metadata_name = metadata_names[0]
        parent = metadata_name.removesuffix('/METADATA')
        _require(wheel_names[0] == parent + '/WHEEL', 'wheel root metadata parents mismatch')
        dist_info = parent.removesuffix('.dist-info').rsplit('/', 1)[-1]
        _require('-' in dist_info, 'wheel dist-info identity missing')
        distribution, metadata_version = dist_info.rsplit('-', 1)
        _require('/' not in parent and normalize_name(distribution) == name and metadata_version == version, 'wheel dist-info identity mismatch')
        wheel_name = parent + '/WHEEL'
        _require(wheel_name in members, 'wheel WHEEL metadata missing')
        metadata = _member_bytes(archive, members[metadata_name], MAX_METADATA_BYTES)
        wheel = _member_bytes(archive, members[wheel_name], MAX_METADATA_BYTES)
        for content in (metadata, wheel):
            _require(b'\x00' not in content, 'wheel metadata contains NUL')
            try:
                content.decode('utf-8')
            except UnicodeError as error:
                raise ProposalError('wheel metadata must be UTF-8') from error
        message = BytesParser(policy=compat32).parsebytes(metadata)
        _require(not message.defects and len(message.get_all('Name', [])) == 1 and len(message.get_all('Version', [])) == 1, 'wheel METADATA identity ambiguous')
        _require(normalize_name(str(message['Name'])) == name and str(message['Version']) == version, 'wheel METADATA/filename identity mismatch')
        wheel_message = BytesParser(policy=compat32).parsebytes(wheel)
        _require(not wheel_message.defects and wheel_message.get_all('Wheel-Version', []) == ['1.0'], 'wheel WHEEL version invalid')
        wheel_tags: set[str] = set()
        for tag in wheel_message.get_all('Tag', []):
            _, _, expanded = _filename_identity(f'x-1-{tag}.whl')
            wheel_tags.update(expanded)
        _require(wheel_tags == set(tags), 'wheel WHEEL/filename tags mismatch')
        result: dict[str, Any] = {'name': name, 'version': version, 'tags': tags}
        if name == 'packaging':
            for component in ('tags', 'utils'):
                member = f'packaging/{component}.py'
                _require(member in members, 'Packaging observation module missing from wheel')
                result[f'packaging_{component}_sha256'] = sha256(_member_bytes(archive, members[member], MAX_METADATA_BYTES))
        return result


def _inventory(value: Any, identity: Mapping[str, Any], native: Mapping[str, str], candidate: bytes, pins: Mapping[str, str], observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = _object(value, ('schema_version', 'identity', 'native', 'candidate_sha256', 'tag_observation', 'wheels'), 'wheel inventory')
    _require(type(result['schema_version']) is int and result['schema_version'] == 1, 'wheel inventory schema invalid')
    inventory_identity = _object(result['identity'], tuple(identity), 'inventory identity')
    _integer(inventory_identity['run_id'], 'inventory run id', positive=True)
    _integer(inventory_identity['run_attempt'], 'inventory attempt', positive=True)
    _object(result['native'], tuple(native), 'inventory native')
    _require(result['identity'] == identity and result['native'] == native and result['candidate_sha256'] == sha256(candidate) and result['tag_observation'] == observation, 'wheel inventory provenance mismatch')
    rows = _list(result['wheels'], 'wheel inventory rows')
    _require(len(rows) == len(pins), 'wheel inventory does not cover complete graph')
    names: list[str] = []
    filenames: set[str] = set()
    for raw in rows:
        row = _object(raw, ('name', 'version', 'filename', 'size', 'sha256', 'tags', 'compatible_tags'), 'wheel row')
        name = _string(row['name'], 'wheel name')
        _require(name == normalize_name(name) and row['version'] == pins.get(name), 'wheel normalized name/version mismatch')
        filename = _string(row['filename'], 'wheel filename')
        actual_name, version, tags = _filename_identity(filename)
        _require(actual_name == name and version == row['version'] and row['tags'] == tags, 'wheel filename identity/tag mismatch')
        _integer(row['size'], 'wheel size', positive=True)
        _require(row['size'] <= MAX_WHEEL_BYTES, 'wheel size exceeds bound')
        _digest(row['sha256'], 'wheel SHA256')
        compatible = sorted(set(tags).intersection(observation['tags']))
        _require(bool(compatible) and row['compatible_tags'] == compatible, 'wheel native compatibility mismatch')
        _require(filename not in filenames, 'duplicate wheel filename')
        names.append(name)
        filenames.add(filename)
    _require(names == sorted(pins), 'wheel inventory order/coverage mismatch')
    return cast(list[dict[str, Any]], rows)


def _pins_projection(value: Any, label: str) -> dict[str, str]:
    rows = _list(value, label)
    result: dict[str, str] = {}
    names: list[str] = []
    for raw in rows:
        row = _object(raw, ('name', 'version'), label)
        name = _string(row['name'], label)
        version = _string(row['version'], label)
        _require(name == normalize_name(name) and name not in result and _PIN.fullmatch(f'{name}=={version}') is not None, f'{label}: invalid or duplicate pin')
        result[name] = version
        names.append(name)
    _require(bool(result) and names == sorted(result), f'{label}: empty/unsorted pin projection')
    return result


def _bootstrap_projection(value: Any, source: bytes, constraint: bytes) -> tuple[str, str]:
    result = _object(value, ('policy', 'state', 'source', 'constraints', 'source_transition'), 'bootstrap projection')
    _require(result['policy'] == 'stable' and result['state'] == 'stable', 'bootstrap policy/state must be stable')
    pair = parse_version_lock(source)
    _require(set(pair) == {'pip', 'pip-tools'}, 'bootstrap source pair invalid')
    pins = parse_version_lock(constraint)
    _require(all(pins.get(name) == version for name, version in pair.items()), 'bootstrap candidate pair mismatch')
    source_record = _object(result['source'], ('path', 'sha256', 'pin_fingerprint', 'pins'), 'bootstrap source')
    source_path = _string(source_record['path'], 'bootstrap source path')
    _require(source_record['sha256'] == sha256(source) and source_record['pin_fingerprint'] == pin_fingerprint(pair) and source_record['pins'] == pair, 'bootstrap source binding mismatch')
    constraints = _list(result['constraints'], 'bootstrap constraints')
    _require(len(constraints) == 1, 'stable bootstrap requires one constraint')
    selected = _object(constraints[0], ('path', 'sha256', 'pin_fingerprint', 'bootstrap_pins'), 'bootstrap constraint')
    path = _string(selected['path'], 'bootstrap constraint path')
    _require(path != source_path and selected['sha256'] == sha256(constraint) and selected['pin_fingerprint'] == pin_fingerprint(pins) and selected['bootstrap_pins'] == pair, 'bootstrap constraint binding mismatch')
    transition = _object(result['source_transition'], ('active', 'from', 'to'), 'bootstrap transition')
    _require(transition == {'active': False, 'from': pair, 'to': pair} and type(transition['active']) is bool, 'bootstrap transition forbidden')
    return source_path, path


def _preflight(value: Any, bootstrap: bytes, constraint: bytes) -> tuple[str, str]:
    result = _object(value, ('schema_version', 'status', 'policy', 'state', 'source', 'constraints', 'source_transition', 'errors'), 'preflight receipt')
    _require(type(result['schema_version']) is int and result['schema_version'] == 1 and result['status'] == 'verified' and result['errors'] == [], 'preflight receipt not verified')
    projection = {key: result[key] for key in ('policy', 'state', 'source', 'constraints', 'source_transition')}
    return _bootstrap_projection(projection, bootstrap, constraint)


def _receipt(value: Any, bootstrap: bytes, constraint: bytes, native: Mapping[str, str], *, mode: str) -> tuple[str, str]:
    result = _object(value, ('schema_version', 'status', 'mode', 'bootstrap', 'constraint', 'required', 'expected_environment', 'observation', 'errors'), 'schema2 receipt')
    _require(type(result['schema_version']) is int and result['schema_version'] == 2 and result['status'] == 'verified' and result['mode'] == mode and result['errors'] == [], 'schema2 receipt not verified')
    source_path, path = _bootstrap_projection(result['bootstrap'], bootstrap, constraint)
    pins = parse_version_lock(constraint)
    record = _object(result['constraint'], ('fingerprint', 'path', 'pins', 'sha256'), 'receipt constraint')
    _require(record['path'] == path and record['sha256'] == sha256(constraint) and record['fingerprint'] == pin_fingerprint(pins) and _pins_projection(record['pins'], 'constraint pins') == pins, 'schema2 constraint mismatch')
    required = _list(result['required'], 'required packages')
    _require(required == (['pip', 'pip-tools'] if mode == 'subset' else []), 'original required package policy changed')
    expected = {'implementation_name': 'cpython', 'pip_version': pins['pip'], 'platform_machine': native['machine'], 'python_full_version': native['python_version'], 'python_version': '3.12', 'sys_platform': native['sys_platform']}
    _require(result['expected_environment'] == expected, 'schema2 expected runtime mismatch')
    observation = _object(result['observation'], ('pip_check', 'pip_inspect', 'environment', 'installed', 'installed_fingerprint', 'pip_inspect_schema', 'pip_version'), 'receipt observation')
    observed_environment = {'implementation_name': 'cpython', 'implementation_version': native['python_version'], 'os_name': native['os_name'], 'platform_machine': native['machine'], 'platform_python_implementation': 'CPython', 'platform_system': native['system'], 'python_full_version': native['python_version'], 'python_version': '3.12', 'sys_platform': native['sys_platform']}
    _require(observation['environment'] == observed_environment and observation['pip_version'] == pins['pip'] and observation['pip_inspect_schema'] == '1', 'schema2 actual runtime/pip mismatch')
    for key, keys in (('pip_check', ('returncode', 'stderr', 'stdout')), ('pip_inspect', ('returncode', 'stderr'))):
        command = _object(observation[key], keys, f'observation {key}')
        _require(type(command['returncode']) is int and command['returncode'] == 0, f'{key} did not succeed')
        for text_key in keys[1:]:
            text = _string(command[text_key], key, empty=True)
            _require(len(text) <= 65536, f'{key} output exceeds bound')
    installed = _pins_projection(observation['installed'], 'installed pins')
    _require(observation['installed_fingerprint'] == pin_fingerprint(installed), 'installed fingerprint mismatch')
    _require(all(name in pins and pins[name] == version for name, version in installed.items()) and all(installed.get(name) == pins[name] for name in ('pip', 'pip-tools')), 'installed subset/pair mismatch')
    _require(mode != 'complete' or installed == pins, 'complete environment missing packages')
    return source_path, path


def _option(argv: Sequence[str], flag: str) -> str:
    values: list[str] = []
    for index, arg in enumerate(argv):
        if arg == flag:
            _require(index + 1 < len(argv), f'{flag}: missing option value')
            values.append(argv[index + 1])
        elif arg.startswith(flag + '='):
            values.append(arg[len(flag) + 1:])
    _require(len(values) == 1 and bool(values[0]), f'{flag}: missing/duplicate option')
    return values[0]


def _absolute_key(path: str, native: Mapping[str, str]) -> str:
    spelling = path.replace('\\', '/')
    _require(bool(spelling) and all(part not in ('.', '..') for part in spelling.split('/')), 'command path has relative traversal')
    if native['os_name'] == 'nt':
        _require(ntpath.isabs(path) and bool(ntpath.splitdrive(path)[0]), 'command path must be absolute native Windows path')
        return spelling.casefold()
    _require(spelling.startswith('/'), 'command path must be absolute native POSIX path')
    return spelling


def _command_policy(rows: list[dict[str, Any]], phases: list[Any], seed: str, native: Mapping[str, str], bootstrap_path: str, seed_path: str, candidate_path: str) -> None:
    _require(len(phases) == len(PHASE_ORDER), 'phase proof count mismatch')
    ids: dict[str, list[int]] = {phase: [] for phase in PHASE_ORDER}
    grouped: dict[str, list[dict[str, Any]]] = {phase: [] for phase in PHASE_ORDER}
    previous_phase = 0
    for number, raw in enumerate(rows, 1):
        row = _object(raw, ('id', 'phase', 'kind', 'argv', 'cwd', 'returncode'), 'command row')
        _require(type(row['id']) is int and row['id'] == number and type(row['returncode']) is int and row['returncode'] == 0, 'command id/outcome invalid')
        phase = _string(row['phase'], 'command phase')
        _require(phase in ids and phase != 'native-preflight', 'command phase invalid')
        ordinal = PHASE_ORDER.index(phase)
        _require(ordinal >= previous_phase, 'command phase order regressed')
        previous_phase = ordinal
        _require(row['kind'] in ('venv', 'preflight', 'install', 'verify', 'compile', 'download', 'observe'), 'command kind invalid')
        argv = _list(row['argv'], 'command argv')
        _require(0 < len(argv) <= 256 and all(isinstance(arg, str) and arg and '\x00' not in arg and len(arg) <= 32768 for arg in argv), 'command argv invalid')
        _string(row['cwd'], 'command cwd')
        _absolute_key(row['cwd'], native)
        _absolute_key(argv[0], native)
        _require(len(row['cwd']) <= 32768 and len(argv) > 1 and argv[1] == '-I', 'command interpreter isolation missing')
        banned = ('--platform', '--python-version', '--implementation', '--abi', '--no-deps', '--index-url', '--extra-index-url', '--trusted-host', '--target', '--prefix', '--user')
        _require(not any(arg == flag or arg.startswith(flag + '=') for arg in argv for flag in banned), 'command contains forbidden pip override/bypass')
        ids[phase].append(number)
        grouped[phase].append(row)
    for phase, raw in zip(PHASE_ORDER, phases, strict=True):
        record = _object(raw, ('name', 'returncode', 'command_ids'), 'phase row')
        _require(record['name'] == phase and type(record['returncode']) is int and record['returncode'] == 0 and record['command_ids'] == ids[phase], 'phase status/order/command coverage mismatch')
        for identifier in _list(record['command_ids'], 'phase ids'):
            _integer(identifier, 'phase id', positive=True)
        _require(phase == 'native-preflight' or bool(ids[phase]), 'required native phase command missing')
    _require(bool(rows), 'empty command proof')
    python_suffix = '/Scripts/python.exe' if native['os_name'] == 'nt' else '/bin/python'
    environments: dict[str, str] = {}
    env_roots: set[str] = set()
    for phase in ('current-generator', 'candidate-generator', 'fresh-1', 'fresh-2'):
        commands = grouped[phase]
        _require([row['kind'] for row in commands] == ['venv', 'install', 'install', 'verify'], 'environment requires ordered venv/two installs/verification')
        creation = commands[0]['argv']
        _require(len(creation) == 5 and creation[1:4] == ['-I', '-m', 'venv'], 'venv creation command invalid')
        root = _absolute_key(creation[4], native)
        _require(root not in env_roots, 'fresh environment root reused')
        env_roots.add(root)
        python = root + python_suffix.casefold() if native['os_name'] == 'nt' else root + python_suffix
        environments[phase] = python
        for command in commands[1:]:
            _require(_absolute_key(command['argv'][0], native) == python, 'install/verify uses another phase environment')
    expected_helpers_root = bootstrap_path.replace('\\', '/').rsplit('/', 1)[0]
    verifier_path = expected_helpers_root + '/scripts/verify_dependency_environment.py'
    producer_path = expected_helpers_root + '/scripts/propose_native_wheels.py'
    companion_path = candidate_path.replace('\\', '/').rsplit('/', 1)[0] + '/companion.wheels.lock'
    artifact_root = candidate_path.replace('\\', '/').rsplit('/', 2)[0]
    house_paths: dict[str, str] = {}
    for phase in ('first-download', 'second-download'):
        _require(len(grouped[phase]) == 1 and grouped[phase][0]['kind'] == 'download', 'download phase must have one actual download')
        argv = grouped[phase][0]['argv']
        _require(_absolute_key(argv[0], native) == environments['current-generator'], 'download does not use verified current generator')
        house_paths[phase] = _absolute_key(_option(argv, '--dest'), native)
        _require(_absolute_key(_option(argv, '-r'), native) == _absolute_key(candidate_path, native), 'download requirement differs from candidate')
    _require(house_paths['first-download'] != house_paths['second-download'], 'independent wheelhouse destination reused')
    _require(house_paths['first-download'] == _absolute_key(artifact_root + '/wheelhouse', native), 'first actual wheelhouse differs from archived wheelhouse')
    compile_caches: set[str] = set()
    compile_roots: set[str] = set()
    for phase in ('candidate-compile', 'selfhost-compile'):
        _require(len(grouped[phase]) == 1 and grouped[phase][0]['kind'] == 'compile', 'compile phase must have one compile')
        command = grouped[phase][0]
        argv = command['argv']
        environment = 'current-generator' if phase == 'candidate-compile' else 'candidate-generator'
        _require(_absolute_key(argv[0], native) == environments[environment], 'compile uses wrong verified generator')
        _require(argv[2] == 'scripts/compile_dependency_lock.py', 'compile helper is not source-owned logical script')
        suffix = argv[3:]
        cache = _absolute_key(_option(suffix, '--cache-dir'), native)
        cwd = _absolute_key(command['cwd'], native)
        _require(cache not in compile_caches and cwd not in compile_roots, 'compile cache/root reused')
        compile_caches.add(cache)
        compile_roots.add(cwd)
        _require([arg for arg in suffix if not arg.startswith('--cache-dir=')] == [*_COMPILE_FLAGS, f'--output-file={seed}', 'requirements-lock.in'], 'compile invocation differs from canonical command/cache')
    for phase in ('first-observation', 'second-observation'):
        _require(len(grouped[phase]) == 1 and grouped[phase][0]['kind'] == 'observe', 'observation phase must have one observer')
        argv = grouped[phase][0]['argv']
        _require(len(argv) == 5 and _absolute_key(argv[0], native) == environments['current-generator'] and _absolute_key(argv[2], native) == _absolute_key(producer_path, native) and argv[3] == '--internal-observe', 'native tag observation does not use source-owned verified generator observer')
        _absolute_key(argv[4], native)
    for phase in ('current-preflight', 'candidate-preflight'):
        _require(len(grouped[phase]) == 1 and grouped[phase][0]['kind'] == 'preflight', 'preflight phase must have one preflight')
        argv = grouped[phase][0]['argv']
        constraint = seed_path if phase == 'current-preflight' else candidate_path
        _require(len(argv) > 5 and argv[2] == '-c' and 'bootstrap_preflight_main' in argv[3] and _absolute_key(argv[4], native) == _absolute_key(verifier_path, native), 'preflight source-owned helper missing')
        _require(_option(argv, '--policy') == 'stable' and _absolute_key(_option(argv, '--source'), native) == _absolute_key(bootstrap_path, native) and _absolute_key(_option(argv, '--constraint'), native) == _absolute_key(constraint, native), 'preflight original policy/path binding differs')
        _require(_absolute_key(_option(argv, '--output'), native) == _absolute_key(artifact_root + '/receipts/' + phase + '.json', native), 'preflight receipt path differs from archived receipt')
    for phase in ('current-generator', 'candidate-generator', 'fresh-1', 'fresh-2'):
        command = grouped[phase][-1]
        argv = command['argv']
        constraint = seed_path if phase == 'current-generator' else candidate_path
        _require(_absolute_key(argv[2], native) == _absolute_key(verifier_path, native), 'verification helper is not source-owned')
        checks = {'--mode': 'subset' if phase == 'current-generator' else 'complete', '--expected-python': native['python_version'], '--expected-platform': native['sys_platform'], '--expected-machine': native['machine'], '--bootstrap-policy': 'stable'}
        _require(all(_option(argv, flag) == value for flag, value in checks.items()), 'verification runtime/mode/policy differs from original receipt')
        for flag, path in (('--constraint', constraint), ('--bootstrap', bootstrap_path), ('--output', artifact_root + '/receipts/' + phase + '.json')):
            _require(_absolute_key(_option(argv, flag), native) == _absolute_key(path, native), 'verification original receipt path differs')
        required = [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == '--require']
        _require(required == (['pip', 'pip-tools'] if phase == 'current-generator' else []), 'verification original require policy differs')
        for index, install in enumerate(grouped[phase][1:3]):
            args = install['argv']
            _require(args[1:4] == ['-I', '-m', 'pip'] and 'install' in args, 'pip install command invalid')
            if phase == 'current-generator':
                _require(_absolute_key(_option(args, '--constraint'), native) == _absolute_key(seed_path, native) and args[-1] == ('pip' if index == 0 else 'pip-tools'), 'current generator bootstrap pair/seed differs')
            else:
                _require('--require-hashes' in args and '--no-index' in args, 'full offline hash install flags missing')
                house = house_paths['second-download' if phase == 'fresh-2' else 'first-download']
                _require(_absolute_key(_option(args, '--find-links'), native) == house, 'hash install uses wrong independent wheelhouse')
                requirement = _absolute_key(_option(args, '-r'), native)
                _require(requirement.endswith('/' + phase + '-pip.wheels.lock') if index == 0 else requirement == _absolute_key(companion_path, native), 'hashed pip/full companion install order differs')
    for commands in grouped.values():
        for row in commands:
            if row['kind'] not in ('install', 'download'):
                continue
            argv = row['argv']
            _require(argv[1:4] == ['-I', '-m', 'pip'] and row['kind'] in argv, 'pip operation command invalid')
            for flag in ('--isolated', '--disable-pip-version-check', '--no-input', '--no-cache-dir', '--only-binary=:all:'):
                _require(flag in argv, 'pip isolation/cache/binary flag missing')
            _require(not any('://' in arg or arg.endswith('.whl') for arg in argv), 'direct URL/wheel install forbidden')


@dataclass(frozen=True)
class ExpectedRun:
    repository: str
    source_sha: str
    run_id: int
    run_attempt: int
    phase: str
    native_jobs_result: str = 'success'

    def validate(self) -> None:
        _require(self.repository == 'Infiland/GM2Godot', 'expected canonical repository mismatch')
        _require(_SOURCE_SHA.fullmatch(self.source_sha) is not None, 'expected source SHA invalid')
        _integer(self.run_id, 'expected run id', positive=True)
        _integer(self.run_attempt, 'expected attempt', positive=True)
        _require(self.phase in ('discover', 'require-committed'), 'proposal phase invalid')
        _require(self.native_jobs_result == 'success', 'native matrix did not succeed')


def archive_name(platform: str, expected: ExpectedRun) -> str:
    return f'native-wheel-proposal-{platform}-py{HOSTS[platform]["python_version"]}-{expected.run_id}-{expected.run_attempt}.zip'


def _version_layout(root: Path, phase: str) -> dict[str, str]:
    result = {platform: host['seed'] for platform, host in HOSTS.items()}
    if phase == 'require-committed':
        arm = 'constraints/requirements-macos-arm64-py312.lock'
        intel = 'constraints/requirements-macos-x64-py312.lock'
        existence = ((root / arm).exists(), (root / intel).exists())
        _require(existence[0] == existence[1], 'partial explicit Mac lock pair forbidden')
        if existence[0]:
            result['macos-arm64'], result['macos-x64'] = arm, intel
    return result


def _source_names(platform: str, expected: ExpectedRun, layout: Mapping[str, str]) -> set[str]:
    names = set(SOURCE_HELPERS) | set(REQUIREMENT_ROOTS) | {WORKFLOW_PATH, layout[platform]}
    if expected.phase == 'require-committed':
        names.update(host['companion'] for host in HOSTS.values())
        names.update(layout.values())
    return names


def _authored_roots(sources: Mapping[str, bytes], pins: Mapping[str, str]) -> None:
    _require(sources['requirements-lock.in'].decode('utf-8').splitlines() == ['-r requirements-bootstrap.txt', '-r requirements.txt', '-r requirements-tooling.txt'], 'authored requirement graph changed')
    for path in REQUIREMENT_ROOTS[:3]:
        text = sources[path].decode('utf-8')
        for line in text.splitlines():
            value = line.split('#', 1)[0].strip()
            if not value:
                continue
            value = re.sub(r'\[[A-Za-z0-9,_.-]+\](?=\s*==)', '', value)
            match = _PIN.fullmatch(value)
            _require(match is not None, 'authored requirement is not exact pin')
            assert match is not None
            _require(pins.get(normalize_name(match[1])) == match[2], 'candidate drifted from authored requirement root')


def _inspect_proposal(path: Path, platform: str, expected: ExpectedRun, layout: Mapping[str, str], source_snapshot: Mapping[str, bytes]) -> dict[str, Any]:
    sources = {name: source_snapshot[name] for name in sorted(_source_names(platform, expected, layout))}
    native = native_tuple(platform)
    identity = {'repository': expected.repository, 'source_sha': expected.source_sha, 'run_id': expected.run_id, 'run_attempt': expected.run_attempt, 'platform': platform}
    seed_path = layout[platform]
    with _regular_file(path, MAX_ARCHIVE_BYTES) as (stream, initial):
        raw_digest = hashlib.sha256()
        remaining = initial.st_size
        while remaining:
            chunk = stream.read(min(READ_CHUNK_BYTES, remaining))
            _require(bool(chunk), 'outer archive truncated during fixed-size hashing')
            remaining -= len(chunk)
            raw_digest.update(chunk)
        _require(not stream.read(1), 'outer archive grew beyond captured size')
        _require(_stat_key(os.fstat(stream.fileno())) == _stat_key(initial), 'outer archive changed during hashing')
        stream.seek(0)
        with zipfile.ZipFile(cast(Any, _BoundedReader(stream, initial.st_size))) as archive:
            members = _zip_members(archive, maximum=MAX_OUTER_MEMBERS, total_limit=MAX_TOTAL_BYTES)
            _require(all(name in members and not members[name].is_dir() for name in POSITIVE_MEMBERS), 'proposal required file missing')
            contents = {name: _member_bytes(archive, members[name], MAX_LOCK_BYTES if name.endswith('.lock') else MAX_JSON_BYTES) for name in POSITIVE_MEMBERS}
            proposal = _object(parse_json(contents['proposal.json'], 'proposal'), ('schema_version', 'kind', 'status', 'phase', 'identity', 'native', 'tag_observation', 'files', 'phases', 'counts'), 'proposal')
            _require(type(proposal['schema_version']) is int and proposal['schema_version'] == 1 and proposal['kind'] == 'native-wheel-proposal' and proposal['status'] == 'verified' and proposal['phase'] == expected.phase, 'proposal status/schema/phase invalid')
            _object(proposal['identity'], tuple(identity), 'proposal identity')
            _integer(proposal['identity']['run_id'], 'artifact run id', positive=True)
            _integer(proposal['identity']['run_attempt'], 'artifact attempt', positive=True)
            _object(proposal['native'], tuple(native), 'proposal native')
            _require(proposal['identity'] == identity and proposal['native'] == native, 'proposal source/run/attempt/native mismatch')
            source_bindings = _object(parse_json(contents['inputs/source-bindings.json'], 'source bindings'), ('schema_version', 'files'), 'source bindings')
            _require(type(source_bindings['schema_version']) is int and source_bindings['schema_version'] == 1, 'source bindings schema invalid')
            _file_records(source_bindings['files'], {name: _file_record(content) for name, content in sources.items()}, 'source bindings')
            _require(contents['inputs/seed.lock'] == sources[seed_path], 'seed bytes do not match trusted source')
            candidate = contents['candidate/version.lock']
            _require(candidate == contents['selfhost/version.lock'], 'candidate/selfhost raw bytes differ')
            pins = parse_version_lock(candidate)
            _authored_roots(sources, pins)
            header = f'#\n# This file is autogenerated by pip-compile with Python 3.12\n# by the following command:\n#\n#    {canonical_compile_command(seed_path)}\n#\n'.encode()
            _require(candidate.startswith(header), 'canonical compile header changed')
            observation = _tag_observation(proposal['tag_observation'], pins)
            first = _inventory(parse_json(contents['downloads/first-wheel-inventory.json'], 'first inventory'), identity, native, candidate, pins, observation)
            second = _inventory(parse_json(contents['downloads/second-wheel-inventory.json'], 'second inventory'), identity, native, candidate, pins, observation)
            _require(first == second and contents['downloads/first-wheel-inventory.json'] == contents['downloads/second-wheel-inventory.json'], 'two independent wheel observations differ')
            hashes = {row['name']: row['sha256'] for row in first}
            companion = canonical_companion(pins, hashes)
            _require(contents['candidate/companion.wheels.lock'] == companion == contents['downloads/second-companion.wheels.lock'], 'companion bytes differ from actual wheel/pin projection')
            expected_files = set(POSITIVE_MEMBERS) | {f'wheelhouse/{row["filename"]}' for row in first}
            allowed_dirs = {ancestor for name in expected_files for ancestor in _ancestors(name)}
            _require(set(members) == expected_files | {name for name, info in members.items() if info.is_dir() and name in allowed_dirs}, 'proposal ZIP has undeclared file/directory')
            records = {name: _file_record(content) for name, content in contents.items() if name != 'proposal.json'}
            for row in first:
                name = f'wheelhouse/{row["filename"]}'
                info = members[name]
                _require(not info.is_dir() and info.file_size == row['size'] and info.file_size <= MAX_WHEEL_BYTES, 'actual wheel size mismatch')
                actual_digest = _member_digest(archive, info)
                _require(actual_digest == row['sha256'], 'actual wheel SHA256 mismatch')
                records[name] = {'sha256': actual_digest, 'bytes': info.file_size}
                with archive.open(info) as wheel_stream:
                    wheel = inspect_wheel(cast(BinaryIO, wheel_stream), info.file_size, row['filename'])
                _require(wheel['name'] == row['name'] and wheel['version'] == row['version'] and wheel['tags'] == row['tags'], 'actual wheel metadata mismatch')
                if row['name'] == 'packaging':
                    _require(all(wheel[key] == observation[key] for key in ('packaging_tags_sha256', 'packaging_utils_sha256')), 'native Packaging observation source differs from selected wheel')
            _file_records(proposal['files'], records, 'proposal files')
            bootstrap = sources['requirements-bootstrap.txt']
            current_preflight = _preflight(parse_json(contents['receipts/current-preflight.json'], 'current preflight'), bootstrap, sources[seed_path])
            current_generator = _receipt(parse_json(contents['receipts/current-generator.json'], 'current generator'), bootstrap, sources[seed_path], native, mode='subset')
            _require(current_preflight == current_generator, 'current preflight/generator paths mismatch')
            candidate_preflight = _preflight(parse_json(contents['receipts/candidate-preflight.json'], 'candidate preflight'), bootstrap, candidate)
            candidate_paths = [_receipt(parse_json(contents[name], name), bootstrap, candidate, native, mode='complete') for name in ('receipts/candidate-generator.json', 'receipts/fresh-1.json', 'receipts/fresh-2.json')]
            _require(all(value == candidate_preflight for value in candidate_paths) and current_preflight[0] == candidate_preflight[0], 'candidate original receipt paths mismatch')
            _require(contents['receipts/fresh-1.json'] == contents['receipts/fresh-2.json'], 'fresh schema2 normalized receipt bytes differ')
            raw_commands = contents['logs/commands.jsonl']
            _require(raw_commands.endswith(b'\n') and b'\r' not in raw_commands, 'command journal must be LF JSONL')
            commands = [parse_json(line, 'command row') for line in raw_commands.splitlines()]
            _command_policy(commands, _list(proposal['phases'], 'phases'), seed_path, native, candidate_preflight[0], current_preflight[1], candidate_preflight[1])
            counts = _object(proposal['counts'], ('pins', 'wheels', 'commands'), 'counts')
            for key, value in (('pins', len(pins)), ('wheels', len(first)), ('commands', len(commands))):
                _require(_integer(counts[key], 'proof count', positive=True) == value, 'proof count mismatch')
            if expected.phase == 'require-committed':
                _require(candidate == sources[seed_path], 'candidate differs from chosen committed native version lock')
                _require(companion == sources[HOSTS[platform]['companion']], 'candidate companion differs from committed architecture companion')
            return {'platform': platform, 'identity': identity, 'native': native, 'archive': {'name': path.name, 'bytes': initial.st_size, 'sha256': raw_digest.hexdigest()}, 'candidate_sha256': sha256(candidate), 'companion_sha256': sha256(companion), 'pins': len(pins), 'wheels': len(first), 'commands': len(commands), 'source_bindings': source_bindings['files'], 'version_path': seed_path, 'second_wheelhouse_observation': 'source-bound native inventory; only first original wheelhouse archived', 'candidate_bytes': candidate}


def validate_proposals(artifact_root: Path, source_root: Path, expected: ExpectedRun) -> dict[str, Any]:
    expected.validate()
    _require(artifact_root.is_dir() and not artifact_root.is_symlink(), 'artifact root must be physical directory')
    layout = _version_layout(source_root, expected.phase)
    expected_paths = {artifact_root / platform / archive_name(platform, expected) for platform in HOSTS}
    actual: set[Path] = set()
    for item in artifact_root.iterdir():
        _require(item.name in HOSTS and item.is_dir() and not item.is_symlink(), 'unexpected artifact platform entry')
        for child in item.iterdir():
            _require(child.is_file() and not child.is_symlink(), 'artifact platform entry is not regular archive')
            actual.add(child)
    _require(actual == expected_paths, 'expected exactly four named original proposal archives')
    source_names: set[str] = set()
    for platform in HOSTS:
        source_names.update(_source_names(platform, expected, layout))
    if expected.phase == 'discover' or layout['macos-arm64'] == layout['macos-x64']:
        source_names.add('constraints/requirements-macos-py312.lock')
    source_snapshot = {name: _source_bytes(source_root, name) for name in sorted(source_names)}
    summaries = [_inspect_proposal(artifact_root / platform / archive_name(platform, expected), platform, expected, layout, source_snapshot) for platform in HOSTS]
    by_platform = {summary['platform']: summary for summary in summaries}
    mac_equal = by_platform['macos-arm64']['candidate_bytes'] == by_platform['macos-x64']['candidate_bytes']
    neutral = source_snapshot.get('constraints/requirements-macos-py312.lock')
    shared_proven = neutral is not None and mac_equal and by_platform['macos-arm64']['candidate_bytes'] == neutral
    mac_relation = 'shared-neutral-proven' if shared_proven else 'explicit-split-needed-or-unreviewed-common-drift'
    if expected.phase == 'require-committed':
        if layout['macos-arm64'] == layout['macos-x64']:
            _require(shared_proven, 'committed shared Mac layout lacks actual native equality')
        else:
            mac_relation = 'explicit-arm64-x64-committed-and-proven'
    for name, content in source_snapshot.items():
        _require(_source_bytes(source_root, name) == content, 'trusted source changed during aggregate validation')
    for summary in summaries:
        del summary['candidate_bytes']
    return {'schema_version': 1, 'kind': 'native-wheel-proposal-acceptance', 'status': 'verified', 'phase': expected.phase, 'repository': expected.repository, 'source_sha': expected.source_sha, 'run_id': expected.run_id, 'run_attempt': expected.run_attempt, 'native_jobs_result': expected.native_jobs_result, 'platforms': summaries, 'macos_layout': mac_relation, 'native_job_authentication': 'external trusted workflow/API audit; artifact JSON alone does not authenticate execution', 'discovery_establishes_committed_four_way_policy': False if expected.phase == 'discover' else True}


_PUBLICATION_HELPERS = ('scripts/_anchored_output.py', 'scripts/_anchored_receipt_posix.py', 'scripts/_anchored_receipt_windows.py')


def _publication_snapshot(source_root: Path) -> dict[str, bytes]:
    return {name: _source_bytes(source_root, name) for name in _PUBLICATION_HELPERS}


def _publish(source_root: Path, output: Path, value: Mapping[str, Any], snapshot: Mapping[str, bytes] | None = None) -> None:
    """Execute a private copy of previously validated source-owned helper bytes.

    Original source paths are never used as a later module execution target.
    The private copy includes both exact sibling backends, without altering them.
    """
    sources = _publication_snapshot(source_root) if snapshot is None else snapshot
    _require(set(sources) == set(_PUBLICATION_HELPERS), 'publication snapshot helper set mismatch')
    if value.get('status') == 'verified':
        for platform in value['platforms']:
            for name, content in sources.items():
                _require(platform['source_bindings'][name] == _file_record(content), 'publication helper differs from validated source bytes')
    temporary = tempfile.TemporaryDirectory(prefix='gm2godot-proposal-publication-')
    name = '_gm2godot_native_proposal_anchored_' + os.urandom(12).hex()
    primary: BaseException | None = None
    try:
        directory = Path(temporary.name).resolve(strict=True)
        for relative, content in sources.items():
            path = directory / Path(relative).name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
        module_path = directory / '_anchored_output.py'
        spec = importlib.util.spec_from_file_location(name, module_path)
        _require(spec is not None, 'cannot create exact publication snapshot module')
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(sources['scripts/_anchored_output.py'], str(module_path), 'exec'), module.__dict__)
        publish = cast(Callable[[Path, bytes], None], getattr(module, 'publish_identical_receipt_bytes'))
        content = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
        publish(output, content)
    except BaseException as error:
        primary = error
        raise
    finally:
        for key in tuple(sys.modules):
            if key == name or key.startswith(name + '__anchored_receipt_'):
                sys.modules.pop(key, None)
        try:
            temporary.cleanup()
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note(f'Private publication snapshot cleanup failed: {str(error)[:512]}')


def _diagnostic(error: BaseException) -> None:
    print(f'native-wheel-proposal: {type(error).__name__}: {str(error)[:512]}', file=sys.stderr)
    if error.__cause__ is not None:
        print(f'Cause: {type(error.__cause__).__name__}: {str(error.__cause__)[:512]}', file=sys.stderr)
    notes = getattr(error, '__notes__', ())
    for note in notes[:8]:
        print(f'Note: {str(note)[:512]}', file=sys.stderr)
    if len(notes) > 8:
        print('Further notes omitted.', file=sys.stderr)
    print('An immutable candidate or prior identical receipt may remain; inspect the output paths.', file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('artifact-root', 'source-root', 'repository', 'source-sha', 'phase', 'native-jobs-result', 'output'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    args = parser.parse_args(argv)
    root, output = Path(args.source_root), Path(args.output)
    expected = ExpectedRun(args.repository, args.source_sha, args.run_id, args.run_attempt, args.phase, args.native_jobs_result)
    snapshot: Mapping[str, bytes] | None = None
    try:
        snapshot = _publication_snapshot(root)
        receipt = validate_proposals(Path(args.artifact_root), root, expected)
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        _diagnostic(error)
        failure = {'schema_version': 1, 'kind': 'native-wheel-proposal-acceptance', 'status': 'failed', 'phase': args.phase, 'repository': args.repository, 'source_sha': args.source_sha, 'run_id': args.run_id, 'run_attempt': args.run_attempt, 'error': {'type': type(error).__name__, 'message': str(error)[:512]}}
        try:
            _require(snapshot is not None, 'no trusted publication snapshot available')
            _publish(root, output.with_name(output.name + '.failed.json'), failure, snapshot)
        except (Exception, KeyboardInterrupt, SystemExit) as write_error:
            _diagnostic(write_error)
        return 2
    try:
        _publish(root, output, receipt, snapshot)
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        _diagnostic(error)
        return 2
    print(f'Verified four original native proposal archives: {output}')
    return 0


if __name__ == '__main__':
    if not sys.flags.isolated:
        print('native wheel proposal validation requires Python isolated mode (-I)', file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
