import hashlib
import json
import subprocess
from pathlib import Path

root = Path('E:/PtoP/work/github-upload')
verification = json.loads(Path('E:/PtoP/work/upload-verification.json').read_text(encoding='utf-8'))
if verification['broken_relative_markdown_links'] or verification['restricted_file_or_credential_flags']:
    raise RuntimeError('Publication verification has unresolved findings')
smoke_path = root / 'my-part/work/synthetic-check-final/report.json'
smoke = json.loads(smoke_path.read_text(encoding='utf-8'))
if smoke['joint_gradient_check'] != 'passed' or smoke['independent_process_reload']['status'] != 'passed':
    raise RuntimeError('Synthetic validation failed')
report = {
    **verification,
    'current_synthetic_execution': {
        'command': 'python -B tools/smoke.py --output work/synthetic-check-final',
        'directory': 'my-part',
        'environment': 'Windows x64; Python 3.12.10; PyTorch 2.8.0 CPU; existing local environment',
        'result': smoke,
    },
    'documents_and_archives': 'Five DOCX XML texts and delivery ZIP documentation reviewed; no actual market samples included',
}
whitespace = subprocess.run(['git', '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol', 'diff', '--cached', '--check'], cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
if whitespace.returncode not in {0, 2}:
    raise RuntimeError(whitespace.stderr)
report['git_whitespace_check'] = {
    'exit_code': whitespace.returncode,
    'findings': whitespace.stdout.splitlines(),
    'scope': 'Initial archive commit; source formatting preserved; CRLF recognized as Windows line endings',
}
for line in whitespace.stdout.splitlines():
    if not line.endswith(': new blank line at EOF.'):
        raise RuntimeError(f'Unexpected whitespace finding: {line}')
    relative = line.rsplit(':', 2)[0]
    part, remainder = relative.split('/', 1)
    source_root = Path('E:/PtoP/work/repo-publication') if part == 'project' else Path('E:/PtoP')
    source_data = (source_root / remainder).read_bytes()
    current_data = (root / relative).read_bytes()
    if not source_data.endswith(b'\n\n') and not source_data.endswith(b'\r\n\r\n'):
        raise RuntimeError(f'Unexpected new EOF blank line: {relative}')
    if source_data.splitlines()[-2:] != current_data.splitlines()[-2:]:
        raise RuntimeError(f'EOF formatting changed: {relative}')
(root / 'UPLOAD_VERIFICATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
entries = []
for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if not path.is_file() or {'.git', 'work', '__pycache__', '.pytest_cache'}.intersection(relative.parts) or relative.as_posix() == 'UPLOAD_MANIFEST.json':
        continue
    data = path.read_bytes()
    entries.append({'path': relative.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
manifest = {'algorithm': 'SHA-256', 'self_excluded': 'UPLOAD_MANIFEST.json', 'file_count': len(entries), 'files': entries}
(root / 'UPLOAD_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'manifest_files': len(entries), 'bytes': sum(item['bytes'] for item in entries), 'largest_file_bytes': max(item['bytes'] for item in entries)}, ensure_ascii=False))
