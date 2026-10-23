import React from 'react';

/**
 * DocumentPreview — Renders realistic representations of documents,
 * scanned pages, and highlighted evidence regions.
 */
export default function DocumentPreview({
  filename = 'report.pdf',
  page = 14,
  title = 'Annual Financial Performance Report',
  highlightText = 'Operating margin expanded by 4.2% year over year across software subscriptions.',
  highlightRegion = 'Region 03 · Table 4.1',
  variant = 'highlighted', // 'highlighted' | 'thumbnail' | 'diagram'
  className = '',
}) {
  return (
    <div className={`doc-preview-card ${variant} ${className}`}>
      {/* Header bar */}
      <div className="doc-preview-header">
        <div className="doc-preview-tag">
          <span className="doc-type-badge">PDF</span>
          <span className="doc-preview-name">{filename}</span>
        </div>
        <span className="doc-preview-page">Page {page}</span>
      </div>

      {/* Document Sheet Visual */}
      <div className="doc-preview-sheet">
        <div className="doc-preview-sheet-title">{title}</div>
        
        {/* Placeholder skeleton lines representing document text */}
        <div className="doc-line w-85" />
        <div className="doc-line w-95" />
        <div className="doc-line w-70" />

        {/* Highlighted Evidence Callout / Bounding Box */}
        <div className="doc-highlight-box">
          <div className="doc-highlight-corner tl" />
          <div className="doc-highlight-corner tr" />
          <div className="doc-highlight-corner bl" />
          <div className="doc-highlight-corner br" />
          <div className="doc-highlight-tag">
            <span className="doc-highlight-dot" />
            {highlightRegion}
          </div>
          <div className="doc-highlight-content">
            "{highlightText}"
          </div>
        </div>

        {/* Additional document structure lines */}
        <div className="doc-line w-90" />
        <div className="doc-line w-60" />
        <div className="doc-table-skeleton">
          <div className="doc-table-row header">
            <span />
            <span />
            <span />
          </div>
          <div className="doc-table-row">
            <span />
            <span />
            <span />
          </div>
          <div className="doc-table-row">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>

      {/* Bottom Grounding Note */}
      <div className="doc-preview-footer">
        <span className="doc-grounding-indicator">
          Evidence matched via cross-encoder reranker (p.{page})
        </span>
      </div>
    </div>
  );
}
