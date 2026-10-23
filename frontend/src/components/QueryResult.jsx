import React from 'react';
import CitationChip from './CitationChip';

/**
 * QueryResult — Displays grounded question-answer pairs with citation chips
 * and latency metadata. Used in real chat view and product previews.
 */
export default function QueryResult({
  question = 'What were the main findings in the research?',
  answer = 'The study identified three primary conclusions: first, multimodal indexing reduced retrieval error by 41% across mixed documents; second, cross-attention reranking improved precise region alignment; and third, grounding validation eliminated unsupported statements.',
  citations = [
    { filename: 'report.pdf', page: 14, score: 0.912 },
    { filename: 'research.png', region: '03', score: 0.874 },
  ],
  latency = {
    embed: 38,
    retrieve: 19,
    rerank: 22,
    gen: 285,
    total: 364,
  },
  cacheHit = false,
  className = '',
}) {
  return (
    <div className={`query-result-block ${className}`}>
      {/* User Question */}
      <div className="query-question-wrap">
        <div className="query-avatar">Q</div>
        <div className="query-question-text">{question}</div>
      </div>

      {/* OmniLens Grounded Answer */}
      <div className="query-answer-wrap">
        <div className="query-answer-header">
          <span className="query-answer-badge">
            <span className="answer-pulse" />
            Grounded synthesis
          </span>
          {cacheHit && (
            <span className="query-cache-badge">⚡ Cache Hit</span>
          )}
        </div>

        <div className="query-answer-body">
          {answer}
        </div>

        {/* Citations section */}
        {citations && citations.length > 0 && (
          <div className="query-citations-row">
            <span className="citations-label">Sources cited:</span>
            <div className="citations-list">
              {citations.map((c, i) => (
                <CitationChip
                  key={i}
                  filename={c.filename}
                  page={c.page}
                  region={c.region}
                  score={c.score}
                />
              ))}
            </div>
          </div>
        )}

        {/* Latency timing breakdown */}
        {latency && (
          <div className="query-latency-bar">
            {latency.embed != null && (
              <span className="latency-pill embed">embed {latency.embed}ms</span>
            )}
            {latency.retrieve != null && (
              <span className="latency-pill retrieve">retrieve {latency.retrieve}ms</span>
            )}
            {latency.rerank != null && (
              <span className="latency-pill rerank">rerank {latency.rerank}ms</span>
            )}
            {latency.gen != null && (
              <span className="latency-pill gen">gen {latency.gen}ms</span>
            )}
            {latency.total != null && (
              <span className="latency-pill total">total {latency.total}ms</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
