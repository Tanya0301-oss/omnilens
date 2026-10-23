import { useState, useEffect } from 'react';
import { fetchSourceChunks } from '../api';
import { IconChevronLeft } from '../Icons';

function ChunkCard({ chunk }) {
  const isImage = chunk.chunk_type === 'image_region';
  return (
    <div className="chunk-inspector-card">
      <div className="chunk-card-topbar">
        <div className="chunk-id-tag" title={chunk.id}>
          <span className="chunk-id-symbol">#</span>
          <span className="chunk-id-val">{chunk.id}</span>
        </div>

        <div className="chunk-meta-tags">
          {chunk.page_number != null && (
            <span className="chunk-page-pill">Page {chunk.page_number}</span>
          )}
          <span className={`chunk-kind-badge ${isImage ? 'image' : 'text'}`}>
            {isImage ? 'IMAGE REGION' : 'TEXT CHUNK'}
          </span>
        </div>
      </div>

      <div className="chunk-body-viewport">
        {isImage
          ? `[Extracted Visual Region]\nTarget path: ${chunk.content_image_path ?? '—'}\nCoordinates: bounding box verified`
          : (chunk.content_text ?? '(No textual content)')}
      </div>
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function SourceDetailView({ source, onBack }) {
  const [chunks, setChunks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    let isMounted = true;
    fetchSourceChunks(source.source_id)
      .then((data) => {
        if (isMounted) setChunks(data.chunks ?? []);
      })
      .catch((err) => {
        if (isMounted) setError(err.message);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [source.source_id]);

  const textCount = chunks.filter((c) => c.chunk_type !== 'image_region').length;
  const imageCount = chunks.filter((c) => c.chunk_type === 'image_region').length;

  const filtered =
    filter === 'all'
      ? chunks
      : filter === 'text'
      ? chunks.filter((c) => c.chunk_type !== 'image_region')
      : chunks.filter((c) => c.chunk_type === 'image_region');

  return (
    <div className="source-detail-root">
      {/* Return button */}
      <button className="back-to-sources-btn" onClick={onBack} id="back-to-sources">
        <IconChevronLeft size={13} />
        <span>Return to Sources</span>
      </button>

      {/* Source Metadata Overview Panel */}
      <div className="source-overview-panel">
        <div className="source-overview-header">
          <div className="source-title-row">
            <span className={`source-type-pill ${source.source_type}`}>
              {source.source_type.toUpperCase()}
            </span>
            <h2 className="source-detail-filename">{source.source_filename}</h2>
          </div>
        </div>

        <div className="source-stats-grid">
          <div className="stat-brick">
            <span className="stat-brick-label">INGESTED CHUNKS</span>
            <span className="stat-brick-val">{source.chunk_count}</span>
          </div>
          <div className="stat-brick">
            <span className="stat-brick-label">FORMAT TYPE</span>
            <span className="stat-brick-val">{source.source_type.toUpperCase()}</span>
          </div>
          <div className="stat-brick">
            <span className="stat-brick-label">TIMESTAMP</span>
            <span className="stat-brick-val">{formatDate(source.created_at)}</span>
          </div>
          <div className="stat-brick">
            <span className="stat-brick-label">SOURCE IDENTIFIER</span>
            <span className="stat-brick-val mono">
              {source.source_id.slice(0, 12)}…
            </span>
          </div>
        </div>
      </div>

      {/* Filter Tabs Bar */}
      <div className="chunks-filter-bar">
        <div className="filter-tabs-group">
          {[
            { key: 'all', label: `All Chunks (${chunks.length})` },
            { key: 'text', label: `Text (${textCount})` },
            { key: 'image', label: `Images (${imageCount})` },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`filter-tab-pill${filter === tab.key ? ' active' : ''}`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* State Viewport */}
      {loading && (
        <div className="chunks-empty-box">
          <div className="loading-spinner" />
          <span>Fetching chunk embeddings from index...</span>
        </div>
      )}

      {error && (
        <div className="query-error-card">
          <span className="error-icon">⚠</span>
          <span className="error-text">{error}</span>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="chunks-empty-box">
          <span>No chunks match the current filter selection.</span>
        </div>
      )}

      {!loading && !error && (
        <div className="chunks-stack-view">
          {filtered.map((chunk) => (
            <ChunkCard key={chunk.id} chunk={chunk} />
          ))}
        </div>
      )}
    </div>
  );
}
