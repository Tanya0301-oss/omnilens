"""
app/ingestion/image_parser.py
------------------------------
Standalone image ingestion for OmniLens with vision-based image understanding.

Pipeline for a single uploaded JPG/PNG:
1. OCR via Tesseract (pytesseract) → extracted text.
2. Vision captioning via Groq vision API (GROQ_VISION_MODEL) → 2-4 sentence
   description, visible text, entities & relationships.
3. Object detection via YOLOv8-nano (ultralytics) → stored in metadata bbox.
4. Composite ``content_text`` created:
   "Image file: <filename>. Description: <caption>. Visible text: <OCR text + VLM text>"
   (or photo YOLO labels if non-empty photo).
5. One ``chunk_type="image_region"`` row inserted into the metadata store.

Fallback:
- If Groq vision fails (rate limits, network, credentials), a warning is logged,
  caption_pending=True is marked in metadata, and content_text falls back to OCR-only.
- Ingestion NEVER fails as a result of vision captioning failure.

Dependencies: pytesseract, Pillow, ultralytics (YOLOv8), groq.
"""

import base64
import io
import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple, Optional

import pytesseract
from dotenv import load_dotenv
from groq import Groq
from PIL import Image
from ultralytics import YOLO

from app.db.metadata_store import insert_chunk
from app.utils.logging_config import get_logger, log_stage

logger = get_logger(__name__)

# Ensure environment variables are loaded
load_dotenv()

# Max dimension for images sent to Groq Vision API to stay within limits
_MAX_VISION_DIM = 1024


# ---------------------------------------------------------------------------
# YOLO model — loaded lazily once via lru_cache
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_yolo_model() -> YOLO:
    """Load and return the YOLOv8-nano pretrained model (cached after first call).

    The model file (``yolov8n.pt``) is downloaded automatically by the
    ultralytics library on first use and cached in ``~/.cache/ultralytics/``.

    Returns:
        A :class:`ultralytics.YOLO` instance ready for inference.
    """
    logger.info("Loading YOLOv8-nano model (first call — may download weights)…")
    model = YOLO("yolov8n.pt")
    logger.info("YOLOv8-nano model loaded.")
    return model


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class ImageIngestionResult(NamedTuple):
    """Summary returned after ingesting a standalone image."""

    source_id: str
    chunk_id: str
    ocr_text_length: int
    detected_objects: int
    caption_pending: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_markdown(text: str) -> str:
    """Strip common markdown formatting characters (bold, headers, bullets)."""
    # Remove bold/italic markers
    text = re.sub(r"[*_]{1,3}", "", text)
    # Remove markdown headers like ### or ##
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Remove leading bullet dashes or asterisks
    text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _prepare_image_b64(image_path: Path, max_dim: int = _MAX_VISION_DIM) -> str:
    """Open an image, resize if dimensions exceed max_dim, and return base64 jpeg."""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _run_ocr(image_path: Path) -> str:
    """Run Tesseract OCR on *image_path* and return the extracted text.

    Args:
        image_path: Absolute path to the image file.

    Returns:
        Stripped OCR output string (may be empty if no text is found).
    """
    try:
        pil_image = Image.open(image_path).convert("RGB")
        text: str = pytesseract.image_to_string(pil_image)
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for %s: %s", image_path.name, exc)
        return ""


