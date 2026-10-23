/**
 * CitationChip — shared component used in both the real QueryView
 * and the landing page product preview.
 *
 * Props:
 *   filename   — e.g. "report.pdf"
 *   page       — optional page number, e.g. 14
 *   region     — optional visual region identifier, e.g. "03"
 *   score      — optional relevance score (shown as tooltip)
 *   label      — optional custom explicit label string
 *   active     — boolean highlight state
 *   onClick    — optional click handler
 */
export default function CitationChip({
  filename,
  page,
  region,
  score,
  label,
  active = false,
  onClick,
}) {
  let displayLabel = label;
  if (!displayLabel) {
    if (page != null) {
      displayLabel = `${filename} · p. ${page}`;
    } else if (region != null) {
      displayLabel = `${filename} · region ${region}`;
    } else {
      displayLabel = filename;
    }
  }

  const title = score != null ? `Relevance Score: ${Number(score).toFixed(3)}` : undefined;

  return (
    <span
      className={`citation-chip${active ? ' active' : ''}`}
      title={title}
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <span className="citation-chip-dot" />
      {displayLabel}
    </span>
  );
}
