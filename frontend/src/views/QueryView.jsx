import { useState, useEffect, useRef, useCallback } from 'react';
import { streamQuery, fetchSources } from '../api';
import { IconSearch } from '../Icons';
import CitationChip from '../components/CitationChip';

const STAGE_LABELS = {
  rewriting: 'Understanding question…',
  searching: 'Searching documents…',
  reranking: 'Ranking results…',
  generating: 'Writing answer…',
};

function StageIndicator({ stage }) {
  const text = STAGE_LABELS[stage] ?? 'Analyzing sources…';
  return (
    <div className="query-thinking-state">
      <div className="thinking-dots-anim">
        <span className="thinking-pip" />
        <span className="thinking-pip" />
        <span className="thinking-pip" />
      </div>
      <span className="thinking-text">{text}</span>
    </div>
  );
}

function LatencyTelemetryBar({ latency, cacheHit, modelUsed, modeUsed }) {
  if (!latency && !modeUsed && !modelUsed) return null;
  const segments = [
    { key: 'embedding_ms', label: 'embed' },
    { key: 'retrieval_ms', label: 'retrieve' },
    { key: 'reranking_ms', label: 'rerank' },
    { key: 'generation_ms', label: 'gen' },
    { key: 'total_ms', label: 'total' },
  ];

  return (
    <div className="query-telemetry-bar">
      {modeUsed && (
        <span className="telemetry-item" title="Retrieval mode used">
          <span className="telemetry-label">mode</span>
          <span className="telemetry-val mode-val">{modeUsed}</span>
        </span>
      )}
      {segments.map(({ key, label }) => {
        const val = latency?.[key] ?? (latency?.[key.replace('_ms', '')]);
        return val != null ? (
          <span key={key} className={`telemetry-item ${key === 'total_ms' ? 'total' : ''}`}>
            <span className="telemetry-label">{label}</span>
            <span className="telemetry-val">{val}ms</span>
          </span>
        ) : null;
      })}
      {cacheHit && (
        <span className="telemetry-item cache">
          <span className="telemetry-val">⚡ cache hit</span>
        </span>
      )}
      {modelUsed && (
        <span className="telemetry-item" title="Groq model used for this answer">
          <span className="telemetry-label">model</span>
          <span className="telemetry-val">{modelUsed}</span>
        </span>
      )}
    </div>
  );
}

function CitationChipsList({ citations }) {
  if (!citations?.length) return null;
  return (
    <div className="query-citations-section">
      <span className="citations-header-tag">Sources cited</span>
      <div className="citations-chip-flex">
        {citations.map((c, i) => (
          <CitationChip
            key={i}
            filename={c.source_filename ?? c.chunk_id ?? `source-${i}`}
            page={c.page_number}
            region={c.chunk_type === 'image_region' ? (c.page_number ?? '01') : null}
            score={c.rerank_score ?? c.score}
          />
        ))}
      </div>
    </div>
  );
}

