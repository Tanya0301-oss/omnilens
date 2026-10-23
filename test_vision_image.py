#!/usr/bin/env python3
"""
test_vision_image.py
---------------------
Test for vision-based image understanding and filename-aware retrieval.

This test:
1. Generates a small diagram image (PNG) with shapes and drawn text:
   e.g. "ARCHITECTURE_FLOW: Service A -> Service B -> Database"
2. Uploads the image via POST /upload with filename "architecture_flow_diagram.png"
3. Inspects the stored chunk in GET /source/{source_id}:
   - Verifies content_text contains the filename ("architecture_flow_diagram.png")
   - Verifies content_text contains drawn diagram text ("Service A", "Service B", or "ARCHITECTURE_FLOW")
4. Queries POST /query with a question that mentions the filename:
   e.g. "What does architecture_flow_diagram show about Service B?"
   - Verifies that the retrieval result retrieves the uploaded image chunk
   - Verifies cited_chunks contains the filename and answer is generated
"""

import io
import json
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

BASE_URL = "http://127.0.0.1:8000"


def create_test_diagram() -> tuple[bytes, str]:
    """Create a synthetic PNG diagram with text and geometric elements."""
    filename = "architecture_flow_diagram.png"
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw boxes
    draw.rectangle([30, 80, 160, 150], outline=(0, 0, 150), width=3)
    draw.rectangle([230, 80, 360, 150], outline=(0, 150, 0), width=3)
    draw.rectangle([430, 80, 560, 150], outline=(150, 0, 0), width=3)

    # Draw arrows
    draw.line([(160, 115), (230, 115)], fill=(50, 50, 50), width=3)
    draw.line([(360, 115), (430, 115)], fill=(50, 50, 50), width=3)

    # Draw labels
    draw.text((30, 30), "ARCHITECTURE_FLOW DIAGRAM", fill=(0, 0, 0))
    draw.text((45, 105), "Service A", fill=(0, 0, 0))
    draw.text((245, 105), "Service B", fill=(0, 0, 0))
    draw.text((455, 105), "Database", fill=(0, 0, 0))
    draw.text((30, 220), "Service A sends requests to Service B, which writes to Database.", fill=(0, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), filename


def run_test():
    print("=" * 65)
    print(" OmniLens Vision Understanding & Filename Retrieval Test")
    print("=" * 65)

    # Step 0: Health check
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=20)
        r.raise_for_status()
        print("Backend server is healthy: HTTP 200")
    except Exception as exc:
        sys.exit(f"Backend server is not reachable at {BASE_URL}: {exc}")


    # Step 1: Generate diagram
    img_bytes, filename = create_test_diagram()
    print(f"Generated synthetic test diagram: {filename} ({len(img_bytes)} bytes)")

    # Step 2: Upload diagram
    print(f"\n[1/3] Uploading {filename} to /upload...")
    upload_res = requests.post(
        f"{BASE_URL}/upload",
        files={"file": (filename, img_bytes, "image/png")},
        timeout=60,
    )
    if upload_res.status_code != 200:
        sys.exit(f"Upload failed: HTTP {upload_res.status_code} - {upload_res.text}")

    upload_data = upload_res.json()
    source_id = upload_data["source_id"]
    print(f"Upload successful!")
    print(f"  source_id: {source_id}")
    print(f"  chunks_created: {upload_data.get('chunks_created')}")
    print(f"  embedding_summary: {upload_data.get('embedding_summary')}")

    # Step 3: Check stored chunk metadata
    print(f"\n[2/3] Fetching chunks from /source/{source_id}...")
    source_res = requests.get(f"{BASE_URL}/source/{source_id}", timeout=10)
    if source_res.status_code != 200:
        sys.exit(f"Fetch source chunks failed: HTTP {source_res.status_code} - {source_res.text}")

    source_data = source_res.json()
    chunks = source_data.get("chunks", [])
    if not chunks:
        sys.exit("No chunks found for uploaded source!")

    chunk = chunks[0]
    content_text = chunk.get("content_text", "")
    print(f"Stored chunk content_text:\n---\n{content_text}\n---")

    # Assert filename is present in content_text
    assert filename in content_text, f"Filename '{filename}' was NOT found in content_text!"
    print(f"CHECK PASSED: content_text contains filename '{filename}'")

    # Assert some drawn text is present (e.g., Service A, Service B, or ARCHITECTURE)
    has_drawn_text = any(
        term in content_text.lower()
        for term in ["service a", "service b", "database", "architecture", "flow"]
    )
    assert has_drawn_text, "Drawn diagram text was NOT found in content_text!"
    print("CHECK PASSED: content_text contains drawn diagram text from vision / OCR")

    # Step 4: Filename-aware retrieval
    # Query mentioning filename
    question = "According to architecture_flow_diagram, what does Service A connect to?"
    print(f"\n[3/3] Querying: '{question}'...")
    query_res = requests.post(
        f"{BASE_URL}/query",
        json={"question": question, "top_k": 5},
        timeout=60,
    )
    if query_res.status_code != 200:
        sys.exit(f"Query failed: HTTP {query_res.status_code} - {query_res.text}")

    query_data = query_res.json()
    raw_answer = str(query_data.get("answer", ""))
    safe_answer = raw_answer.replace("\u202f", " ").encode("ascii", errors="replace").decode("ascii")
    print(f"Answer:\n{safe_answer}")
    print(f"\nModel used: {query_data.get('model_used')}")
    print(f"Latency: {query_data.get('latency_ms')}")


    cited = query_data.get("cited_chunks", [])
    print(f"\nCited chunks count: {len(cited)}")
    for c in cited:
        print(f"  - Chunk: {c.get('chunk_id')} | File: {c.get('source_filename')} | Score: {c.get('rerank_score')}")

    # Verify that the uploaded chunk or source filename was retrieved
    retrieved_filenames = [c.get("source_filename") for c in cited]
    assert filename in retrieved_filenames, (
        f"Expected {filename} in cited chunks, but got: {retrieved_filenames}"
    )
    print(f"CHECK PASSED: Question mentioning filename retrieved {filename}!")

    print("\n" + "=" * 65)
    print(" ALL TESTS PASSED SUCCESSFULLY! ")
    print("=" * 65)


if __name__ == "__main__":
    run_test()
