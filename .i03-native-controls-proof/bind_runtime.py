"""Bind and recheck one temporary Windows proof transport against an immutable I03 source."""
import ast
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRANSPORT = HERE.parent
SPEC_PATH = HERE / 'binding-spec.json'
FINAL_PATH = HERE / 'final-source.json'
PACKAGE_PATH = HERE / 'package-files.json'
SPEC = json.loads(SPEC_PATH.read_bytes())
FINAL = json.loads(FINAL_PATH.read_bytes())
PACKAGE = json.loads(PACKAGE_PATH.read_bytes())
assert FINAL['ready'] is True and FINAL['head'] and FINAL['tree'] and FINAL['files'], 'Final source is not bound'
SOURCE = TRANSPORT / SPEC['source_directory']
WORK = Path(os.environ['RUNNER_TEMP']).resolve() / SPEC['execution_directory']
MODE = sys.argv[1]
assert MODE in ('bind', 'verify')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def body_from(workflow):
    lines = workflow.read_text(encoding='utf-8').splitlines(keepends=True)
    header = '      - name: ' + SPEC['source_positive_step_name'] + '\n'
    assert lines.count(header) == 1
    start = lines.index(header)
    heredoc = next(index for index in range(start + 1, len(lines)) if "<<'PY'" in lines[index])
    end = next(index for index in range(heredoc + 1, len(lines)) if lines[index] == '          PY\n')
    selected = lines[heredoc + 1:end]
    assert all(line.startswith('          ') or not line.strip() for line in selected)
    return ''.join(line[10:] if line.startswith('          ') else '\n' for line in selected).encode()


def snapshot():
    assert Path.cwd().resolve() == SOURCE and Path(os.environ['GITHUB_WORKSPACE']).resolve() == TRANSPORT
    assert os.environ['GITHUB_REF'] == 'refs/heads/' + SPEC['temporary_branch']
    assert HERE.name == SPEC['transport_directory']
    package_names = {'binding-spec.json', 'final-source.json', 'native_windows_step.py', 'bind_runtime.py',
                     'control_worker.proposed.py', 'run_controls.proposed.py'}
    assert set(PACKAGE['files']) == package_names
    assert all(sha(HERE / name) == digest for name, digest in PACKAGE['files'].items())
    assert sha(TRANSPORT / '.github/workflows/tests.yml') == PACKAGE['workflow_sha256']
    transport_head = git(TRANSPORT, 'rev-parse', 'HEAD').decode().strip()
    transport_tree = git(TRANSPORT, 'rev-parse', 'HEAD^{tree}').decode().strip()
    assert transport_head == os.environ['GITHUB_SHA']
    assert git(TRANSPORT, 'rev-list', '--parents', '-n', '1', 'HEAD').decode().split() == [transport_head, FINAL['head']]
    changed = dict((path, status) for status, path in
                   (line.split('\t') for line in git(TRANSPORT, 'diff', '--name-status', FINAL['head'], transport_head).decode().splitlines()))
    expected_changed = {SPEC['transport_directory'] + '/' + name: 'A' for name in package_names | {'package-files.json'}}
    expected_changed['.github/workflows/tests.yml'] = 'M'
    assert changed == expected_changed
    for name in expected_changed:
        path = TRANSPORT / name
        assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
        assert path.read_bytes() == git(TRANSPORT, 'show', transport_head + ':' + name)
    assert git(SOURCE, 'rev-parse', 'HEAD').decode().strip() == FINAL['head']
    assert git(SOURCE, 'rev-parse', 'HEAD^{tree}').decode().strip() == FINAL['tree']
    assert git(SOURCE, 'diff', '--binary', 'HEAD') == b''
    assert set(git(SOURCE, 'ls-files', '-z').decode().strip('\0').split('\0')) == set(FINAL['files'])
    actual_files = {}
    for name, expected in FINAL['files'].items():
        path = SOURCE / name
        assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
        actual_files[name] = sha(path)
        assert actual_files[name] == expected, name
    assert git(SOURCE, 'config', '--get', 'core.autocrlf').decode().strip() == 'false'
    assert git(SOURCE, 'config', '--get', 'core.eol').decode().strip() == 'lf'
    source_workflow = (SOURCE / '.github/workflows/tests.yml').read_text(encoding='utf-8')
    job_start = source_workflow.index('  windows-artifact-transactions:\n')
    setup_start = source_workflow.index('      - name: Set up Python\n', job_start)
    setup_end = source_workflow.index('      - name: Run required native receipt gate\n', setup_start)
    assert hashlib.sha256(source_workflow[setup_start:setup_end].encode()).hexdigest() == SPEC['existing_windows_setup_sha256']
    body = (HERE / 'native_windows_step.py').read_bytes()
    assert body_from(SOURCE / '.github/workflows/tests.yml') == body
    assert body_from(TRANSPORT / '.github/workflows/tests.yml') == body
    assert hashlib.sha256(body).hexdigest() == SPEC['gates']['I03-windows-operations']['sha256']
    assert sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize
    assert os.name == 'nt' and [platform.python_version(), sys.platform, platform.machine()] == SPEC['runtime']
    prefix = Path(os.environ['VIRTUAL_ENV']).resolve()
    executable = prefix / 'Scripts' / 'python.exe'
    assert Path(sys.prefix).resolve() == prefix and Path(sys.executable).resolve() == executable.resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    base_executable = Path(sys._base_executable).resolve()
    assert base_prefix != prefix and base_executable == (base_prefix / 'python.exe').resolve()
    assert executable.is_file() and base_executable.is_file()
    stdlib_files = {name: base_prefix / 'Lib' / 'unittest' / name for name in ('case.py', 'mock.py')}
    assert all(path.is_file() for path in stdlib_files.values())
    case_source = stdlib_files['case.py'].read_text(encoding='utf-8')
    assert 'getattr(testMethod, "__unittest_skip__", False)' in case_source
    assert "getattr(testMethod, '__unittest_skip_why__', '')" in case_source
    for row in SPEC['method_origins']:
        assert row['source_sha256'] == actual_files[row['path']]
        tree = ast.parse((SOURCE / row['path']).read_bytes())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == row['class'])
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == row['method'])
        assert method.lineno == row['line']
        assert hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest() == row['ast_sha256']
    dependency_paths = [Path(os.environ['RUNNER_TEMP']).resolve() / name
                        for name in ('tests-windows-bootstrap.json', 'tests-windows-dependencies.json')]
    assert all(path.is_file() for path in dependency_paths)
    return {'transport_head': transport_head, 'transport_tree': transport_tree, 'source_head': FINAL['head'],
            'source_tree': FINAL['tree'], 'source_root': str(SOURCE), 'source_hashes': actual_files,
            'transport_index_sha256': sha(PACKAGE_PATH), 'transport_workflow_sha256': PACKAGE['workflow_sha256'],
            'source_workflow_sha256': actual_files['.github/workflows/tests.yml'],
            'literal_body_sha256': hashlib.sha256(body).hexdigest(),
            'runtime': SPEC['runtime'], 'python': str(executable), 'prefix': str(prefix),
            'base_prefix': str(base_prefix), 'alternate_python': str(base_executable),
            'executable_sha256': sha(executable), 'alternate_executable_sha256': sha(base_executable),
            'pyvenv_cfg_sha256': sha(prefix / 'pyvenv.cfg'),
            'stdlib': {name: {'path': str(path), 'sha256': sha(path)} for name, path in stdlib_files.items()},
            'dependency_receipts': {str(path): sha(path) for path in dependency_paths},
            'line_endings': 'Actual file bytes matched exactly; core.autocrlf=false and core.eol=lf, no normalization',
            'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT']}


