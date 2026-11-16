import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path


def child(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f'清单路径超出目标目录：{relative}')
    return path


def check_file(path, expected):
    if not path.is_file() or path.stat().st_size != expected['bytes']:
        raise RuntimeError(f'文件大小不一致：{path}')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected['sha256']:
        raise RuntimeError(f'文件 SHA-256 不一致：{path}')


def restore(archive_root, output, manifest):
    output.mkdir(parents=True, exist_ok=False)
    for index, entry in enumerate(manifest['files'], 1):
        destination = child(output, entry['path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        storage = entry['storage']
        if storage['kind'] == 'repository':
            source = child(archive_root, storage['path'])
            check_file(source, entry)
            shutil.copyfile(source, destination)
        elif storage['kind'] == 'release':
            with destination.open('xb') as stream:
                for asset in storage['assets']:
                    digest = hashlib.sha256()
                    size = 0
                    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'PtoP-Archive-Restore'})
                    with urllib.request.urlopen(request, timeout=120) as response:
                        while block := response.read(8 * 1024**2):
                            stream.write(block)
                            digest.update(block)
                            size += len(block)
                    if size != asset['bytes'] or digest.hexdigest() != asset['sha256']:
                        raise RuntimeError(f'分片完整性检查失败：{asset["name"]}')
        else:
            raise ValueError(f'未知存储类型：{storage["kind"]}')
        check_file(destination, entry)
        print(f'{index}/{len(manifest["files"])} 已校验：{entry["path"]}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='恢复并校验 PtoP 完整项目资料')
    parser.add_argument('--archive-root', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path)
    action.add_argument('--verify', type=Path)
    args = parser.parse_args()
    archive_root = args.archive_root.resolve()
    manifest = json.loads((archive_root / 'FULL_ARCHIVE_MANIFEST.json').read_text(encoding='utf-8'))
    if args.verify is not None:
        for entry in manifest['files']:
            check_file(child(args.verify.resolve(), entry['path']), entry)
        print(f'全部 {len(manifest["files"])} 个文件校验通过')
    else:
        restore(archive_root, args.output.resolve(), manifest)


if __name__ == '__main__':
    main()
