from pathlib import Path
from storage import load_database

db = load_database('.')
print('批次数量:', len(db.batches))
for b in db.batches:
    print(f'  批次: {b.batch_id}')
    print(f'  快照文件数: {len(b.contract_file_paths)}')
    if b.contract_file_paths:
        print(f'  快照文件: {[Path(p).name for p in b.contract_file_paths]}')
    else:
        print(f'  ⚠️  快照为空!')
print()
print('合同库合同数:', len(db.contracts))
for c in db.contracts:
    print(f'  {Path(c.file_path).name}: scan_batch_id={c.scan_batch_id}')
