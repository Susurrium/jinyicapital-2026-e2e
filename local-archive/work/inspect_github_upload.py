import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

root = Path('E:/PtoP/work/github-upload')
destination = Path('E:/PtoP/work/upload-inspection')
destination.mkdir(exist_ok=True)
summaries = []
markers = re.compile(r'302132|333,610,197|174,064|3\.93\s*亿|instrument_id=11|-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}')
for path in sorted(root.rglob('*')):
    if not path.is_file() or path.suffix.lower() not in {'.zip', '.whl', '.docx'}:
        continue
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f'ZIP CRC failed: {path.name} {bad}')
        record = {'path': path.relative_to(root).as_posix(), 'members': archive.namelist(), 'flags': []}
        extracted_text = []
        for member in archive.infolist():
            if member.is_dir():
                continue
            if path.suffix.lower() == '.docx':
                if member.filename.startswith('word/') and member.filename.endswith('.xml'):
                    tree = ElementTree.fromstring(archive.read(member))
                    for paragraph in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                        line = ''.join(paragraph.itertext())
                        extracted_text.append(line)
                        if markers.search(line):
                            record['flags'].append({'member': member.filename, 'text': line[:400]})
            elif Path(member.filename).suffix.lower() in {'.md', '.txt', '.json', '.py', '.toml', '.xml', '.yaml', '.yml', '.ini', '.cfg'}:
                value = archive.read(member).decode('utf-8', errors='replace')
                if Path(member.filename).suffix.lower() in {'.md', '.json', '.toml', '.yaml', '.yml', '.ini', '.cfg'}:
                    extracted_text.extend(['\nFILE: ' + member.filename, value])
                for line in value.splitlines():
                    if markers.search(line):
                        record['flags'].append({'member': member.filename, 'text': line[:400]})
        if extracted_text:
            target = destination / (path.name + '.txt')
            target.write_text('\n'.join(extracted_text), encoding='utf-8')
            record['extracted_text'] = str(target)
        summaries.append(record)
(destination / 'archives.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps([{'path': item['path'], 'member_count': len(item['members']), 'flags': item['flags']} for item in summaries], ensure_ascii=False, indent=2))
