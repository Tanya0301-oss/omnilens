import sys
sys.path.insert(0, ".")
from app.retrieval.vector_store import delete_by_source

# Test with non-existent source_id - must tolerate and return 0
res = delete_by_source("non-existent-source-uuid-123")
print("delete_by_source for non-existent returned:", res)
assert res == 0, f"Expected 0, got {res}"
print("VERIFICATION PASS: delete_by_source tolerates missing IDs cleanly.")