def _run_groq_vision(image_path: Path, filename: str) -> tuple[str, bool]:
    """Call Groq Vision API to understand the image content.

    Prompt requests:
    (a) a 2-4 sentence description of what the image shows,
    (b) every piece of readable text, labels, table names, column names, or numbers seen,
    (c) for diagrams, the entities and relationships between them.
    Plain text, no markdown.

    Returns:
        (vision_text, caption_pending):
        vision_text: Generated vision text or empty string on failure.
        caption_pending: True if vision call failed, False on success.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.warning("GROQ_API_KEY not configured — skipping vision captioning for %s", filename)
        return "", True

    vision_model = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()
    prompt = (
        "Analyze this image and provide:\n"
        "(a) A 2-4 sentence description of what the image shows.\n"
        "(b) Every piece of readable text, labels, table names, column names, or numbers you can see.\n"
        "(c) For diagrams, the entities and relationships between them.\n"
        "Provide plain text only, no markdown formatting (no asterisks, bullet points, headers, or bold text)."
    )

    try:
        b64_image = _prepare_image_b64(image_path)
        client = Groq(api_key=api_key, timeout=30.0)
        response = client.chat.completions.create(
            model=vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}"
                            },
                        },
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=600,
        )
        raw_text = response.choices[0].message.content or ""
        clean_text = _clean_markdown(raw_text)
        return clean_text, False
    except Exception as exc:
        logger.warning(
            "Groq vision captioning failed for %s (falling back to OCR): %s",
            filename,
            exc,
        )
        return "", True


def _run_yolo(image_path: Path) -> list[dict[str, Any]]:
    """Run YOLOv8 object detection on *image_path*.

    Args:
        image_path: Absolute path to the image file.

    Returns:
        A list of detection dicts, each with keys:
        ``label`` (str), ``confidence`` (float, 2 d.p.),
        ``bbox`` (dict with keys ``x1``, ``y1``, ``x2``, ``y2`` in pixels).
        Returns an empty list if detection fails.
    """
    try:
        model = _get_yolo_model()
        results = model(str(image_path), verbose=False)
        detections: list[dict[str, Any]] = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                conf = round(float(box.conf[0]), 4)
                cls_id = int(box.cls[0])
                label: str = result.names[cls_id]
                detections.append(
                    {
                        "label": label,
                        "confidence": conf,
                        "bbox": {
                            "x1": round(x1, 2),
                            "y1": round(y1, 2),
                            "x2": round(x2, 2),
                            "y2": round(y2, 2),
                        },
                    }
                )

        return detections
    except Exception as exc:  # noqa: BLE001
        logger.warning("YOLO inference failed for %s: %s", image_path.name, exc)
        return []


def _is_probable_photo(image_path: Path, detections: list[dict[str, Any]]) -> bool:
    """Heuristic to check if an image is likely a photographic image rather than a diagram/chart.

    If YOLO detects objects typical of real-world scenes (e.g. person, car, dog, chair)
    or color variance across pixels indicates a photo.
    """
    if not detections:
        return False

    photo_labels = {
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
        "boat", "traffic light", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
        "bottle", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
        "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "couch", "potted plant", "bed", "dining table", "tv", "laptop", "mouse",
        "remote", "keyboard", "cell phone"
    }

    detected_labels = [d["label"].lower() for d in detections]
    return any(lbl in photo_labels for lbl in detected_labels)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_image_chunk_content(
    image_path: Path,
    source_filename: str,
    ocr_text: Optional[str] = None,
    detections: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, str, bool]:
    """Generate structured content_text for an image chunk using Groq vision.

    Returns:
        (content_text, caption, caption_pending)
    """
    if ocr_text is None:
        ocr_text = _run_ocr(image_path)
    if detections is None:
        detections = _run_yolo(image_path)

    vlm_text, caption_pending = _run_groq_vision(image_path, source_filename)

    # Format the content_text as:
    # "Image file: <filename>. Description: <caption>. Visible text: <OCR text + VLM text>"
    # If vision captioning failed, fall back to OCR text while still keeping filename.
    if vlm_text:
        caption = vlm_text
        visible_text_parts = []
        if ocr_text:
            visible_text_parts.append(ocr_text)
        visible_text_parts.append(vlm_text)
        combined_text = " ".join(visible_text_parts).strip()
        content_text = f"Image file: {source_filename}. Description: {caption}. Visible text: {combined_text}"
    else:
        caption = ""
        combined_text = ocr_text.strip()
        if combined_text:
            content_text = f"Image file: {source_filename}. Visible text: {combined_text}"
        else:
            content_text = f"Image file: {source_filename}."

    # Keep YOLO labels only as secondary metadata, not in the embedded text,
    # unless the labels are non-empty and the image is a photo.
    is_photo = _is_probable_photo(image_path, detections)
    if is_photo and detections:
        labels_str = ", ".join(d["label"] for d in detections)
        content_text = f"{content_text} Objects: {labels_str}"

    return content_text.strip(), caption, caption_pending


def ingest_image(
    image_path: Path,
    source_id: str,
    source_filename: str,
    saved_relative_path: str,
) -> ImageIngestionResult:
    """Ingest a standalone image: OCR + Vision captioning + YOLO → metadata store.

    Args:
        image_path:           Absolute path to the image file on disk.
        source_id:            UUID that will group chunks from this upload.
        source_filename:      Original filename (stored for display).
        saved_relative_path:  Relative path (from repo root) where the raw
                              upload was saved; stored in ``content_image_path``.

    Returns:
        An :class:`ImageIngestionResult` summarising the ingestion.

    Raises:
        FileNotFoundError: If *image_path* does not exist.
    """
    t_start = time.perf_counter()

    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    logger.info("Starting image ingestion: %s", source_filename)

    # --- OCR -----------------------------------------------------------
    t_ocr = time.perf_counter()
    ocr_text = _run_ocr(image_path)
    log_stage(
        logger,
        "OCR complete",
        elapsed=time.perf_counter() - t_ocr,
        filename=source_filename,
        chars=len(ocr_text),
    )

    # --- Object detection -------------------------------------------
    t_yolo = time.perf_counter()
    detections = _run_yolo(image_path)
    log_stage(
        logger,
        "YOLO detection complete",
        elapsed=time.perf_counter() - t_yolo,
        filename=source_filename,
        objects=len(detections),
    )

    # --- Vision Captioning ------------------------------------------
    t_vision = time.perf_counter()
    content_text, caption, caption_pending = generate_image_chunk_content(
        image_path=image_path,
        source_filename=source_filename,
        ocr_text=ocr_text,
        detections=detections,
    )
    log_stage(
        logger,
        "Vision captioning complete",
        elapsed=time.perf_counter() - t_vision,
        filename=source_filename,
        caption_pending=caption_pending,
    )

    # --- Store chunk ------------------------------------------------
    detected_obj_str = ", ".join(d["label"] for d in detections) if detections else ""
    bbox_payload: dict[str, Any] = {
        "detections": detections,
        "detected_objects": detected_obj_str,
        "caption": caption,
        "ocr_text": ocr_text,
        "caption_pending": caption_pending,
    }

    chunk_id = insert_chunk(
        source_id=source_id,
        source_filename=source_filename,
        source_type="image",
        chunk_type="image_region",
        page_number=None,
        bbox=bbox_payload,
        content_text=content_text,
        content_image_path=saved_relative_path,
    )

    elapsed = time.perf_counter() - t_start
    log_stage(
        logger,
        "Image ingested",
        elapsed=elapsed,
        filename=source_filename,
        ocr_chars=len(ocr_text),
        objects_detected=len(detections),
        caption_pending=caption_pending,
    )

    return ImageIngestionResult(
        source_id=source_id,
        chunk_id=chunk_id,
        ocr_text_length=len(ocr_text),
        detected_objects=len(detections),
        caption_pending=caption_pending,
    )
