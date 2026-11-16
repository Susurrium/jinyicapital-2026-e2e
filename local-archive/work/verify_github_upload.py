import ast
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import mistune

root = Path('E:/PtoP/work/github-upload')
sources = {'project': Path('E:/PtoP/work/repo-publication'), 'my-part': Path('E:/PtoP')}
excluded = {'.git', 'work', '__pycache__', '.pytest_cache'}
files = sorted(path for path in root.rglob('*') if path.is_file() and not excluded.intersection(path.relative_to(root).parts))
checked_python = []
checked_archives = []
checked_xml = []
broken_links = []
security_flags = []
markdown = mistune.create_markdown(renderer='ast')
secret_pattern = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-proj-[A-Za-z0-9_-]{30,}')
restricted_pattern = re.compile(r'302132\.SZ|333,610,197|174,064|3\.93\s*亿|333610197')


def inspect_nested_archive(payload, label):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f'Nested ZIP CRC failure: {label}')
        checked_archives.append({'path': label, 'members': len(archive.namelist())})
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if member_path.is_absolute() or '..' in member_path.parts:
                raise RuntimeError(f'Unsafe nested archive member: {label} {member.filename}')
            if member_path.suffix.lower() in {'.feather', '.parquet', '.csv', '.tsv', '.npy', '.npz', '.pt', '.pth', '.ckpt', '.pem', '.key', '.bundle'}:
                security_flags.append({'path': label, 'member': member.filename, 'reason': 'restricted nested archive extension'})
            value = archive.read(member)
            if member_path.suffix.lower() in {'.zip', '.whl'}:
                inspect_nested_archive(value, label + '!' + member.filename)
            elif member_path.suffix.lower() in {'.md', '.py', '.ps1', '.json', '.toml', '.xml', '.txt', '.yaml', '.yml'}:
                content = value.decode('utf-8', errors='replace')
                if secret_pattern.search(content) or restricted_pattern.search(content):
                    security_flags.append({'path': label, 'member': member.filename, 'reason': 'credential or restricted marker in nested archive'})


def links(tokens):
    for token in tokens:
        if token['type'] in {'link', 'image'}:
            yield token['attrs']['url']
        yield from links(token.get('children', []))


for path in files:
    relative = path.relative_to(root)
    if path.name.startswith('.env') or path.suffix.lower() in {'.pem', '.key', '.feather', '.parquet', '.csv', '.tsv', '.npy', '.npz', '.pt', '.pth', '.ckpt', '.bundle'}:
        security_flags.append({'path': relative.as_posix(), 'reason': 'restricted filename or extension'})
    if path.suffix == '.py':
        ast.parse(path.read_bytes(), filename=str(relative))
        source = sources[relative.parts[0]].joinpath(*relative.parts[1:])
        if not source.is_file() or source.read_bytes() != path.read_bytes():
            raise RuntimeError(f'Source copy mismatch: {relative}')
        checked_python.append(relative.as_posix())
    if path.suffix == '.xml':
        ElementTree.parse(path)
        checked_xml.append(relative.as_posix())
    if path.suffix.lower() in {'.zip', '.whl', '.docx'}:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f'ZIP CRC failure: {relative}')
            checked_archives.append({'path': relative.as_posix(), 'members': len(archive.namelist())})
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or '..' in member_path.parts:
                    raise RuntimeError(f'Unsafe archive member: {relative} {member.filename}')
                if member_path.suffix.lower() in {'.feather', '.parquet', '.csv', '.tsv', '.npy', '.npz', '.pt', '.pth', '.ckpt', '.pem', '.key', '.bundle'}:
                    security_flags.append({'path': relative.as_posix(), 'member': member.filename, 'reason': 'restricted archive extension'})
                if member_path.suffix.lower() in {'.zip', '.whl'}:
                    inspect_nested_archive(archive.read(member), relative.as_posix() + '!' + member.filename)
    if path.suffix.lower() in {'.md', '.py', '.ps1', '.json', '.toml', '.xml', '.txt', '.lock'} or path.name.startswith('.'):
        content = path.read_text(encoding='utf-8-sig')
        for line_number, line in enumerate(content.splitlines(), 1):
            if secret_pattern.search(line) or restricted_pattern.search(line):
                security_flags.append({'path': relative.as_posix(), 'line': line_number, 'reason': 'credential or known restricted marker'})
        if path.suffix == '.md':
            for target in links(markdown(content)):
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                linked = path.parent / unquote(url.path)
                if not linked.exists():
                    broken_links.append({'path': relative.as_posix(), 'target': target})

report = {
    'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'file_count_before_manifest': len(files),
    'python_source_copies_identical': len(checked_python),
    'python_ast_passed': len(checked_python),
    'xml_parsed': checked_xml,
    'zip_crc_checked': checked_archives,
    'broken_relative_markdown_links': broken_links,
    'restricted_file_or_credential_flags': security_flags,
    'scope': 'Publication files only; no real market data accessed; no platform or financial performance validation',
}
report_path = Path('E:/PtoP/work/upload-verification.json')
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
if broken_links or security_flags:
    raise SystemExit(1)
