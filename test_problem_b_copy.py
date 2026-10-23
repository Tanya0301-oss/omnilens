import os
import shutil
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

# 1. Prepare temp copy of data/
temp_dir = tempfile.mkdtemp(prefix="omnilens_test_data_")
print(f"Created temp data directory: {temp_dir}")

data_src = Path("data")
for item in data_src.iterdir():
    dest = Path(temp_dir) / item.name
    if item.is_dir():
        shutil.copytree(item, dest)
    else:
        shutil.copy2(item, dest)

print("Copied real data/ to temp directory.")

# 2. Set OMNILENS_DATA_DIR to point to temp_dir
os.environ["OMNILENS_DATA_DIR"] = temp_dir

from app.utils.paths import get_data_dir, get_db_path, get_chroma_dir
from app.db.metadata_store import list_all_sources, get_source, fetch_chunks_by_source
from app.cache.cache_manager import reset_caches
from app.retrieval.vector_store import _ensure_client, TEXT_COLLECTION, IMAGE_COLLECTION, _get_collection

reset_caches()
_ensure_client()

print(f"Active data dir: {get_data_dir()}")
print(f"Active db path: {get_db_path()}")

sources = list_all_sources()
print(f"Total sources in copy: {len(sources)}")

# Find a legacy row (one of the architecture_flow_diagram.png rows that existed from startup migration)
target_source = None
for s in sources:
    if s["source_id"] == "2dc84ba4-faf3-43db-a90d-9c308bcbc859":
        target_source = s
        break

if not target_source:
    # fallback to first architecture_flow_diagram.png
    for s in sources:
        if s["filename"] == "architecture_flow_diagram.png":
            target_source = s
            break

print(f"Selected legacy target source: {target_source['source_id']} ({target_source['filename']})")
print(f"  stored_path: {target_source.get('stored_path')}")
print(f"  status: {target_source.get('status')}")

# Chunks before delete in temp copy
chunks_before = fetch_chunks_by_source(target_source["source_id"])
print(f"  chunks in SQLite before delete: {len(chunks_before)}")

# 3. Call DELETE /source/{id} via TestClient
from app.main import app
client = TestClient(app)

resp = client.delete(f"/source/{target_source['source_id']}")
print(f"\nHTTP STATUS: {resp.status_code}")
print(f"RESPONSE BODY: {resp.text}")

# 4. Verify in temp copy
source_after = get_source(target_source["source_id"])
chunks_after = fetch_chunks_by_source(target_source["source_id"])
print(f"Source row after delete: {source_after}")
print(f"Chunks after delete: {len(chunks_after)}")

# Test idempotency (calling delete again on already deleted row)
resp2 = client.delete(f"/source/{target_source['source_id']}")
print(f"\nSecond DELETE HTTP STATUS (idempotency check): {resp2.status_code}")
print(f"Second DELETE RESPONSE BODY: {resp2.text}")

# 5. Clean up temp dir
shutil.rmtree(temp_dir, ignore_errors=True)
print(f"\nCleaned up temp data directory {temp_dir}.")

# 6. Verify REAL data was untouched
os.environ.pop("OMNILENS_DATA_DIR", None)
reset_caches()
_ensure_client()

from app.db.metadata_store import get_source as get_real_source
real_target = get_real_source(target_source["source_id"])
print(f"\nREAL data verification: target source {target_source['source_id']} in real DB: {real_target is not None}")
