import json
import shutil
import tarfile
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc

target = Path('work/local-data/first-member.feather')
target.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open('data/cpt_jyc_2026_e2e_bar1m.tar.gz', mode='r|gz') as archive:
    for member in archive:
        if member.isfile() and member.name.endswith('.feather'):
            with archive.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
            with pa.memory_map(str(target), 'r') as handle:
                reader = ipc.open_file(handle)
                rows = 0
                dates = []
                ids = set()
                for index in range(reader.num_record_batches):
                    batch = reader.get_batch(index)
                    rows += batch.num_rows
                    dates.append(pc.min_max(batch.column('date')).as_py())
                    ids.update(pc.unique(batch.column('instrument_id')).to_pylist())
                print(json.dumps({'member': member.name, 'size': member.size, 'schema': str(reader.schema), 'record_batches': reader.num_record_batches, 'rows': rows, 'date_min': str(min(item['min'] for item in dates)), 'date_max': str(max(item['max'] for item in dates)), 'instrument_count': len(ids), 'instrument_min': min(ids), 'instrument_max': max(ids), 'path': str(target.resolve())}, ensure_ascii=False), flush=True)
            break
