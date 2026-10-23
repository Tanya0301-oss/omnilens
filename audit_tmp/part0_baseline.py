import sqlite3
import chromadb
import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect("data/omnilens.db")
c = conn.cursor()

print("=== PART 0: BASELINE CHUNK COUNTS ===")
rows = c.execute("SELECT source_id, count(*) FROM chunks GROUP BY source_id").fetchall()
for sid, cnt in rows:
    print(f"Source: {sid} -> {cnt} chunks")
total = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
print(f"Total chunks in SQLite: {total}")

client = chromadb.PersistentClient(path="data/chroma_db")
print(f"Chroma text_chunks: {client.get_collection('text_chunks').count()}")
print(f"Chroma image_chunks: {client.get_collection('image_chunks').count()}")

API = "http://127.0.0.1:8000"
DBMS_ID = "0298b585-8ac3-4bbb-9975-6dcf0a6dd7ef"

def post_json(path, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(f"{API}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode('utf-8'))

print("\n=== BASELINE TEST 1: Document Question ===")
r_doc = post_json("/query", {"question": "What is Problem Statement 1 about in this lab document?", "source_id": DBMS_ID})
print(f"answer_source: {r_doc.get('answer_source')}, citations: {len(r_doc.get('cited_chunks', []))}")
print(f"answer sample: {r_doc.get('answer')[:100]}")

print("\n=== BASELINE TEST 2: Off-topic with allow_general=True ===")
r_gk = post_json("/query", {"question": "what is normalization in DBMS?", "source_id": DBMS_ID, "allow_general": True})
print(f"answer_source: {r_gk.get('answer_source')}, notice: {r_gk.get('notice')}")

print("\n=== BASELINE TEST 3: Off-topic with allow_general=False ===")
r_nf = post_json("/query", {"question": "what is normalization in DBMS?", "source_id": DBMS_ID, "allow_general": False})
print(f"answer_source: {r_nf.get('answer_source')}, answer: {r_nf.get('answer')}")

print("\n=== BASELINE TEST 4: Streaming /query/stream ===")
req = urllib.request.Request(
    f"{API}/query/stream",
    data=json.dumps({"question": "What is Problem Statement 1?", "source_id": DBMS_ID}).encode('utf-8'),
    headers={"Content-Type": "application/json"}
)
events = []
with urllib.request.urlopen(req) as resp:
    for line in resp:
        txt = line.decode('utf-8').strip()
        if txt.startswith("data: "):
            events.append(json.loads(txt[6:]).get("type"))
print(f"Stream event types received: {set(events)}")
print(f"Stream ends with done: {events[-1] == 'done' if events else False}")
