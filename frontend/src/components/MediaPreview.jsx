import React from 'react';

/**
 * MediaPreview — Shows that OmniLens ingests and indexes mixed formats
 * (PDF, Image, Video/Audio) into one unified cross-modal knowledge index.
 */
export default function MediaPreview({ className = '' }) {
  const formats = [
    {
      badge: 'PDF',
      title: 'Document & Layout',
      meta: 'Text, tables & layout chunks',
      spec: 'PyMuPDF · Page & section parsing',
      previewType: 'pdf',
    },
    {
      badge: 'IMAGE',
      title: 'Visuals & Diagrams',
      meta: 'OCR & visual region embeddings',
      spec: 'CLIP / SigLIP · Cross-modal vector space',
      previewType: 'image',
    },
    {
      badge: 'MEDIA',
      title: 'Video & Spoken Content',
      meta: 'Frame sampling & synced transcripts',
      spec: 'ASR transcript · 04:12 timestamp anchor',
      previewType: 'video',
    },
  ];

  return (
    <div className={`media-inputs-container ${className}`}>
      <div className="media-inputs-header">
        <span className="section-eyebrow">UNIFIED INGESTION</span>
        <h3 className="media-inputs-caption">
          Different formats. One searchable knowledge space.
        </h3>
      </div>

      <div className="media-grid">
        {formats.map((item, idx) => (
          <div key={idx} className="media-card">
            {/* Card header */}
            <div className="media-card-top">
              <span className={`media-badge ${item.badge.toLowerCase()}`}>
                {item.badge}
              </span>
              <span className="media-card-spec">{item.spec}</span>
            </div>

            {/* Simulated Miniature UI Viewport */}
            <div className="media-viewport">
              {item.previewType === 'pdf' && (
                <div className="mini-sheet pdf-sheet">
                  <div className="sheet-header-line" />
                  <div className="sheet-text-row w-90" />
                  <div className="sheet-text-row w-75" />
                  <div className="sheet-columns-row">
                    <div className="mini-col" />
                    <div className="mini-col" />
                  </div>
                  <div className="sheet-footer-page">PAGE 14 OF 48</div>
                </div>
              )}

              {item.previewType === 'image' && (
                <div className="mini-sheet img-sheet">
                  <div className="mini-diagram-chart">
                    <div className="chart-bar h-40" />
                    <div className="chart-bar h-70 active" />
                    <div className="chart-bar h-55" />
                    <div className="chart-bar h-85" />
                  </div>
                  <div className="mini-detect-box">
                    <span className="detect-label">CHART REGION 02</span>
                  </div>
                </div>
              )}

              {item.previewType === 'video' && (
                <div className="mini-sheet video-sheet">
                  <div className="mini-video-frame">
                    <div className="video-ambient-wave" />
                    <span className="video-timestamp">04:12</span>
                  </div>
                  <div className="mini-audio-track">
                    <div className="audio-bar" />
                    <div className="audio-bar tall" />
                    <div className="audio-bar" />
                    <div className="audio-bar tall" />
                    <div className="audio-bar active" />
                    <div className="audio-bar" />
                  </div>
                </div>
              )}
            </div>

            {/* Card info */}
            <div className="media-card-info">
              <div className="media-card-title">{item.title}</div>
              <div className="media-card-desc">{item.meta}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
