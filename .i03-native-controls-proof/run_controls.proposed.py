"""Proposal: exactly eleven isolated controls for one literal I03 Windows step."""
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / 'bound-inputs.json'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
INPUT_SHA = os.environ['I03_CONTROL_INPUT_SHA']
assert sha(INPUT_PATH) == INPUT_SHA
INPUT = json.loads(INPUT_PATH.read_text())
assert INPUT['ready_for_launch'] is True, 'Unbound proposal: no execution authorized'
assert list(INPUT['gates']) == ['I03-windows-operations']
GATE_KEY = 'I03-windows-operations'
GATE = INPUT['gates'][GATE_KEY]
assert INPUT['controls'] == ['collection', 'missing_id', 'deleted_id', 'skip', 'wrong_cwd', 'wrong_prefix',
                             'wrong_interpreter', 'wrong_runtime', 'foreign_production', 'foreign_test', 'foreign_loader']
ROOT = Path(INPUT['root']).resolve()
INDEX_PATH = HERE / 'review-files.json'
INDEX_BYTES = INDEX_PATH.read_bytes()
INDEX = json.loads(INDEX_BYTES)
assert hashlib.sha256(INDEX_BYTES).hexdigest() == os.environ['I03_CONTROL_REVIEW_SHA']


def verify():
    assert sha(INPUT_PATH) == INPUT_SHA and INDEX_PATH.read_bytes() == INDEX_BYTES
    assert all(sha(HERE / name) == digest for name, digest in INDEX['files'].items())
    assert Path.cwd().resolve() == ROOT and Path(sys.executable).resolve() == Path(INPUT['python']).resolve()
    assert Path(sys.prefix).resolve() == Path(INPUT['prefix']).resolve()
    assert [platform.python_version(), sys.platform, platform.machine()] == INPUT['runtime']
    assert sha(Path(INPUT['python'])) == INPUT['executable_sha256']
    assert sha(Path(INPUT['alternate_python'])) == INPUT['alternate_executable_sha256']
    assert sha(Path(INPUT['prefix']) / 'pyvenv.cfg') == INPUT['pyvenv_cfg_sha256']
    assert subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip() == INPUT['head']
    assert subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD^{tree}'], text=True).strip() == INPUT['tree']
    assert sha(ROOT / '.github/workflows/tests.yml') == INPUT['workflow_sha256']
    assert all(sha(ROOT / name) == digest for name, digest in INPUT['source_hashes'].items())


verify()
PROOF = HERE / 'proof'
PROOF.mkdir()
results = []
for control in INPUT['controls']:
    verify()
    receipt, log = PROOF / (control + '.json'), PROOF / (control + '.log')
    interpreter = INPUT['alternate_python'] if control == 'wrong_interpreter' else INPUT['python']
    cwd = HERE if control == 'wrong_cwd' else ROOT
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONNOUSERSITE='1', PYTHONIOENCODING='utf-8')
    with log.open('x', encoding='utf-8') as stream:
        completed = subprocess.run([interpreter, '-B', '-I', str(HERE / 'control_worker.proposed.py'),
                                    GATE_KEY, control, str(receipt)], cwd=cwd, env=environment,
                                   stdout=stream, stderr=subprocess.STDOUT)
    verify()
    actual = json.loads(receipt.read_text())
    assert actual['exit_code'] == completed.returncode and actual['head'] == INPUT['head'] and actual['tree'] == INPUT['tree']
    assert actual['gate'] == GATE_KEY and actual['control'] == control
    assert Path(actual['actual_python']).resolve() == Path(interpreter).resolve()
    assert Path(actual['actual_cwd']).resolve() == cwd
    expected_prefix = INPUT['base_prefix'] if control == 'wrong_interpreter' else INPUT['prefix']
    assert Path(actual['actual_prefix']).resolve() == Path(expected_prefix).resolve()
    assert actual['actual_runtime_after_control'] == INPUT['runtime']
    assert actual['worker_sha256'] == sha(HERE / 'control_worker.proposed.py') and actual['input_sha256'] == INPUT_SHA
    assert actual['review_index_sha256'] == hashlib.sha256(INDEX_BYTES).hexdigest()
    assert actual['original_native_body_sha256'] == GATE['sha256']
    assert actual['actual_sources_before'] == actual['actual_sources_after'] == INPUT['source_hashes']
    records = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.startswith('{')]
    if control == 'collection':
        assert completed.returncode == 0 and actual['exception'] is None and actual['unittest_outcomes'] is None
        assert records == [{'collection_only': 34, 'selected_ids': GATE['ids']}]
        assert [row['id'] for row in actual['method_origins']] == GATE['ids']
    elif control == 'skip':
        assert completed.returncode == 1 and actual['exception'] is None
        assert len(records) == 1 and records[0]['tests_run'] == 34
        assert records[0]['selected_ids'] == GATE['ids'] and records[0]['skip_count'] == 1 and records[0]['accepted'] is False
        assert actual['unittest_outcomes'] == {'tests_run': 34,
            'skipped': [[GATE['ids'][0], 'I03 induced skip control']], 'failures': [], 'errors': [],
            'unexpected_successes': [], 'expected_failures': []}
        assert actual['skip_callable_and_code_identity_retained'] is True
        assert [row['id'] for row in actual['method_origins']] == GATE['ids']
    else:
        guard = 'collection' if control in ('missing_id', 'deleted_id') else 'origin' if control.startswith('foreign_') else 'runtime' if control == 'wrong_runtime' else 'prefix'
        assert completed.returncode == 1 and actual['exception']['type'] == 'AssertionError'
        assert actual['exception']['last_file'] == '<I03 ' + GATE_KEY + ' ' + control + '>'
        assert actual['exception']['last_line'] == GATE['guard_lines'][guard]
        assert actual['unittest_outcomes'] is None and not records
        if control in INPUT['foreign']:
            foreign = INPUT['foreign'][control]
            assert actual['foreign_origin']['module'] == foreign['module']
            assert Path(actual['foreign_origin']['actual_file']).resolve() == (HERE / foreign['package_path']).resolve()
            assert actual['foreign_origin']['sha256'] == foreign['sha256']
    results.append({'gate': GATE_KEY, 'control': control, 'receipt': str(receipt), 'log': str(log),
                    'receipt_sha256': sha(receipt), 'log_sha256': sha(log), 'exit_code': completed.returncode})
verify()
with (PROOF / 'summary.json').open('x') as stream:
    stream.write(json.dumps({'head': INPUT['head'], 'tree': INPUT['tree'], 'control_count': 11, 'results': results,
        'input_sha256': INPUT_SHA, 'worker_sha256': sha(HERE / 'control_worker.proposed.py'),
        'controller_sha256': sha(Path(__file__)), 'review_index_sha256': hashlib.sha256(INDEX_BYTES).hexdigest(),
        'native_positive_credit': False, 'host_adapter_used': False,
        'limit': 'One intact collection and ten causal refusals. The distinct 34/34 native step remains required.'}, indent=2) + '\n')
print('I03 finite native invocation controls passed:', len(results))
