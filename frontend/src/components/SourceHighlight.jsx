import React from 'react';

/**
 * SourceHighlight — Visual component illustrating the direct link between
 * an extracted grounded answer and the exact source document coordinates/region.
 */
export default function SourceHighlight({
  source = 'report.pdf',
  location = 'Page 4 · Table 2.1',
  score = 0.942,
  chunkType = 'table_region',
  excerpt = 'Fiscal Q3 consolidated software revenues reached $48.2M, representing 18.4% year-over-year organic expansion.',
  className = '',
}) {
  return (
    <div className={`source-highlight-panel ${className}`}>
      {/* Panel Top bar */}
      <div className="source-highlight-header">
        <div className="source-highlight-title">
          <span className="source-indicator-dot" />
          <span className="source-filename">{source}</span>
          <span className="source-location-badge">{location}</span>
        </div>
        <div className="source-score-badge">
          Rerank score: {score.toFixed(3)}
        </div>
      </div>

      {/* Visual Bounding Box / Chunk Frame */}
      <div className="source-evidence-frame">
        <div className="evidence-canvas">
          {/* Mock document background lines */}
          <div className="evidence-ambient-line w-80" />
          <div className="evidence-ambient-line w-95" />

          {/* Active Evidence Region */}
          <div className="evidence-bounding-box active">
            <div className="box-corner-marker tl" />
            <div className="box-corner-marker tr" />
            <div className="box-corner-marker bl" />
            <div className="box-corner-marker br" />
            
            <div className="box-header-strip">
              <span className="box-type-label">{chunkType.toUpperCase()}</span>
              <span className="box-coords-label">BBOX [142, 380, 520, 94]</span>
            </div>

            <p className="box-text-content">
              {excerpt}
            </p>
          </div>

          <div className="evidence-ambient-line w-85" />
          <div className="evidence-ambient-line w-60" />
        </div>
      </div>

      {/* Verification footer */}
      <div className="source-highlight-footer">
        <span className="source-verification-status">
          ✓ Verified exact source match · Cited in response
        </span>
      </div>
    </div>
  );
}
