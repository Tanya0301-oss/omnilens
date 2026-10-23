import React from 'react';

/**
 * Pipeline — Technical architecture pipeline diagram showing OmniLens's
 * 6-stage retrieve -> rerank -> generate process.
 */
export default function Pipeline({ className = '' }) {
  const steps = [
    {
      num: '01',
      stage: 'INGEST',
      focus: 'PDF / IMAGE / MEDIA',
      detail: 'Format parsing & chunking',
    },
    {
      num: '02',
      stage: 'UNDERSTAND',
      focus: 'TEXT + LAYOUT + VISUALS',
      detail: 'OCR & visual region extraction',
    },
    {
      num: '03',
      stage: 'INDEX',
      focus: 'SHARED EMBEDDING SPACE',
      detail: 'Unified multimodal vectors in ChromaDB',
    },
    {
      num: '04',
      stage: 'RETRIEVE',
      focus: 'SEMANTIC SEARCH',
      detail: 'Cross-modal candidate selection',
    },
    {
      num: '05',
      stage: 'RERANK',
      focus: 'RELEVANCE FILTERING',
      detail: 'Cross-encoder scoring & thresholding',
    },
    {
      num: '06',
      stage: 'GENERATE',
      focus: 'GROUNDED ANSWER',
      detail: 'Cited synthesis with page & region links',
    },
  ];

  return (
    <div className={`technical-pipeline-wrap ${className}`}>
      <div className="pipeline-flow">
        {steps.map((step, idx) => (
          <React.Fragment key={step.num}>
            <div className="pipeline-node">
              <div className="pipeline-node-num">{step.num}</div>
              <div className="pipeline-node-stage">{step.stage}</div>
              <div className="pipeline-node-focus">{step.focus}</div>
              <div className="pipeline-node-detail">{step.detail}</div>
            </div>

            {idx < steps.length - 1 && (
              <div className="pipeline-connector">
                <span className="pipeline-connector-line" />
                <span className="pipeline-connector-arrow">→</span>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
