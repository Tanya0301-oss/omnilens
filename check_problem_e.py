import sqlite3
import hashlib
from pathlib import Path

db_path = "data/omnilens.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("""
    SELECT source_id, filename, source_type, status, chunk_count, file_hash, created_at, stored_path
    FROM sources
    ORDER BY filename, created_at
""")
rows = c.fetchall()

print("=== ALL SOURCES IN DATABASE ===")
for r in rows:
    sid, fname, stype, status, chunks, fhash, created, spath = r
    # if fhash is None, try to calculate from disk
    actual_hash = fhash
    disk_path = None
    if spath and Path(spath).exists():
        disk_path = Path(spath)
    elif (Path("data/uploads") / f"{sid}_{fname}").exists():
        disk_path = Path("data/uploads") / f"{sid}_{fname}"
    elif (Path("data/uploads") / sid).exists():
        disk_path = Path("data/uploads") / sid

    if disk_path and disk_path.is_file():
        actual_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()[:16]

    print(f"ID: {sid} | File: {fname} | Chunks: {chunks} | Status: {status} | Date: {created} | Hash: {actual_hash} | Path: {disk_path}")

print("\n=== ORPHAN CHUNKS IN CHUNKS TABLE NOT IN SOURCES ===")
c.execute("""
    SELECT DISTINCT source_id, source_filename, source_type, count(*), min(created_at)
    FROM chunks
    WHERE source_id NOT IN (SELECT source_id FROM sources)
    GROUP BY source_id
""")
orphan_rows = c.fetchall()
for r in orphan_rows:
    sid, fname, stype, chunks, created = r
    actual_hash = None
    disk_path = None
    if (Path("data/uploads") / f"{sid}_{fname}").exists():
        disk_path = Path("data/uploads") / f"{sid}_{fname}"
    elif (Path("data/uploads") / sid).exists():
        disk_path = Path("data/uploads") / sid
    if disk_path and disk_path.is_file():
        actual_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()[:16]
    print(f"ID: {sid} | File: {fname} | Chunks: {chunks} | Date: {created} | Hash: {actual_hash} | Path: {disk_path}")

conn.close()
