from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable, cast

from scripts import conversion_parity_contract as contract
from scripts import conversion_parity_snapshot as snapshots


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n').encode()


def _digest(content: bytes) -> str:
    return 'sha256:' + hashlib.sha256(content).hexdigest()


def _identity(number: int) -> list[str]:
    return [f'{number:032x}', f'{number + 1:032x}']


def _definition() -> contract.DestinationDefinition:
    return contract.load_parity_definition(Path(__file__).resolve().parents[1] / 'architecture-verification.json', 'R01').destination


def _fixture(token: str = 'a', offset: int = 0, directory: str = 'scripts') -> tuple[dict[str, tuple[int, bytes]], dict[str, object]]:
    """Build independent wire records, without production schema/validation imports."""
    transaction_id = token * 32
    root = '.gm2godot-managed-output/'
    files = {
        'project.godot': (0o644, b'[application]\nconfig/name="desired"\n'),
        f'{directory}/sample.gd': (0o644, b'extends Node\n'),
        'gm2godot/architecture_policy.json': (0o644, _json({})),
        'gm2godot/conversion_diagnostics.json': (0o644, _json({'diagnostics': []})),
    }
    entries: list[dict[str, object]] = []
    for path, (mode, content) in sorted(files.items()):
        entries.append({'path': path, 'mode': mode, 'byte_count': len(content), 'sha256': _digest(content),
                        'kind': 'project' if path == 'project.godot' else 'gdscript' if path.endswith('.gd') else 'report',
                        'owner': {'class': 'converter_step' if path.endswith('.gd') else 'shared_owner',
                                  'name': directory if path.endswith('.gd') else 'project_configuration' if path == 'project.godot' else 'conversion_evidence'}})
    inventory = {'format_version': 1, 'entries': entries}
    manifest = _json({'format_version': 2, 'generation_inventory': inventory})
    attempt = _json({'format_version': 1, 'canonical_manifest': {'path': 'gm2godot/conversion_manifest.json',
                    'status': 'updated', 'updated': True, 'current_output': 'verified', 'sha256': _digest(manifest)}})
    files.update({'gm2godot/conversion_manifest.json': (0o644, manifest), 'gm2godot/conversion_attempt.json': (0o644, attempt)})
    public_ids = {path: _identity(offset + index + 100) for index, path in enumerate(sorted(files))}
    destination_id, parent_id, previous_id = _identity(offset + 10), _identity(offset + 20), _identity(offset + 200)
    seed = b'[application]\nconfig/name="seed"\n'
    old_entry = {**next(entry for entry in entries if entry['path'] == 'project.godot'), 'byte_count': len(seed), 'sha256': _digest(seed)}
    evidence = {}
    absent = {}
    for kind in ('attempt', 'manifest'):
        path = f'gm2godot/conversion_{kind}.json'
        content = files[path][1]
        evidence[kind] = {'path': path, 'present': True, 'identity': public_ids[path], 'mode': 0o644, 'byte_count': len(content), 'sha256': _digest(content)}
        absent[kind] = {'path': path, 'present': False, 'identity': None, 'mode': None, 'byte_count': 0, 'sha256': None}
    desired = {'format_version': 1, 'kind': 'gm2godot-managed-output-generation-record', 'transaction_id': transaction_id,
               'role': 'desired', 'destination_identity': destination_id, 'inventory': inventory,
               'managed_identities': [[entry['path'], *public_ids[cast(str, entry['path'])]] for entry in entries], 'evidence': evidence}
    previous = {**desired, 'role': 'previous', 'inventory': {'format_version': 1, 'entries': [old_entry]},
                'managed_identities': [['project.godot', *previous_id]], 'evidence': absent}
    observed: dict[str, dict[str, object]] = {}

    def add(name: str, value: object, identifier: int) -> str:
        path = root + name
        observed[path] = {'mode': 0o600, 'identity': _identity(offset + identifier), 'bytes_hex': _json(value).hex()}
        return path

    desired_path = add(f'.gm2godot-managed-output-generation-{transaction_id}-desired.json', desired, 30)
    previous_path = add(f'.gm2godot-managed-output-generation-{transaction_id}-previous.json', previous, 40)

    def reference(path: str) -> dict[str, object]:
        metadata = observed[path]
        content = bytes.fromhex(cast(str, metadata['bytes_hex']))
        return {'name': path.removeprefix(root), 'identity': metadata['identity'], 'mode': metadata['mode'],
                'byte_count': len(content), 'sha256': _digest(content)}

    directory_ids = {path: _identity(offset + 300 + index) for index, path in enumerate(sorted({'gm2godot', directory}))}
    transitions: list[dict[str, object]] = []
    backups: dict[str, dict[str, object]] = {}
    for path, (mode, content) in sorted(files.items()):
        kind = 'attempt' if path.endswith('conversion_attempt.json') else 'manifest' if path.endswith('conversion_manifest.json') else 'managed'
        suffix = path if kind == 'managed' else f'conversion_{kind}.json'
        backup_path = f'.gm2godot-publication/backups/{suffix}'
        stage_path = path if kind == 'managed' else f'.gm2godot-publication/evidence/desired-{kind}.json'
        receipt = {'mode': mode, 'byte_count': len(content), 'sha256': _digest(content)}
        old = {'mode': 0o644, 'byte_count': len(seed), 'sha256': _digest(seed)} if path == 'project.godot' else None
        backup_id = _identity(offset + 400)
        backup = None if old is None else {'path': backup_path, 'identity': backup_id, **old}
        if backup is not None:
            backups[backup_path] = {'mode': 0o644, 'identity': backup_id, 'bytes_hex': seed.hex()}
        transitions.append({'path': path, 'kind': kind, 'previous': old, 'desired': receipt,
                            'previous_public_identity': previous_id if old else None, 'backup': backup,
                            'desired_stage': {'path': stage_path, 'identity': public_ids[path], **receipt},
                            'backup_path': backup_path, 'desired_stage_path': stage_path,
                            'displaced_path': f'.gm2godot-publication/displaced/{suffix}'})
    transitions.sort(key=lambda row: ({'managed': 0, 'attempt': 1, 'manifest': 2}[cast(str, row['kind'])], cast(str, row['path'])))
    journal = {'format_version': 1, 'kind': 'gm2godot-managed-output-transaction', 'state': 'prepared',
               'transaction_id': transaction_id, 'destination_identity': destination_id, 'workspace_parent_identity': parent_id,
               'stage_identity': _identity(offset + 60), 'publication_identity': _identity(offset + 70),
               'pointer_stage_identity': _identity(offset + 50), 'previous_record': reference(previous_path),
               'desired_record': reference(desired_path), 'previous_pointer': None,
               'directories': [{'path': path, 'disposition': 'staged', 'identity': identity, 'mode': 0o755,
                                'stage_path': f'.gm2godot-publication/directories/{path}'} for path, identity in directory_ids.items()],
               'transitions': transitions}
    add('.gm2godot-managed-output-transaction.json', journal, 80)
    pointer_path = add('.gm2godot-managed-output-generation.json', {'format_version': 1, 'kind': 'gm2godot-managed-output-generation',
                       'state': 'committed', 'transaction_id': transaction_id, 'destination_identity': destination_id,
                       'journal_sha256': _digest(_json(journal)), 'generation_record': reference(desired_path)}, 50)
    marker_path = add('.gm2godot-workspace-parent.json', {'format_version': 1, 'kind': 'gm2godot-managed-output-workspace-parent',
                      'destination_identity': destination_id, 'parent_identity': parent_id}, 90)
    marker_value = json.loads(bytes.fromhex(cast(str, observed[marker_path]['bytes_hex'])))
    observed[marker_path]['bytes_hex'] = (json.dumps(marker_value, sort_keys=True, separators=(',', ':')) + '\n').encode().hex()
    for path in (desired_path, pointer_path, marker_path):
        files[path] = (0o600, bytes.fromhex(cast(str, observed[path]['bytes_hex'])))
        public_ids[path] = cast(list[str], observed[path]['identity'])
    files['.gm2godot-managed-output.lock'] = (0o600, b'')
    return files, {'destination_identity': destination_id, 'parent_identity': parent_id, 'stage_identity': journal['stage_identity'],
                   'publication_identity': journal['publication_identity'], 'files': observed, 'public_identities': public_ids,
                   'directory_identities': directory_ids, 'directory_modes': {path: 0o755 for path in directory_ids}, 'backup_files': backups}


