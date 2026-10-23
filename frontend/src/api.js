/**
 * api.js — OmniLens API client
 * All calls hit http://127.0.0.1:8000 (configurable via VITE_API_URL).
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

async function handleResponse(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.message ?? body.detail ?? JSON.stringify(body);
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/** POST /upload — multipart form, returns { source_id, chunk_count, ... } */
export async function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE_URL}/upload`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error('Invalid JSON from /upload'));
        }
      } else {
        let detail = `HTTP ${xhr.status}`;
        try { detail = JSON.parse(xhr.responseText).message ?? JSON.parse(xhr.responseText).detail ?? detail; } catch { /* */ }
        reject(new Error(detail));
      }
    };

    xhr.onerror = () => reject(new Error('Network error on upload'));
    xhr.send(formData);
  });
}

/** GET /sources — returns { sources: [...] } */
export async function fetchSources() {
  const res = await fetch(`${BASE_URL}/sources`);
  return handleResponse(res);
}

/** GET /source/:sourceId — returns { source_id, chunk_count, chunks: [...] } */
export async function fetchSourceChunks(sourceId) {
  const res = await fetch(`${BASE_URL}/source/${sourceId}`);
  return handleResponse(res);
}

/** POST /query (non-streaming) */
export async function postQuery(question, topK = 5, sourceId = null, mode = 'auto', allowGeneral = true, history = []) {
  const payload = {
    question,
    top_k: topK,
    mode,
    allow_general: allowGeneral,
    history,
  };
  if (sourceId) {
    payload.source_id = sourceId;
  }
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse(res);
}

/** POST /query/stream — Server-Sent Events streaming */
export async function streamQuery({
  question,
  topK = 5,
  sourceId = null,
  mode = 'auto',
  allowGeneral = true,
  history = [],
  signal,
  onStage,
  onToken,
  onMeta,
  onError,
  onDone,
}) {
  const payload = {
    question,
    top_k: topK,
    mode,
    allow_general: allowGeneral,
    history,
  };
  if (sourceId) {
    payload.source_id = sourceId;
  }

  let res;
  try {
    res = await fetch(`${BASE_URL}/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) {
      if (onDone) onDone();
      return;
    }
    if (onError) {
      onError({
        error_code: 'internal_error',
        message: 'Could not connect to the backend server. Is it running?',
        retryable: true,
      });
    }
    return;
  }

  if (!res.ok) {
    let errObj = {
      error_code: 'internal_error',
      message: `Server returned error (${res.status}).`,
      retryable: true,
    };
    try {
      const data = await res.json();
      if (data.error_code && data.message) {
        errObj = data;
      }
    } catch { /* ignore */ }
    if (onError) onError(errObj);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const jsonStr = trimmed.slice(5).trim();
        if (!jsonStr) continue;

        try {
          const event = JSON.parse(jsonStr);
          if (event.type === 'stage' && onStage) {
            onStage(event.stage);
          } else if (event.type === 'token' && onToken) {
            onToken(event.text);
          } else if (event.type === 'meta' && onMeta) {
            onMeta(event);
          } else if (event.type === 'error' && onError) {
            onError({
              error_code: event.error_code,
              message: event.message,
              retryable: event.retryable ?? true,
            });
          } else if (event.type === 'done' && onDone) {
            onDone();
          }
        } catch (jsonErr) {
          console.warn('Failed to parse SSE event:', jsonErr);
        }
      }
    }
    if (onDone) onDone();
  } catch (err) {
    if (signal?.aborted) {
      if (onDone) onDone();
      return;
    }
    if (onError) {
      onError({
        error_code: 'internal_error',
        message: 'Stream connection interrupted. Please try again.',
        retryable: true,
      });
    }
  }
}

/** GET /health */
export async function healthCheck() {
  try {
    const res = await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

/** DELETE /source/:sourceId — returns { deleted, removed_chunks } or error */
export async function deleteSource(sourceId) {
  const res = await fetch(`${BASE_URL}/source/${sourceId}`, { method: 'DELETE' });
  return handleResponse(res);
}

/** POST /source/:sourceId/reindex — returns { queued, source_id } or error */
export async function reindexSource(sourceId) {
  const res = await fetch(`${BASE_URL}/source/${sourceId}/reindex`, { method: 'POST' });
  return handleResponse(res);
}

/** GET /sources/:sourceId/status — returns { status, stage, progress, chunk_count, error_message } */
export async function fetchSourceStatus(sourceId) {
  const res = await fetch(`${BASE_URL}/sources/${sourceId}/status`);
  return handleResponse(res);
}

