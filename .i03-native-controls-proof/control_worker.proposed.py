"""Proposal: one isolated I03 collection/refusal control on native Windows only.

No launch until final input/source/runtime/workflow binding and independent/root approval.
This worker does not provide positive native-gate credit.
"""
import hashlib
import importlib.util
import inspect
import json
import os
import platform
import stat
import subprocess
import sys
import traceback
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / 'bound-inputs.json'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
INPUT_SHA = os.environ['I03_CONTROL_INPUT_SHA']
assert sha(INPUT_PATH) == INPUT_SHA
INPUT = json.loads(INPUT_PATH.read_text())
assert INPUT['ready_for_launch'] is True, 'Unbound proposal: no execution authorized'
GATE_KEY, CONTROL, OUTPUT_NAME = sys.argv[1:]
assert list(INPUT['gates']) == ['I03-windows-operations'] and GATE_KEY == 'I03-windows-operations'
assert CONTROL in INPUT['controls'] and len(INPUT['controls']) == 11
GATE = INPUT['gates'][GATE_KEY]
ROOT = Path(INPUT['root']).resolve()
OUTPUT = Path(OUTPUT_NAME).resolve()
assert OUTPUT.parent == HERE / 'proof' and not OUTPUT.exists()
INDEX_PATH = HERE / 'review-files.json'
INDEX_BYTES = INDEX_PATH.read_bytes()
INDEX = json.loads(INDEX_BYTES)
assert hashlib.sha256(INDEX_BYTES).hexdigest() == os.environ['I03_CONTROL_REVIEW_SHA']


def verify():
    assert sha(INPUT_PATH) == INPUT_SHA and INDEX_PATH.read_bytes() == INDEX_BYTES
    assert all(sha(HERE / name) == digest for name, digest in INDEX['files'].items())
    assert subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip() == INPUT['head']
    assert subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD^{tree}'], text=True).strip() == INPUT['tree']
    assert sha(ROOT / '.github/workflows/tests.yml') == INPUT['workflow_sha256']
    actual = {}
    for name, expected in INPUT['source_hashes'].items():
        path = ROOT / name
        assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
        actual[name] = sha(path)
        assert actual[name] == expected
    for row in INPUT['foreign'].values():
        assert sha(HERE / row['package_path']) == row['sha256'] == sha(ROOT / row['source_path'])
    assert sha(HERE / GATE['body']) == GATE['sha256']
    assert sha(Path(INPUT['prefix']) / 'pyvenv.cfg') == INPUT['pyvenv_cfg_sha256']
    expected_python = INPUT['alternate_python'] if CONTROL == 'wrong_interpreter' else INPUT['python']
    expected_sha = INPUT['alternate_executable_sha256'] if CONTROL == 'wrong_interpreter' else INPUT['executable_sha256']
    assert Path(sys.executable).resolve() == Path(expected_python).resolve() and sha(Path(sys.executable)) == expected_sha
    return actual


