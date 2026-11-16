import json
from pathlib import Path
import shutil


def correct_observed_counts(report_path, backup_path):
    report = json.loads(report_path.read_text(encoding='utf-8'))
    members = report['members']
    if not members or report['violations']['infinite_values'] or report['violations']['fractional_local_values']:
        raise ValueError('仅适用于已确认全包无无穷和小数的整数型本地归档报告')
    if report['status'] != 'source_contract_violations':
        raise ValueError('原报告必须明确保留数据合同失败状态')
    negative_total = 0
    for member in members:
        schema = {field['name']: field['type'] for field in member['schema']}
        for name, stats in member['fields'].items():
            if schema[name] not in ('int16', 'int32', 'int64'):
                raise ValueError(f'字段未满足已核对整数型前提：{name}')
            if stats['infinite'] or stats['fractional']:
                raise ValueError('字段明细与全包前提不一致')
            prior_observed = member['rows'] - stats['null'] - stats['nan'] - stats['infinite'] - stats['sentinel_missing']
            if stats['observed'] != prior_observed or not 0 <= stats['unknown_negative'] <= prior_observed:
                raise ValueError('原 observed 计数不满足可精确修正的前提')
            stats['observed'] -= stats['unknown_negative']
            negative_total += stats['unknown_negative']
    if negative_total != report['violations']['unknown_negative_values']:
        raise ValueError('全包未知负值与字段明细不一致')
    if backup_path.exists():
        raise FileExistsError('原始审计报告备份已经存在，禁止覆盖')
    shutil.copy2(report_path, backup_path)
    report['schema_consistent'] = all(member['schema'] == members[0]['schema'] for member in members)
    report['observed_definition'] = '符合本地数值合同的非缺失观测：有限、非负、整数，且不是字段规定的缺失哨兵。未知负值和小数仍单独记录为合同失败，不修改原始数值。'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'excluded_invalid_cells_from_observed': negative_total,
                      'schema_consistent': report['schema_consistent'], 'original_report_backup': str(backup_path)}, ensure_ascii=True))


if __name__ == '__main__':
    correct_observed_counts(Path('reports/local-data/archive-audit.json'),
                            Path('work/local_archive/archive-audit.before-observed-semantics.json'))
