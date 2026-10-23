import sqlite3
import os
import chromadb

db_path = "data/omnilens.db"
print("=== SQLITE SOURCES TABLE ===")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT source_id, filename, source_type, chunk_count, status, error_message, stored_path, created_at FROM sources")
    rows = c.fetchall()
    print(f"Total rows in sources: {len(rows)}")
    for r in rows:
        print(r)

    print("\n=== SQLITE CHUNKS TABLE (pbl search) ===")
    c.execute("SELECT id, source_id, source_filename, chunk_type FROM chunks WHERE source_filename LIKE '%pbl%' OR source_id LIKE '%pbl%'")
    pbl_chunks = c.fetchall()
    print(f"PBL chunks found: {len(pbl_chunks)}")
    for r in pbl_chunks:
        print(r)

    print("\n=== SQLITE CHUNKS GROUPED BY SOURCE ===")
    c.execute("SELECT source_filename, source_id, count(*) FROM chunks GROUP BY source_filename, source_id")
    for r in c.fetchall():
        print(r)
    conn.close()
else:
    print("data/metadata.db not found!")

print("\n=== UPLOADS FOLDER ===")
uploads_dir = "data/uploads"
if os.path.exists(uploads_dir):
    files = os.listdir(uploads_dir)
    print(f"Total files in uploads: {len(files)}")
    for f in sorted(files):
        print(f" - {f}")
else:
    print("data/uploads not found!")

print("\n=== CHROMADB COLLECTIONS ===")
chroma_dir = "data/chroma_db"
if os.path.exists(chroma_dir):
    client = chromadb.PersistentClient(path=chroma_dir)
    for col_name in ["text_chunks", "image_chunks"]:
        try:
            col = client.get_collection(col_name)
            cnt = col.count()
            print(f"Collection '{col_name}': count={cnt}")
            # check for pbl in metadata
            res = col.get(where={"source_filename": {"$eq": "pbl.pdf"}})
            print(f"  '{col_name}' where source_filename='pbl.pdf': {len(res['ids'])} found: {res['ids']}")
            # also check if any id has pbl
            all_data = col.get()
            pbl_ids = [cid for cid in all_data["ids"] if "pbl" in cid.lower()]
            pbl_metas = [m for m in all_data["metadatas"] if m and "pbl" in str(m).lower()]
            print(f"  '{col_name}' ids containing pbl: {pbl_ids}")
            print(f"  '{col_name}' metadatas containing pbl: {len(pbl_metas)}")
        except Exception as e:
            print(f"Error checking {col_name}: {e}")
else:
    print("chroma_dir not found")
