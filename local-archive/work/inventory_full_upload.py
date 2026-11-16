import json
import os
from pathlib import Path

root = Path('E:/PtoP')
excluded_directories = {'.git', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
excluded_roots = {'work/github-upload', 'work/full-upload-staging', 'work/python-temp'}
files = []
excluded = []
for directory, directories, filenames in os.walk(root, followlinks=False):
    parent = Path(directory)
    for name in list(directories):
        path = parent / name
        relative = path.relative_to(root).as_posix()
        if name in excluded_directories or name.endswith('.egg-info') or relative in excluded_roots:
            directories.remove(name)
            excluded.append({'path': relative, 'reason': 'local environment, Git metadata, cache or upload staging'})
    for name in filenames:
        path = parent / name
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in {'.pyc', '.pyo', '.bundle'}:
            excluded.append({'path': relative, 'reason': 'local bytecode or Git history bundle'})
            continue
        if path.is_symlink():
            raise RuntimeError(f'File symlink requires explicit handling: {relative}')
        state = path.stat()
        files.append({'path': relative, 'bytes': state.st_size, 'mtime_ns': state.st_mtime_ns})
result = {'files': files, 'excluded': excluded}
destination = root / 'work/full-upload-inventory.json'
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'files': len(files),
    'bytes': sum(item['bytes'] for item in files),
    'over_50_mib': [item for item in files if item['bytes'] > 50 * 1024**2],
    'excluded': excluded,
}, ensure_ascii=False, indent=2))
