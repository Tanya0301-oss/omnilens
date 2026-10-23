import { useState, useCallback, useEffect, useRef } from 'react';
import { uploadFile, fetchSources, deleteSource, reindexSource, fetchSourceStatus } from '../api';
import { IconUpload, IconEye, IconTrash, IconRefresh } from '../Icons';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceIcon({ type }) {
  const isPdf = type === 'pdf';
  return (
    <div className={`source-icon-badge ${isPdf ? 'pdf' : 'image'}`}>
      {isPdf ? 'PDF' : 'IMG'}
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

/** Animated dots progress for queued/processing state */
function StatusBadge({ status, stage, progress }) {
  if (status === 'ready') {
    return <span className="sm-status-badge sm-ready">Ready</span>;
  }
  if (status === 'failed') {
    return <span className="sm-status-badge sm-failed">Failed</span>;
  }
  if (status === 'queued') {
    return <span className="sm-status-badge sm-queued">Queued</span>;
  }
  if (status === 'processing') {
    return (
      <span className="sm-status-badge sm-processing">
        <span className="sm-spinner" />
        {stage ?? 'Processing'} {progress != null ? `${progress}%` : ''}
      </span>
    );
  }
  return <span className="sm-status-badge">{status}</span>;
}

/** Trap focus inside a dialog element */
function useFocusTrap(ref, active) {
  useEffect(() => {
    if (!active || !ref.current) return;
    const el = ref.current;
    const focusable = el.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const onKey = (e) => {
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
      if (e.key === 'Escape') { /* handled by parent */ }
    };
    el.addEventListener('keydown', onKey);
    first?.focus();
    return () => el.removeEventListener('keydown', onKey);
  }, [active, ref]);
}

/** Confirmation dialog with focus trap and Escape support */
function ConfirmDialog({ open, title, body, confirmLabel, confirmDanger, onConfirm, onCancel }) {
  const ref = useRef(null);
  useFocusTrap(ref, open);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="sm-dialog-overlay" role="dialog" aria-modal="true" aria-labelledby="sm-dialog-title">
      <div className="sm-dialog-box" ref={ref}>
        <h3 className="sm-dialog-title" id="sm-dialog-title">{title}</h3>
        <p className="sm-dialog-body">{body}</p>
        <div className="sm-dialog-actions">
          <button
            id="sm-cancel-btn"
            className="sm-btn sm-btn-ghost"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            id="sm-confirm-btn"
            className={`sm-btn ${confirmDanger ? 'sm-btn-danger' : 'sm-btn-primary'}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Toast notification that auto-dismisses */
function Toast({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="sm-toast-stack" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`sm-toast sm-toast-${t.type}`}>
          <span>{t.message}</span>
          <button
            className="sm-toast-close"
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss notification"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

/** Row action buttons for a source */
function SourceActions({
  source,
  onInspect,
  onDelete,
  onReindex,
  busy,
}) {
  const isBusy = source.status === 'queued' || source.status === 'processing' || busy;

  return (
    <div className="sm-source-actions" onClick={(e) => e.stopPropagation()}>
      {source.status === 'failed' && (
        <button
          id={`reindex-retry-${source.source_id}`}
          className="sm-action-btn sm-try-again"
          title="Try indexing again"
          onClick={() => onReindex(source, true)}
          disabled={busy}
        >
          <IconRefresh size={12} />
          <span>Try again</span>
        </button>
      )}

      <button
        id={`inspect-btn-${source.source_id}`}
        className="sm-action-btn sm-inspect"
        title="Inspect source chunks"
        onClick={() => onInspect(source)}
      >
        <IconEye size={13} />
        <span className="inspect-label">Inspect</span>
      </button>

      <button
        id={`reindex-btn-${source.source_id}`}
        className="sm-action-btn sm-reindex"
        title={isBusy ? 'Cannot re-index while processing' : 'Re-index this source'}
        onClick={() => onReindex(source, false)}
        disabled={isBusy}
        aria-disabled={isBusy}
      >
        <IconRefresh size={12} />
        <span>Re-index</span>
      </button>

      <button
        id={`delete-btn-${source.source_id}`}
        className="sm-action-btn sm-delete"
        title={isBusy ? 'Cannot delete while processing' : 'Delete this source'}
        onClick={() => onDelete(source)}
        disabled={isBusy}
        aria-disabled={isBusy}
      >
        <IconTrash size={12} />
        <span>Delete</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main UploadView
// ---------------------------------------------------------------------------

let _toastId = 0;

export default function UploadView({ onViewSource, onSourcesUpdate, onSourceDeleted }) {
  const [sources, setSources] = useState([]);
  const [loadingSources, setLoadingSources] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState([]);
  const inputRef = useRef(null);

  // Polling state: map from source_id → interval id
  const pollingRefs = useRef({});

  // Dialog state
  const [deleteDialog, setDeleteDialog] = useState(null);   // { source }
  const [reindexDialog, setReindexDialog] = useState(null); // { source }
  const [busyIds, setBusyIds] = useState(new Set());

  // Toast state
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'success') => {
    const id = ++_toastId;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // ---------------------------------------------------------------------------
  // Polling for active (queued/processing) sources
  // ---------------------------------------------------------------------------

  const stopPolling = useCallback((sourceId) => {
    if (pollingRefs.current[sourceId]) {
      clearInterval(pollingRefs.current[sourceId]);
      delete pollingRefs.current[sourceId];
    }
  }, []);

  const startPolling = useCallback((sourceId) => {
    if (pollingRefs.current[sourceId]) return;
    const intervalId = setInterval(async () => {
      try {
        const data = await fetchSourceStatus(sourceId);
        setSources((prev) =>
          prev.map((s) =>
            s.source_id === sourceId
              ? {
                  ...s,
                  status: data.status,
                  stage: data.stage,
                  progress: data.progress,
                  chunk_count: data.chunk_count,
                  error_message: data.error_message,
                }
              : s
          )
        );
        if (data.status === 'ready' || data.status === 'failed') {
          stopPolling(sourceId);
          if (data.status === 'ready') {
            addToast(`"${data.filename}" indexed successfully.`);
          } else if (data.status === 'failed') {
            addToast(data.error_message ?? 'Indexing failed. Use Re-index to try again.', 'error');
          }
        }
      } catch {
        // backend may be restarting — keep polling
      }
    }, 1500);
    pollingRefs.current[sourceId] = intervalId;
  }, [stopPolling, addToast]);

  // Clean up all intervals on unmount
  useEffect(() => {
    return () => {
      Object.values(pollingRefs.current).forEach(clearInterval);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Load sources
  // ---------------------------------------------------------------------------

  const loadSources = useCallback(async () => {
    try {
      const data = await fetchSources();
      const list = data.sources ?? [];
      setSources(list);
      // Start polling for any active sources
      list.forEach((s) => {
        if (s.status === 'queued' || s.status === 'processing') {
          startPolling(s.source_id);
        }
      });
    } catch {
      // silently fail — backend may be starting
    } finally {
      setLoadingSources(false);
    }
  }, [startPolling]);

  useEffect(() => {
    let ignore = false;
    fetchSources()
      .then((data) => {
        if (!ignore) {
          const list = data.sources ?? [];
          setSources(list);
          setLoadingSources(false);
          list.forEach((s) => {
            if (s.status === 'queued' || s.status === 'processing') {
              startPolling(s.source_id);
            }
          });
        }
      })
      .catch(() => {
        if (!ignore) setLoadingSources(false);
      });
    return () => { ignore = true; };
  }, [startPolling]);

  useEffect(() => {
    if (onSourcesUpdate) {
      onSourcesUpdate({ count: sources.length, refresh: loadSources });
    }
  }, [sources.length, loadSources, onSourcesUpdate]);

  // ---------------------------------------------------------------------------
  // Upload handling
  // ---------------------------------------------------------------------------

  const handleFiles = useCallback(
    async (files) => {
      const allowed = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'];
      const valid = Array.from(files).filter((f) => allowed.includes(f.type));
      if (!valid.length) return;

      const newEntries = valid.map((f) => ({
        id: Math.random().toString(36).slice(2),
        name: f.name,
        progress: 0,
        status: 'uploading',
        error: null,
      }));

      setUploads((prev) => [...newEntries, ...prev]);

      for (const [i, file] of valid.entries()) {
        const entryId = newEntries[i].id;
        try {
          const result = await uploadFile(file, (pct) => {
            setUploads((prev) =>
              prev.map((u) => (u.id === entryId ? { ...u, progress: pct } : u))
            );
          });
          setUploads((prev) =>
            prev.map((u) => (u.id === entryId ? { ...u, status: 'done', progress: 100 } : u))
          );
          // Start polling the new source_id
          if (result?.source_id) {
            startPolling(result.source_id);
          }
        } catch (err) {
          setUploads((prev) =>
            prev.map((u) =>
              u.id === entryId ? { ...u, status: 'error', error: err.message } : u
            )
          );
        }
      }

      await loadSources();
    },
    [loadSources, startPolling]
  );

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  const handleDeleteClick = useCallback((source) => {
    setDeleteDialog({ source });
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    const source = deleteDialog?.source;
    if (!source) return;
    setDeleteDialog(null);
    setBusyIds((prev) => new Set(prev).add(source.source_id));

    try {
      await deleteSource(source.source_id);
      stopPolling(source.source_id);
      setSources((prev) => prev.filter((s) => s.source_id !== source.source_id));
      addToast(`"${source.filename ?? source.source_filename}" deleted.`);
      if (onSourceDeleted) onSourceDeleted(source.source_id);
    } catch (err) {
      addToast(err.message ?? 'Delete failed. Please try again.', 'error');
    } finally {
      setBusyIds((prev) => { const n = new Set(prev); n.delete(source.source_id); return n; });
    }
  }, [deleteDialog, stopPolling, addToast, onSourceDeleted]);

  // ---------------------------------------------------------------------------
  // Re-index
  // ---------------------------------------------------------------------------

  const handleReindexClick = useCallback((source, skipConfirm) => {
    if (skipConfirm) {
      // "Try again" on failed row — no confirm needed
      executeReindex(source);
    } else {
      setReindexDialog({ source });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const executeReindex = useCallback(async (source) => {
    setBusyIds((prev) => new Set(prev).add(source.source_id));
    setReindexDialog(null);

    try {
      await reindexSource(source.source_id);
      // Update local state to queued
      setSources((prev) =>
        prev.map((s) =>
          s.source_id === source.source_id
            ? { ...s, status: 'queued', stage: 'Queued for re-indexing', progress: 0, error_message: null }
            : s
        )
      );
      addToast(`Re-indexing "${source.filename ?? source.source_filename}" started.`);
      startPolling(source.source_id);
    } catch (err) {
      addToast(err.message ?? 'Re-index failed. Please try again.', 'error');
    } finally {
      setBusyIds((prev) => { const n = new Set(prev); n.delete(source.source_id); return n; });
    }
  }, [addToast, startPolling]);

  const handleReindexConfirm = useCallback(async () => {
    const source = reindexDialog?.source;
    if (!source) return;
    executeReindex(source);
  }, [reindexDialog, executeReindex]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="upload-view-root">
      {/* Toast stack */}
      <Toast toasts={toasts} onDismiss={dismissToast} />

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={!!deleteDialog}
        title={`Delete "${deleteDialog?.source?.filename ?? deleteDialog?.source?.source_filename}"?`}
        body="This removes the file and its indexed content. This cannot be undone."
        confirmLabel="Delete"
        confirmDanger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteDialog(null)}
      />

      {/* Re-index confirmation dialog */}
      <ConfirmDialog
        open={!!reindexDialog}
        title={`Re-index "${reindexDialog?.source?.filename ?? reindexDialog?.source?.source_filename}"?`}
        body="Processing will run again. Existing answers may be refreshed."
        confirmLabel="Re-index"
        confirmDanger={false}
        onConfirm={handleReindexConfirm}
        onCancel={() => setReindexDialog(null)}
      />

      {/* Ingestion Compact Panel */}
      <section className="ingestion-section">
        <div className="section-label-bar">
          <span className="panel-eyebrow">INGEST DOCUMENTS</span>
          <span className="panel-hint">Supported: PDF · Images</span>
        </div>

        <label
          className={`ingestion-drop-zone${dragOver ? ' drag-over' : ''}`}
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
        >
          <div className="drop-zone-icon-wrap">
            <IconUpload size={22} />
          </div>
          <div className="drop-zone-content">
            <span className="drop-zone-primary-text">Drop files here or browse</span>
            <span className="drop-zone-secondary-text">PDF · PNG · JPG · WEBP</span>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.gif"
            multiple
            onChange={(e) => handleFiles(e.target.files)}
          />
        </label>
      </section>

      {/* Active Ingestion Progress Stack */}
      {uploads.length > 0 && (
        <section className="recent-uploads-stack">
          <div className="section-label-bar">
            <span className="panel-eyebrow">RECENT PROCESSING QUEUE</span>
          </div>
          <div className="uploads-list">
            {uploads.map((u) => (
              <div key={u.id} className="upload-item-card">
                <div className="upload-item-header">
                  <span className="upload-item-filename">{u.name}</span>
                  <span className="upload-item-status">
                    {u.status === 'uploading' && `${u.progress}%`}
                    {u.status === 'done' && '✓ Indexed'}
                    {u.status === 'error' && '✗ Error'}
                  </span>
                </div>
                {u.status === 'uploading' && (
                  <div className="upload-progress-track">
                    <div className="upload-progress-fill" style={{ width: `${u.progress}%` }} />
                  </div>
                )}
                {u.status === 'error' && (
                  <div className="upload-error-msg">{u.error}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Ingested Sources Table/List */}
      <section className="sources-list-section">
        <div className="section-label-bar">
          <span className="panel-eyebrow">
            INGESTED SOURCES {sources.length > 0 ? `(${sources.length})` : ''}
          </span>
          <span className="panel-hint">Click a source to inspect extracted chunks</span>
        </div>

        {loadingSources ? (
          <div className="sources-empty-state">
            <div className="loading-spinner" />
            <span>Loading sources from index...</span>
          </div>
        ) : sources.length === 0 ? (
          <div className="sources-empty-state">
            <div className="empty-state-symbol">📂</div>
            <div className="empty-state-title">No sources indexed yet</div>
            <p className="empty-state-desc">
              Drop a PDF or image into the ingestion panel above to generate your multimodal knowledge index.
            </p>
          </div>
        ) : (
          <div className="sources-table-wrap">
            {sources.map((s) => {
              const isBusy = s.status === 'queued' || s.status === 'processing' || busyIds.has(s.source_id);
              return (
                <div
                  key={s.source_id}
                  className={`source-row-card ${isBusy ? 'source-row-busy' : ''}`}
                  role="group"
                  aria-label={`Source: ${s.filename ?? s.source_filename}`}
                >
                  {/* Clickable left area goes to inspect */}
                  <div
                    className="source-row-left"
                    onClick={() => onViewSource(s)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') onViewSource(s); }}
                    style={{ cursor: 'pointer', flex: 1, minWidth: 0 }}
                  >
                    <SourceIcon type={s.source_type} />
                    <div className="source-row-info">
                      <div className="source-row-name" title={s.filename ?? s.source_filename}>
                        {s.filename ?? s.source_filename}
                      </div>
                      <div className="source-row-meta">
                        <span>{formatDate(s.created_at)}</span>
                        <span className="meta-sep">·</span>
                        <span className="meta-chunks">
                          {s.chunk_count ?? 0} chunk{(s.chunk_count ?? 0) !== 1 ? 's' : ''}
                        </span>
                        <span className="meta-sep">·</span>
                        <StatusBadge
                          status={s.status}
                          stage={s.stage}
                          progress={s.progress}
                        />
                      </div>
                      {s.status === 'failed' && s.error_message && (
                        <div className="source-row-error">{s.error_message}</div>
                      )}
                    </div>
                  </div>

                  <div className="source-row-right">
                    <span className={`source-type-tag ${s.source_type}`}>
                      {s.source_type.toUpperCase()}
                    </span>
                    <SourceActions
                      source={s}
                      onInspect={onViewSource}
                      onDelete={handleDeleteClick}
                      onReindex={handleReindexClick}
                      busy={busyIds.has(s.source_id)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
