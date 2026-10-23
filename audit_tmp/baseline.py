import sqlite3
conn = sqlite3.connect('data/omnilens.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

print('=== SOURCES TABLE ===')
rows = c.execute('SELECT source_id, filename, source_type, status, chunk_count FROM sources ORDER BY created_at').fetchall()
for r in rows:
    sid = dict(r)['source_id']
    fn = dict(r)['filename']
    st = dict(r)['source_type']
    status = dict(r)['status']
    cc = dict(r)['chunk_count']
    print(f'  {fn} | type={st} | status={status} | chunks={cc} | id={sid[:8]}...')

print()
print('=== CHUNKS TABLE (by source) ===')
rows2 = c.execute('SELECT source_filename, COUNT(*) as cnt FROM chunks GROUP BY source_id ORDER BY source_filename').fetchall()
for r in rows2:
    fn = dict(r)['source_filename']
    cnt = dict(r)['cnt']
    print(f'  {fn}: {cnt} chunks')

conn.close()