function ChatEntryCard({ entry, onRetry }) {
  const isGeneralKnowledge = entry.answer_source === 'general_knowledge';
  const isNotFound = entry.answer_source === 'not_found';

  return (
    <div className="chat-conversation-item">
      {/* User Query Bubble */}
      <div className="chat-user-query">
        <div className="user-query-avatar">Q</div>
        <div className="user-query-content">{entry.question}</div>
      </div>

      {/* System Response Card */}
      <div className="chat-system-response">
        {entry.loading && !entry.answer ? (
          <StageIndicator stage={entry.stage} />
        ) : entry.error ? (
          <div className="query-error-card-calm">
            <div className="error-card-body">
              <span className="error-card-icon">⚠</span>
              <span className="error-card-msg">
                {typeof entry.error === 'object' ? entry.error.message : entry.error}
              </span>
            </div>
            {onRetry && (
              <button
                className="error-retry-action-btn"
                onClick={() => onRetry(entry.question)}
              >
                Retry
              </button>
            )}
          </div>
        ) : (
          <div className={`grounded-answer-card ${isGeneralKnowledge ? 'general-knowledge-card' : ''}`}>
            <div className="grounded-card-header">
              {isGeneralKnowledge ? (
                <span className="grounded-header-tag general-knowledge-tag">
                  <span className="gk-pulse-dot" />
                  GENERAL KNOWLEDGE
                </span>
              ) : isNotFound ? (
                <span className="grounded-header-tag not-found-tag">
                  NOT FOUND IN SOURCES
                </span>
              ) : (
                <span className="grounded-header-tag">
                  <span className="grounded-pulse-dot" />
                  GROUNDED ANSWER
                </span>
              )}
            </div>

            {/* Muted Notice line if falling back */}
            {entry.notice && (
              <div className="muted-notice-line">
                {entry.notice}
              </div>
            )}

            <div className="grounded-card-body">
              {entry.answer}
              {entry.loading && <span className="streaming-cursor">▍</span>}
            </div>

            {/* Citations only for document answers */}
            {!isGeneralKnowledge && !isNotFound && (
              <CitationChipsList citations={entry.cited_chunks ?? entry.citations} />
            )}

            {/* Telemetry and Rewritten Query */}
            <div className="card-footer-telemetry">
              {entry.rewritten_question && entry.rewritten_question !== entry.question && (
                <div className="telemetry-rewritten-line">
                  Searched for: <em>"{entry.rewritten_question}"</em>
                </div>
              )}
              <LatencyTelemetryBar
                latency={entry.latency_ms}
                cacheHit={entry.cache_hit}
                modelUsed={entry.model_used}
                modeUsed={entry.mode_used}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function QueryWelcomeScreen({ onSelectPrompt }) {
  const suggestions = [
    'What are the key conclusions or findings reported?',
    'Summarize the financial performance and quarterly revenue.',
    'Explain the architecture or methodology diagram.',
  ];

  return (
    <div className="query-welcome-root">
      <div className="welcome-symbol-wrap">
        <IconSearch size={22} />
      </div>
      <h3 className="welcome-headline">Ask your knowledge base.</h3>
      <p className="welcome-description">
        Ask questions across your indexed sources with grounded citations, streaming
        answers, and general-knowledge fallback.
      </p>

      <div className="welcome-suggestions">
        <span className="suggestions-label">Suggested questions:</span>
        <div className="suggestions-row">
          {suggestions.map((s, idx) => (
            <button
              key={idx}
              className="suggestion-btn"
              onClick={() => onSelectPrompt(s)}
            >
              "{s}"
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function QueryView({ deletedSourceId }) {
  const [history, setHistory] = useState([]);
  const [draft, setDraft] = useState('');
  const [topK, setTopK] = useState(5);
  const [sources, setSources] = useState([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [allowGeneral, setAllowGeneral] = useState(() => {
    return localStorage.getItem('omnilens_allow_general') !== 'false';
  });
  const [isQuerying, setIsQuerying] = useState(false);

  const bottomRef = useRef(null);
  const textareaRef = useRef(null);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  useEffect(() => {
    fetchSources()
      .then((data) => {
        if (data && Array.isArray(data.sources)) {
          setSources(data.sources.filter((s) => s.status === 'ready'));
        }
      })
      .catch((err) => {
        console.warn('Failed to load sources for query dropdown:', err);
      });
  }, []);

  // When a source is deleted from UploadView, clear it from the dropdown
  useEffect(() => {
    if (!deletedSourceId) return;
    setSources((prev) => prev.filter((s) => s.source_id !== deletedSourceId));
    setSelectedSourceId((prev) => (prev === deletedSourceId ? '' : prev));
  }, [deletedSourceId]);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsQuerying(false);
  };

  const executeQuery = useCallback(async (questionText) => {
    const question = questionText.trim();
    if (!question || isQuerying) return;

    const entryId = Date.now();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    // Gather up to the last 3 turns from history
    const previousTurns = history
      .filter((h) => h.answer && !h.error)
      .slice(-3)
      .map((h) => ({
        question: h.question,
        answer: h.answer.slice(0, 400),
      }));

    setHistory((prev) => [
      ...prev,
      {
        id: entryId,
        question,
        loading: true,
        stage: previousTurns.length ? 'rewriting' : 'searching',
        answer: '',
      },
    ]);
    setDraft('');
    setIsQuerying(true);

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    await streamQuery({
      question,
      topK,
      sourceId: selectedSourceId || null,
      mode: 'auto',
      allowGeneral,
      history: previousTurns,
      signal: abortController.signal,
      onStage: (stage) => {
        setHistory((prev) =>
          prev.map((e) => (e.id === entryId ? { ...e, stage } : e))
        );
      },
      onToken: (text) => {
        setHistory((prev) =>
          prev.map((e) =>
            e.id === entryId ? { ...e, answer: e.answer + text } : e
          )
        );
      },
      onMeta: (meta) => {
        setHistory((prev) =>
          prev.map((e) =>
            e.id === entryId
              ? {
                  ...e,
                  cited_chunks: meta.cited_chunks ?? [],
                  answer_source: meta.answer_source ?? 'documents',
                  notice: meta.notice ?? null,
                  mode_used: meta.mode_used ?? 'focused',
                  model_used: meta.model_used ?? null,
                  latency_ms: meta.latency_ms ?? null,
                  rewritten_question: meta.rewritten_question ?? null,
                  cache_hit: meta.cache_hit ?? false,
                }
              : e
          )
        );
      },
      onError: (err) => {
        setHistory((prev) =>
          prev.map((e) =>
            e.id === entryId ? { ...e, loading: false, error: err } : e
          )
        );
      },
      onDone: () => {
        setHistory((prev) =>
          prev.map((e) => (e.id === entryId ? { ...e, loading: false } : e))
        );
        setIsQuerying(false);
      },
    });
  }, [history, isQuerying, topK, selectedSourceId, allowGeneral]);

  const submit = () => {
    executeQuery(draft);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="query-view-root">
      {/* Scrollable Conversation Stream */}
      <div className="chat-stream-viewport">
        {history.length === 0 ? (
          <QueryWelcomeScreen onSelectPrompt={(text) => setDraft(text)} />
        ) : null}

        {history.map((entry) => (
          <ChatEntryCard
            key={entry.id}
            entry={entry}
            onRetry={entry.error ? (q) => executeQuery(q) : null}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Pinned Bottom Input Deck */}
      <div className="chat-input-deck">
        <div className="chat-input-shell">
          <div className="chat-input-row">
            <textarea
              ref={textareaRef}
              id="chat-input"
              className="chat-textarea"
              rows={1}
              placeholder="Ask a question about your sources... (Shift+Enter for newline)"
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                autoResize();
              }}
              onKeyDown={onKeyDown}
              disabled={isQuerying}
            />

            {isQuerying ? (
              <button
                id="stop-btn"
                className="query-stop-btn"
                onClick={handleStop}
                title="Stop generation"
              >
                ■ Stop
              </button>
            ) : (
              <button
                id="send-btn"
                className="query-submit-btn"
                onClick={submit}
                disabled={!draft.trim() || isQuerying}
                aria-label="Submit question"
                title="Submit question"
              >
                <span className="send-arrow">↑</span>
              </button>
            )}
          </div>

          <div className="input-toolbar-row">
            <div className="toolbar-left" style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <label htmlFor="source-select" className="top-k-label">
                  SOURCE:
                </label>
                <select
                  id="source-select"
                  className="top-k-dropdown"
                  value={selectedSourceId}
                  onChange={(e) => setSelectedSourceId(e.target.value)}
                  style={{ maxWidth: '180px' }}
                >
                  <option value="">All sources</option>
                  {sources.map((s) => (
                    <option key={s.source_id} value={s.source_id}>
                      {s.source_filename || s.source_id}
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <label htmlFor="top-k-select" className="top-k-label">
                  TOP-K:
                </label>
                <select
                  id="top-k-select"
                  className="top-k-dropdown"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                >
                  {[3, 5, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n} chunks
                    </option>
                  ))}
                </select>
              </div>

              {/* Allow General Knowledge Toggle */}
              <label className="general-toggle-container" title="Fall back to general knowledge if sources do not contain the answer">
                <input
                  type="checkbox"
                  id="general-knowledge-toggle"
                  className="general-toggle-checkbox"
                  checked={allowGeneral}
                  onChange={(e) => {
                    setAllowGeneral(e.target.checked);
                    localStorage.setItem('omnilens_allow_general', String(e.target.checked));
                  }}
                />
                <span className="general-toggle-text">Allow general knowledge</span>
              </label>
            </div>
            <span className="input-hint-key">Press Enter to send</span>
          </div>

        </div>
      </div>
    </div>
  );
}