before_sources = verify()
assert not any(name.split('.')[0] in ('src', 'scripts', 'tests') for name in sys.modules)
sys.path.insert(0, str(ROOT))
CODE = (HERE / GATE['body']).read_text()
ORIGINAL_CODE_SHA = hashlib.sha256(CODE.encode()).hexdigest()
CONTROL_ORIGIN = None
if CONTROL in INPUT['foreign']:
    foreign = INPUT['foreign'][CONTROL]
    path = HERE / foreign['package_path']
    spec = importlib.util.spec_from_file_location(foreign['module'], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[foreign['module']] = module
    spec.loader.exec_module(module)
    assert module.__file__ is not None and Path(module.__file__).resolve() == path.resolve()
    CONTROL_ORIGIN = {'module': foreign['module'], 'actual_file': module.__file__, 'sha256': sha(path)}

# Preserve the actual selected callable and its source origin. No substitute test function.
original_method = original_code = original_class = None
skip_metadata = None
if CONTROL in ('deleted_id', 'skip'):
    from tests.included_files.test_windows_operations import TestIncludedFilesWindowsOperations
    original_class = TestIncludedFilesWindowsOperations
    original_method = vars(original_class)['test_abi_records_preserve_sizes_offsets_and_values']
    original_code = original_method.__code__
    assert Path(inspect.getfile(original_method)).resolve() == ROOT / 'tests/included_files/test_windows_operations.py'
    if CONTROL == 'deleted_id':
        del TestIncludedFilesWindowsOperations.test_abi_records_preserve_sizes_offsets_and_values
    else:
        skip_metadata = {name: (name in vars(original_method), vars(original_method).get(name))
                         for name in ('__unittest_skip__', '__unittest_skip_why__')}
        assert not vars(original_method).get('__unittest_skip__', False)
        original_method.__unittest_skip__ = True
        original_method.__unittest_skip_why__ = 'I03 induced skip control'

if CONTROL == 'missing_id':
    original = '    "' + GATE['ids'][0] + '",'
    assert CODE.count(original) == 1
    CODE = CODE.replace(original, '    "' + GATE['ids'][0] + '_missing",')
if CONTROL == 'collection':
    run_line = 'result = unittest.TextTestRunner(verbosity=2).run(suite)'
    assert CODE.count(run_line) == 1
    CODE = CODE.replace(run_line, 'print(json.dumps({"collection_only": len(discovered), "selected_ids": list(discovered)})); raise SystemExit(0)')

sys.argv = [GATE['body'], str(ROOT), str(HERE / 'wrong-prefix') if CONTROL == 'wrong_prefix' else INPUT['prefix']]
code_name = '<I03 ' + GATE_KEY + ' ' + CONTROL + '>'
exception = None
exit_code = 0
namespace = {'__name__': '__main__'}
machine = patch.object(platform, 'machine', return_value='I03-wrong-machine') if CONTROL == 'wrong_runtime' else nullcontext()
try:
    with machine:
        exec(compile(CODE, code_name, 'exec'), namespace)
except SystemExit as error:
    exit_code = error.code if type(error.code) is int else 0 if error.code is None else 1
except Exception as error:
    frames = traceback.extract_tb(error.__traceback__)
    exception = {'type': type(error).__name__, 'last_file': frames[-1].filename,
                 'last_line': frames[-1].lineno, 'message': str(error)}
    traceback.print_exc()
    exit_code = 1
finally:
    if CONTROL == 'deleted_id':
        assert original_class is not None
        original_class.test_abi_records_preserve_sizes_offsets_and_values = original_method
    if CONTROL == 'skip':
        assert original_method is not None and skip_metadata is not None
        for name, (present, value) in skip_metadata.items():
            if present:
                setattr(original_method, name, value)
            else:
                delattr(original_method, name)
    after_sources = verify()

outcomes = None
method_origins = []
if CONTROL in ('collection', 'skip'):
    for row in INPUT['method_origins']:
        actual_class = vars(sys.modules[row['module']])[row['class']]
        method = inspect.unwrap(vars(actual_class)[row['method']])
        actual_file = Path(inspect.getfile(method)).resolve()
        assert actual_file == ROOT / row['path'] and sha(actual_file) == row['source_sha256']
        method_origins.append({'id': row['id'], 'file': str(actual_file), 'source_sha256': sha(actual_file),
                               'code_file': method.__code__.co_filename, 'first_line': method.__code__.co_firstlineno})
if CONTROL == 'skip':
    assert original_class is not None and original_method is not None
    assert vars(original_class)['test_abi_records_preserve_sizes_offsets_and_values'] is original_method
    assert original_method.__code__ is original_code
    result = namespace['result']
    assert isinstance(result, unittest.TestResult)
    outcomes = {'tests_run': result.testsRun,
                'skipped': [(test.id(), reason) for test, reason in result.skipped],
                'failures': [(test.id(), detail) for test, detail in result.failures],
                'errors': [(test.id(), detail) for test, detail in result.errors],
                'unexpected_successes': [test.id() for test in result.unexpectedSuccesses],
                'expected_failures': [(test.id(), detail) for test, detail in result.expectedFailures]}
record = {'head': INPUT['head'], 'tree': INPUT['tree'], 'gate': GATE_KEY, 'control': CONTROL,
          'exit_code': exit_code, 'exception': exception, 'unittest_outcomes': outcomes,
          'actual_python': sys.executable, 'actual_prefix': sys.prefix, 'actual_cwd': str(Path.cwd()),
          'actual_runtime_after_control': [platform.python_version(), sys.platform, platform.machine()],
          'foreign_origin': CONTROL_ORIGIN, 'method_origins': method_origins,
          'input_sha256': sha(INPUT_PATH), 'worker_sha256': sha(Path(__file__)),
          'review_index_sha256': hashlib.sha256(INDEX_BYTES).hexdigest(),
          'original_native_body_sha256': ORIGINAL_CODE_SHA,
          'executed_control_code_sha256': hashlib.sha256(CODE.encode()).hexdigest(),
          'actual_sources_before': before_sources, 'actual_sources_after': after_sources,
          'skip_callable_and_code_identity_retained': True if CONTROL == 'skip' else None,
          'limit': 'One-gate collection/refusal control only. No host adapter and no positive native gate credit.'}
with OUTPUT.open('x') as stream:
    stream.write(json.dumps(record, indent=2) + '\n')
raise SystemExit(exit_code)