def _rewrite(files: dict[str, tuple[int, bytes]], observation: dict[str, object], target: str,
             mutation: Callable[[dict[str, object]], None], *, rebind: bool = True) -> None:
    metadata = cast(dict[str, dict[str, object]], observation['files'])
    records: dict[str, dict[str, object]] = {path: json.loads(bytes.fromhex(cast(str, value['bytes_hex']))) for path, value in metadata.items()}
    names = {'pointer': next(path for path in records if path.endswith('/.gm2godot-managed-output-generation.json')),
             'journal': next(path for path in records if path.endswith('-transaction.json')),
             'desired': next(path for path in records if path.endswith('-desired.json')),
             'previous': next(path for path in records if path.endswith('-previous.json'))}
    mutation(records[names[target]])
    if rebind:
        journal = records[names['journal']]
        for role in ('desired', 'previous'):
            content = _json(records[names[role]])
            cast(dict[str, object], journal[f'{role}_record']).update({'byte_count': len(content), 'sha256': _digest(content)})
        records[names['pointer']]['generation_record'] = copy.deepcopy(journal['desired_record'])
        records[names['pointer']]['journal_sha256'] = _digest(_json(journal))
    for path, record in records.items():
        content = (json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode() if path.endswith('/.gm2godot-workspace-parent.json') else _json(record)
        metadata[path]['bytes_hex'] = content.hex()
        if path in files:
            files[path] = (files[path][0], content)


def _run(files: dict[str, tuple[int, bytes]], observation: dict[str, object] | None) -> snapshots.FixtureRun:
    snapshot = snapshots.output_snapshot(files, destination=Path('/same'), definition=_definition(), stdout='', stderr='',
                                         exit_status=0, parser_error={}, runtime_markers={}, publication_observation=observation)
    return snapshots.FixtureRun('/same', files, snapshot)


class TestConversionParitySnapshot(unittest.TestCase):
    def test_only_authenticated_ids_and_bound_digests_are_normalized(self) -> None:
        base, head = _run(*_fixture()), _run(*_fixture('b', 10000))
        self.assertEqual(snapshots.compare_fixture_runs(base, head, ('transaction_provenance',)), {})
        provenance = cast(dict[str, object], base.snapshot['transaction_provenance'])
        self.assertTrue(provenance['validated'])
        self.assertIn('a' * 32, json.dumps(provenance['raw']))
        self.assertIn('.gm2godot-managed-output/.gm2godot-managed-output-generation-<transaction-id>-desired.json', json.dumps(provenance['semantics']))
        self.assertIn('scripts/sample.gd', json.dumps(provenance['semantics']))
        self.assertNotEqual(provenance['raw'], cast(dict[str, object], head.snapshot['transaction_provenance'])['raw'])

    def test_same_length_managed_paths_and_stable_record_modes_remain_visible(self) -> None:
        base, head = _run(*_fixture()), _run(*_fixture('b', 10000, 'objects'))
        self.assertIn('transaction_provenance', snapshots.compare_fixture_runs(base, head, ('transaction_provenance',)))
        files, observation = _fixture('b', 10000)
        files['.gm2godot-managed-output.lock'] = (0o644, b'')
        self.assertIn('transaction_provenance', snapshots.compare_fixture_runs(base, _run(files, observation), ('transaction_provenance',)))

    def test_unobserved_provenance_and_destination_mismatch_fail_closed(self) -> None:
        files, _observation = _fixture()
        run = _run(files, None)
        with self.assertRaisesRegex(contract.ParityError, 'authenticated publication'):
            snapshots.compare_fixture_runs(run, run, ('transaction_provenance',))
        with self.assertRaisesRegex(contract.ParityError, 'Destination mismatch'):
            snapshots.compare_fixture_runs(run, snapshots.FixtureRun('/other', files, run.snapshot), ('stdout',))

    def test_pointer_digest_name_identity_and_byte_receipts_are_authenticated(self) -> None:
        mutations: tuple[Callable[[dict[str, object]], None], ...] = (
            lambda record: record.update({'journal_sha256': 'sha256:' + '0' * 64}),
            lambda record: record.update({'format_version': True}),
            lambda record: record.update({'transaction_id': 'b' * 32}),
            lambda record: cast(dict[str, object], record['generation_record']).update({'name': '.gm2godot-managed-output-generation-' + 'b' * 32 + '-desired.json'}),
            lambda record: cast(dict[str, object], record['generation_record']).update({'identity': _identity(9900)}),
            lambda record: cast(dict[str, object], record['generation_record']).update({'mode': 0o644}),
            lambda record: cast(dict[str, object], record['generation_record']).update({'byte_count': True}),
            lambda record: cast(dict[str, object], record['generation_record']).update({'sha256': 'sha256:' + '0' * 64}),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                files, observation = _fixture()
                _rewrite(files, observation, 'pointer', mutation, rebind=False)
                with self.assertRaises(contract.ParityError):
                    _run(files, observation)

    def test_generation_schema_paths_and_counts_are_checked_before_masking(self) -> None:
        mutations: tuple[Callable[[dict[str, object]], None], ...] = (
            lambda record: record.update({'managed_identities': [['objects/sample.gd', *_identity(1)]]}),
            lambda record: record.update({'destination_identity': {'device': 'bad'}}),
            lambda record: record.update({'format_version': True}),
            lambda record: record.update({'unexpected': 'field'}),
            lambda record: cast(dict[str, object], record['inventory']).update({'format_version': 1.0}),
            lambda record: cast(list[dict[str, object]], cast(dict[str, object], record['inventory'])['entries'])[0].update({'mode': True}),
            lambda record: cast(list[dict[str, object]], cast(dict[str, object], record['inventory'])['entries'])[0].update({'byte_count': False}),
            lambda record: cast(list[dict[str, object]], cast(dict[str, object], record['inventory'])['entries'])[0].update({'kind': 'invented'}),
            lambda record: cast(dict[str, object], cast(list[dict[str, object]], cast(dict[str, object], record['inventory'])['entries'])[0]['owner']).update({'class': 'invented'}),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                files, observation = _fixture()
                _rewrite(files, observation, 'desired', mutation)
                with self.assertRaises(contract.ParityError):
                    _run(files, observation)

    def test_public_inventory_and_evidence_bytes_cannot_drift(self) -> None:
        for path in ('scripts/sample.gd', 'gm2godot/conversion_attempt.json', 'gm2godot/conversion_manifest.json'):
            with self.subTest(path=path):
                files, observation = _fixture()
                files[path] = (files[path][0], b'changed')
                with self.assertRaises(contract.ParityError):
                    _run(files, observation)

    def test_attempt_boolean_and_manifest_inventory_types_are_exact(self) -> None:
        for malformed_manifest in (False, True):
            with self.subTest(malformed_manifest=malformed_manifest):
                files, observation = _fixture()
                attempt_path, manifest_path = 'gm2godot/conversion_attempt.json', 'gm2godot/conversion_manifest.json'
                attempt = cast(dict[str, object], json.loads(files[attempt_path][1]))
                canonical = cast(dict[str, object], attempt['canonical_manifest'])
                if malformed_manifest:
                    manifest = cast(dict[str, object], json.loads(files[manifest_path][1]))
                    cast(dict[str, object], manifest['generation_inventory'])['format_version'] = True
                    files[manifest_path] = (files[manifest_path][0], _json(manifest))
                    canonical['sha256'] = _digest(files[manifest_path][1])
                else:
                    canonical['updated'] = 1
                files[attempt_path] = (files[attempt_path][0], _json(attempt))

                def mutate(record: dict[str, object]) -> None:
                    evidence = cast(dict[str, dict[str, object]], record['evidence'])
                    for kind, path in (('attempt', attempt_path), ('manifest', manifest_path)):
                        evidence[kind].update({'byte_count': len(files[path][1]), 'sha256': _digest(files[path][1])})

                _rewrite(files, observation, 'desired', mutate)
                with self.assertRaisesRegex(contract.ParityError, 'manifest inventory' if malformed_manifest else 'manifest binding'):
                    _run(files, observation)

    def test_journal_stable_paths_backups_and_native_directory_modes_are_bound(self) -> None:
        mutations: tuple[Callable[[dict[str, object]], None], ...] = (
            lambda record: record.update({'previous_pointer': {}}),
            lambda record: record.update({'format_version': True}),
            lambda record: record.update({'pointer_stage_identity': _identity(9900)}),
            lambda record: cast(list[dict[str, object]], record['directories'])[0].update({'mode': True}),
            lambda record: cast(list[dict[str, object]], record['directories'])[0].update({'mode': 0o700}),
            lambda record: cast(list[dict[str, object]], record['directories'])[0].update({'identity': _identity(9900)}),
            lambda record: cast(list[dict[str, object]], record['transitions'])[0].update({'backup_path': 'wrong/path'}),
            lambda record: cast(list[dict[str, object]], record['transitions'])[0].update({'kind': 'manifest'}),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                files, observation = _fixture()
                _rewrite(files, observation, 'journal', mutation)
                with self.assertRaises(contract.ParityError):
                    _run(files, observation)
        files, observation = _fixture()
        backups = cast(dict[str, dict[str, object]], observation['backup_files'])
        backups[next(iter(backups))]['bytes_hex'] = b'wrong'.hex()
        with self.assertRaisesRegex(contract.ParityError, 'backup'):
            _run(files, observation)

    def test_evidence_transition_cannot_be_reclassified_as_managed(self) -> None:
        files, observation = _fixture()

        def mutate(journal: dict[str, object]) -> None:
            row = next(row for row in cast(list[dict[str, object]], journal['transitions']) if row['kind'] == 'attempt')
            path = cast(str, row['path'])
            row.update({'kind': 'managed', 'backup_path': f'.gm2godot-publication/backups/{path}',
                        'desired_stage_path': path, 'displaced_path': f'.gm2godot-publication/displaced/{path}'})
            cast(dict[str, object], row['desired_stage'])['path'] = path

        _rewrite(files, observation, 'journal', mutate)
        with self.assertRaisesRegex(contract.ParityError, 'kind or path'):
            _run(files, observation)

    def test_missing_or_extra_publication_records_are_rejected(self) -> None:
        original, observation = _fixture()
        for path in tuple(path for path in original if path.startswith('.gm2godot-managed-output')):
            with self.subTest(path=path):
                files = dict(original)
                del files[path]
                with self.assertRaises(contract.ParityError):
                    _run(files, observation)
        files = dict(original)
        files['.gm2godot-managed-output/unexpected.json'] = (0o600, b'{}')
        with self.assertRaises(contract.ParityError):
            _run(files, observation)

    def test_success_requires_diagnostics_and_all_terminal_records(self) -> None:
        original, _observation = _fixture()
        for path in ('gm2godot/conversion_diagnostics.json', 'gm2godot/architecture_policy.json', 'gm2godot/conversion_attempt.json', 'gm2godot/conversion_manifest.json'):
            with self.subTest(path=path):
                files = dict(original)
                del files[path]
                with self.assertRaisesRegex(contract.ParityError, 'required output'):
                    snapshots.validate_required_outputs(files)

    def test_unknown_volatile_policy_and_duplicate_json_fields_are_rejected(self) -> None:
        files, observation = _fixture()
        definition = _definition()
        with self.assertRaisesRegex(contract.ParityError, 'volatile'):
            snapshots.output_snapshot(files, destination=Path('/same'), definition=contract.DestinationDefinition(
                '', True, True, definition.transaction_root, definition.transaction_lock,
                (*definition.volatile_transaction_fields, 'inventory')), stdout='', stderr='', exit_status=0,
                parser_error={}, runtime_markers={}, publication_observation=observation)
        with self.assertRaisesRegex(contract.ParityError, 'Duplicate JSON'):
            _run({'gm2godot/conversion_diagnostics.json': (0o644, b'{"diagnostics":[],"diagnostics":[]}')}, None)

    def test_converter_snapshot_precedes_post_boot_cache_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / 'visible.gd').write_text('extends Node\n', encoding='utf-8')
            files = snapshots.collect_output_files(destination)
            (destination / '.godot').mkdir()
            (destination / '.godot/post_boot.cache').write_text('cache', encoding='utf-8')
            self.assertEqual(_run(files, None).snapshot['relative_paths'], ['visible.gd'])

    def test_transaction_root_and_post_cleanup_native_identities_are_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            parent = destination / '.gm2godot-managed-output'
            parent.mkdir()
            observation: dict[str, object] = {'destination_identity': [f'{destination.stat().st_dev:032x}', f'{destination.stat().st_ino:032x}'],
                'parent_identity': [f'{parent.stat().st_dev:032x}', f'{parent.stat().st_ino:032x}'], 'public_identities': {}, 'directory_identities': {}, 'directory_modes': {}}
            snapshots.verify_publication_identities(destination, observation, _definition())
            parent.rename(destination / 'old-parent')
            parent.mkdir()
            with self.assertRaisesRegex(contract.ParityError, 'transaction-root identity'):
                snapshots.verify_publication_identities(destination, observation, _definition())


if __name__ == '__main__':
    unittest.main()
