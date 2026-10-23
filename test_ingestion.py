#!/usr/bin/env python3
"""
test_ingestion.py
-----------------
Quick smoke-test for OmniLens Step 1 (Core Ingestion + Storage).

What it tests:
  1. POST a small synthetic PDF to /upload  → prints source_id + chunk summary
  2. GET /source/{source_id}               → prints all PDF chunks
  3. POST a small synthetic PNG image      → prints source_id + chunk summary
  4. GET /source/{source_id}               → prints all image chunks

Prerequisites:
  - OmniLens server is running: uvicorn app.main:app --reload
  - Tesseract OCR binary is installed and on PATH
  - Python packages installed: requests, reportlab (for synthetic PDF generation)

Usage::

    # In a separate terminal, start the server:
    uvicorn app.main:app --reload

    # Then in another terminal, from the repo root:
    python test_ingestion.py
"""

import io
import json
import sys
import textwrap
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Install requests first:  pip install requests")

BASE_URL = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# Helpers to create synthetic test files in-memory
# ---------------------------------------------------------------------------


def _make_synthetic_pdf() -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for a small 2-page synthetic PDF.

    Uses reportlab if available; falls back to a raw minimal PDF string.
    """
    filename = "test_omnilens.pdf"
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica", 14)
        c.drawString(72, 700, "OmniLens Test PDF — Page 1")
        c.drawString(72, 680, "This page contains sample text for OCR and chunk testing.")
        c.showPage()
        c.drawString(72, 700, "OmniLens Test PDF — Page 2")
        c.drawString(72, 680, "Second page with different content.")
        c.save()
        return buf.getvalue(), filename
    except ImportError:
        # Minimal valid 2-page PDF (no images, plain text in content stream)
        raw = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R 5 0 R]/Count 2>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<<>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 12 Tf 72 720 Td (Page one text) Tj ET
endstream
endobj
5 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 6 0 R/Resources<<>>>>endobj
6 0 obj<</Length 44>>stream
BT /F1 12 Tf 72 720 Td (Page two text) Tj ET
endstream
endobj
xref
0 7
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000360 00000 n 
0000000511 00000 n 
trailer<</Size 7/Root 1 0 R>>
startxref
604
%%EOF"""
        return raw, filename


def _make_synthetic_png() -> tuple[bytes, str]:
    """Return (png_bytes, filename) for a small PNG with text drawn on it."""
    filename = "test_omnilens.png"
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (400, 200), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        draw.text((20, 80), "OmniLens OCR test 123", fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), filename
    except ImportError:
        # 1×1 white PNG as absolute fallback
        import base64
        tiny = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
            "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        )
        return tiny, filename


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def test_pdf_upload() -> str:
    """POST a synthetic PDF and return the source_id."""
    print("\n" + "=" * 60)
    print("TEST 1: Upload PDF")
    print("=" * 60)

    pdf_bytes, filename = _make_synthetic_pdf()
    resp = requests.post(
        f"{BASE_URL}/upload",
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=60,
    )
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(_pretty(data))
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    assert data["source_type"] == "pdf"
    assert data["chunks_created"] >= 2, "Expected at least 2 text chunks (one per page)"
    print("✓ PDF upload OK")
    return data["source_id"]


def test_get_pdf_chunks(source_id: str) -> None:
    """GET /source/{source_id} and display PDF chunks."""
    print("\n" + "=" * 60)
    print(f"TEST 2: Fetch chunks for PDF source_id={source_id}")
    print("=" * 60)

    resp = requests.get(f"{BASE_URL}/source/{source_id}", timeout=10)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(_pretty(data))
    assert resp.status_code == 200
    assert data["chunk_count"] >= 2
    # Verify page numbers are present
    pages = [c["page_number"] for c in data["chunks"] if c["chunk_type"] == "text"]
    assert pages, "No text chunks found"
    assert all(p is not None for p in pages), "Text chunks missing page_number"
    print(f"✓ Found {data['chunk_count']} chunks, text pages: {pages}")


def test_image_upload() -> str:
    """POST a synthetic PNG and return the source_id."""
    print("\n" + "=" * 60)
    print("TEST 3: Upload Image")
    print("=" * 60)

    png_bytes, filename = _make_synthetic_png()
    resp = requests.post(
        f"{BASE_URL}/upload",
        files={"file": (filename, png_bytes, "image/png")},
        timeout=120,  # YOLO model may download on first run
    )
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(_pretty(data))
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    assert data["source_type"] == "image"
    assert data["chunks_created"] == 1
    print("✓ Image upload OK")
    return data["source_id"]


def test_get_image_chunks(source_id: str) -> None:
    """GET /source/{source_id} and display image chunks."""
    print("\n" + "=" * 60)
    print(f"TEST 4: Fetch chunks for Image source_id={source_id}")
    print("=" * 60)

    resp = requests.get(f"{BASE_URL}/source/{source_id}", timeout=10)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(_pretty(data))
    assert resp.status_code == 200
    chunk = data["chunks"][0]
    assert chunk["chunk_type"] == "image_region"
    assert chunk["content_image_path"] is not None
    print(f"✓ Image chunk found. OCR text: {repr(chunk.get('content_text', '')[:80])}")
    print(f"  Detections: {chunk.get('bbox')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(textwrap.dedent(f"""
    OmniLens Step 1 — Ingestion Smoke Tests
    Target: {BASE_URL}
    Make sure the server is running: uvicorn app.main:app --reload
    """))

    # Health check first
    try:
        health = requests.get(f"{BASE_URL}/health", timeout=5)
        assert health.status_code == 200
        print(f"✓ Server is up ({BASE_URL}/health → {health.json()})")
    except Exception as e:
        sys.exit(f"✗ Server not reachable at {BASE_URL}. Start it first.\n  Error: {e}")

    pdf_source_id = test_pdf_upload()
    test_get_pdf_chunks(pdf_source_id)

    img_source_id = test_image_upload()
    test_get_image_chunks(img_source_id)

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