actual = snapshot()
if MODE == 'bind':
    WORK.mkdir()
    save(WORK / 'binding-before.json', actual)
    for name in ('control_worker.proposed.py', 'run_controls.proposed.py', 'native_windows_step.py'):
        with (WORK / name).open('xb') as output:
            output.write((HERE / name).read_bytes())
    for row in SPEC['foreign'].values():
        assert sha(SOURCE / row['source_path']) == row['sha256']
        destination = WORK / row['package_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as output:
            output.write((SOURCE / row['source_path']).read_bytes())
    bound = {name: SPEC[name] for name in ('gates', 'controls', 'foreign', 'method_origins', 'runtime')}
    bound.update({name: actual[name] for name in ('source_hashes', 'python', 'prefix', 'base_prefix', 'alternate_python',
                  'executable_sha256', 'alternate_executable_sha256', 'pyvenv_cfg_sha256')})
    bound.update(ready_for_launch=True, root=str(SOURCE), head=FINAL['head'], tree=FINAL['tree'],
                 workflow_sha256=actual['source_workflow_sha256'], transport_head=actual['transport_head'],
                 transport_tree=actual['transport_tree'], runtime_binding_sha256=sha(WORK / 'binding-before.json'))
    save(WORK / 'bound-inputs.json', bound)
    files = {str(path.relative_to(WORK)): sha(path) for path in sorted(WORK.rglob('*')) if path.is_file()}
    save(WORK / 'review-files.json', {'files': files, 'transport_head': actual['transport_head'],
                                     'source_head': FINAL['head'], 'runtime_bound_in_same_job': True})
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8', newline='\n') as output:
        output.write('I03_CONTROL_PACKAGE=' + str(WORK) + '\n')
        output.write('I03_CONTROL_INPUT_SHA=' + sha(WORK / 'bound-inputs.json') + '\n')
        output.write('I03_CONTROL_REVIEW_SHA=' + sha(WORK / 'review-files.json') + '\n')
    assert snapshot() == actual
    print(json.dumps({'phase': 'bound', 'transport_head': actual['transport_head'], 'source_head': FINAL['head'],
                      'input_sha256': sha(WORK / 'bound-inputs.json'), 'index_sha256': sha(WORK / 'review-files.json')}))
else:
    before = json.loads((WORK / 'binding-before.json').read_bytes())
    assert actual == before
    index = json.loads((WORK / 'review-files.json').read_bytes())
    assert sha(WORK / 'review-files.json') == os.environ['I03_CONTROL_REVIEW_SHA']
    assert sha(WORK / 'bound-inputs.json') == os.environ['I03_CONTROL_INPUT_SHA']
    assert all(sha(WORK / name) == digest for name, digest in index['files'].items())
    save(WORK / 'binding-after.json', actual)
    print(json.dumps({'phase': 'verified', 'transport_head': actual['transport_head'], 'source_head': FINAL['head'],
                      'all_source_transport_runtime_bindings_unchanged': True}))
