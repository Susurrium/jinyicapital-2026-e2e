import hashlib
import json
import subprocess
from pathlib import Path

root = Path('E:/PtoP/work/github-upload')
manifest = json.loads((root / 'UPLOAD_MANIFEST.json').read_text(encoding='utf-8'))
expected = {entry['path']: entry for entry in manifest['files']}
expected['UPLOAD_MANIFEST.json'] = {'sha256': hashlib.sha256((root / 'UPLOAD_MANIFEST.json').read_bytes()).hexdigest()}
tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')[:-1]
if set(tracked) != set(expected):
    raise RuntimeError(f'Index/manifest mismatch: {set(tracked) ^ set(expected)}')
for name in tracked:
    staged = subprocess.check_output(['git', 'show', ':' + name], cwd=root)
    if hashlib.sha256(staged).hexdigest() != expected[name]['sha256']:
        raise RuntimeError(f'Staged hash mismatch: {name}')
    if staged != (root / name).read_bytes():
        raise RuntimeError(f'Staged bytes mismatch: {name}')
print(json.dumps({'staged_file_count': len(tracked), 'all_staged_hashes_match_manifest_and_disk': True}))
