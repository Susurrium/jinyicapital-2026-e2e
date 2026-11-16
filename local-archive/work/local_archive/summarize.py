from collections import Counter
import json
from pathlib import Path

path = Path('reports/local-data/archive-audit.json')
report = json.loads(path.read_text(encoding='utf-8'))
fields = {}
relationships = Counter()
minutes = Counter()
ids = set()
dates = set()
duplicates = Counter()
schemas = set()
for member in report['members']:
    schemas.add(json.dumps(member['schema'], sort_keys=True))
    relationships.update(member['relationships'])
    minutes.update(member['minute_of_day_rows'])
    ids.update(member['instrument_rows'])
    dates.update(member['date_rows'])
    duplicates.update(member['duplicates'])
    for name, stats in member['fields'].items():
        aggregate = fields.setdefault(name, Counter())
        aggregate.update({key: value for key, value in stats.items() if key not in ('raw_min', 'raw_max')})
summary = {
    'status': report['status'], 'totals': report['totals'], 'source': report['source'],
    'elapsed_seconds': report['elapsed_seconds'], 'violations': report['violations'],
    'date_min': min(item['date_min'] for item in report['members']),
    'date_max': max(item['date_max'] for item in report['members']),
    'dates': len(dates), 'instruments': len(ids), 'schema_variants': len(schemas),
    'within_member_duplicates': dict(duplicates), 'cross_member_duplicates': report['cross_member_duplicates'],
    'fields': fields, 'relationships': dict(relationships),
    'minute_of_day_rows': dict(sorted(minutes.items())),
    'members': [item['archive_member'] for item in report['members']],
}
Path('work/local_archive/summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in summary.items() if key not in ('fields', 'minute_of_day_rows', 'members')}, ensure_ascii=False, indent=2))
print(json.dumps({'field_nonzero_counters': {name: {key: value for key, value in stats.items() if value and key != 'observed'} for name, stats in fields.items()}}, ensure_ascii=False, indent=2))
