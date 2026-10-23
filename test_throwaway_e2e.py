import io
import time
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

BASE_URL = "http://127.0.0.1:8000"

print("=== PART 1: CREATE & UPLOAD THROWAWAY PDF ===")
buf = io.BytesIO()
c = canvas.Canvas(buf, pagesize=letter)
c.setFont("Helvetica-Bold", 14)
c.drawString(72, 700, "Throwaway Test Document for OmniLens")
c.setFont("Helvetica", 12)
c.drawString(72, 670, "The secret test code is ZEPHYR-99214.")
c.drawString(72, 650, "Project Falcon was launched in November 2026.")
c.showPage()
c.save()
pdf_bytes = buf.getvalue()

files = {"file": ("throwaway_sample.pdf", pdf_bytes, "application/pdf")}
resp = requests.post(f"{BASE_URL}/upload", files=files)
print(f"Upload HTTP Status: {resp.status_code}")
data = resp.json()
print(f"Upload Response: {data}")
source_id = data["source_id"]
assert resp.status_code == 200
assert data["chunks_created"] > 0

print(f"\n=== PART 2: QUERY THROWAWAY DOCUMENT ===")
q_resp = requests.post(f"{BASE_URL}/query", json={
    "question": "What is the secret test code?",
    "source_id": source_id,
    "mode": "focused"
})
print(f"Query HTTP Status: {q_resp.status_code}")
q_data = q_resp.json()
print(f"Answer: {q_data.get('answer')}")
print(f"Citations: {[c.get('source_filename') for c in q_data.get('cited_chunks', [])]}")
assert "ZEPHYR-99214" in q_data.get("answer", "")

print(f"\n=== PART 3: RE-INDEX THROWAWAY SOURCE ===")
reindex_resp = requests.post(f"{BASE_URL}/source/{source_id}/reindex")
print(f"Re-index HTTP Status: {reindex_resp.status_code}")
print(f"Re-index Response: {reindex_resp.json()}")
assert reindex_resp.status_code == 200

# Wait for ready status
print("Waiting for re-index to complete...")
for _ in range(30):
    st_resp = requests.get(f"{BASE_URL}/sources/{source_id}/status")
    if st_resp.status_code == 200 and st_resp.json().get("status") == "ready":
        print(f"Re-index complete! Status: {st_resp.json()}")
        break
    time.sleep(1)

print(f"\n=== PART 4: DELETE THROWAWAY SOURCE ===")
del_resp = requests.delete(f"{BASE_URL}/source/{source_id}")
print(f"DELETE HTTP Status: {del_resp.status_code}")
print(f"DELETE Response: {del_resp.json()}")
assert del_resp.status_code == 200
assert del_resp.json()["deleted"] is True

print(f"\n=== PART 5: IDEMPOTENT SECOND DELETE ===")
del2_resp = requests.delete(f"{BASE_URL}/source/{source_id}")
print(f"Second DELETE HTTP Status: {del2_resp.status_code}")
print(f"Second DELETE Response: {del2_resp.json()}")
assert del2_resp.status_code == 200
assert del2_resp.json()["deleted"] is True

print(f"\n=== PART 6: VERIFY CLEANUP ===")
# Verify source no longer exists
st_after = requests.get(f"{BASE_URL}/sources/{source_id}/status")
print(f"Status check after delete: {st_after.status_code}")
assert st_after.status_code == 404

print("\n>>> All throwaway upload, query, re-index, and delete tests PASSED! <<<")
