import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

root = Path('E:/PtoP/work/github-upload')
repository = 'Susurrium/jinyicapital-2026-e2e'
branch = 'archive/full-project-2026-11-16'
gh = 'D:/GitHubCLI/gh.exe'


def github(endpoint):
    return json.loads(subprocess.check_output([gh, 'api', endpoint], encoding='utf-8'))


head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, encoding='utf-8').strip()
remote = github(f'repos/{repository}/git/ref/heads/{branch}')
if remote['object']['sha'] != head:
    raise RuntimeError('Remote branch SHA does not match local commit')
tree = github(f'repos/{repository}/git/trees/{head}?recursive=1')
if tree['truncated']:
    raise RuntimeError('Remote file tree truncated')
published = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
local = {}
for item in subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=root).decode('utf-8').split('\0')[:-1]:
    metadata, filename = item.split('\t', 1)
    local[filename] = metadata.split()[1]
if published != local:
    raise RuntimeError('Remote Git file paths or blob hashes differ from local index')
if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root):
    raise RuntimeError('Upload checkout has uncommitted changes')
source = Path('E:/PtoP/work/repo-publication')
if subprocess.check_output(['git', 'status', '--porcelain'], cwd=source):
    raise RuntimeError('Original integrated archive has uncommitted changes')
source_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, encoding='utf-8').strip()
if source_head != '101ad3c8716c550d7c3ae6f4fb2e4282a246b5a0':
    raise RuntimeError('Original integrated archive commit changed')
receipt = {
    'verified_at_utc': datetime.now(timezone.utc).isoformat(),
    'repository': 'https://github.com/' + repository,
    'branch': branch,
    'commit': head,
    'file_count': len(published),
    'all_remote_blob_hashes_match_local': True,
    'original_archive_head_unchanged': source_head,
    'checkout_clean': True,
    'project_url': f'https://github.com/{repository}/tree/{branch}/project',
    'my_part_url': f'https://github.com/{repository}/tree/{branch}/my-part',
}
target = Path('E:/PtoP/reports/github-upload-20261116.json')
if target.exists():
    raise RuntimeError('Receipt already exists; refusing overwrite')
target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False, indent=2))
