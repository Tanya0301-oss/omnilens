import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { healthCheck } from '../api';
import { IconUpload, IconSearch, IconLogo } from '../Icons';
import UploadView from '../views/UploadView';
import QueryView from '../views/QueryView';
import SourceDetailView from '../views/SourceDetailView';

const VIEWS = {
  UPLOAD: 'upload',
  QUERY: 'query',
  SOURCE_DETAIL: 'source_detail',
};

function Sidebar({ activeView, onNav, mobileOpen, onCloseMobile }) {
  return (
    <aside className={`sidebar${mobileOpen ? ' mobile-open' : ''}`}>
      {/* Sidebar Brand Header */}
      <div className="sidebar-logo">
        <Link to="/" className="sidebar-logo-link" title="OmniLens Home">
          <div className="sidebar-logo-icon">
            <IconLogo size={15} />
          </div>
          <div className="sidebar-logo-text-wrap">
            <div className="sidebar-logo-text">OmniLens</div>
            <div className="sidebar-logo-sub">Multimodal RAG</div>
          </div>
        </Link>
        {onCloseMobile && (
          <button
            className="sidebar-mobile-close"
            onClick={onCloseMobile}
            aria-label="Close sidebar"
          >
            ✕
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="nav-label">WORKSPACE</div>

        <button
          id="nav-query"
          className={`nav-item${activeView === VIEWS.QUERY ? ' active' : ''}`}
          onClick={() => {
            onNav(VIEWS.QUERY);
            if (onCloseMobile) onCloseMobile();
          }}
        >
          <IconSearch size={14} />
          <span>Query</span>
        </button>

        <button
          id="nav-upload"
          className={`nav-item${activeView === VIEWS.UPLOAD || activeView === VIEWS.SOURCE_DETAIL ? ' active' : ''}`}
          onClick={() => {
            onNav(VIEWS.UPLOAD);
            if (onCloseMobile) onCloseMobile();
          }}
        >
          <IconUpload size={14} />
          <span>Sources</span>
        </button>
      </nav>

      {/* API Connection Telemetry */}
      <div className="sidebar-footer">
        <div className="sidebar-status-wrap">
          <span className="status-dot" id="status-dot" />
          <span className="sidebar-status-text">API connected</span>
        </div>
        <Link to="/" className="sidebar-home-link">
          Landing ↗
        </Link>
      </div>
    </aside>
  );
}

function Topbar({
  view,
  sourceFilename,
  onToggleMobile,
  sourcesCount,
  onRefreshSources,
}) {
  const titles = {
    [VIEWS.QUERY]: {
      title: 'Query',
      crumb: 'Ask questions across your indexed sources.',
      badge: 'GROUNDED Q&A',
    },
    [VIEWS.UPLOAD]: {
      title: 'Sources',
      crumb: 'Upload and manage your knowledge base.',
      badge: 'INGESTION',
    },
    [VIEWS.SOURCE_DETAIL]: {
      title: sourceFilename ?? 'Source Inspection',
      crumb: 'Examine extracted chunks and evidence locations',
      badge: 'CHUNKS',
    },
  };
  const { title, crumb, badge } = titles[view] ?? { title: '', crumb: '', badge: '' };

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button
          className="topbar-hamburger"
          onClick={onToggleMobile}
          aria-label="Toggle navigation"
        >
          ☰
        </button>
        <div>
          <div className="topbar-title-row">
            <h1 className="topbar-title">{title}</h1>
            <span className="topbar-badge">{badge}</span>
          </div>
          <div className="topbar-breadcrumb">{crumb}</div>
        </div>
      </div>

      <div className="topbar-right">
        {view === VIEWS.UPLOAD && (
          <div className="topbar-sources-controls">
            {sourcesCount != null && (
              <span className="source-counter-pill">
                <span className="counter-dot" />
                {sourcesCount} source{sourcesCount === 1 ? '' : 's'}
              </span>
            )}
            {onRefreshSources && (
              <button
                onClick={onRefreshSources}
                className="refresh-sources-btn"
                title="Refresh sources"
              >
                ↺ Refresh
              </button>
            )}
          </div>
        )}
        <Link to="/" className="topbar-back-link">
          ← Overview
        </Link>
      </div>
    </header>
  );
}

export default function Dashboard() {
  const [view, setView] = useState(VIEWS.QUERY);
  const [selectedSource, setSelectedSource] = useState(null);
  const [, setOnline] = useState(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sourcesInfo, setSourcesInfo] = useState({ count: null, refresh: null });
  const [deletedSourceId, setDeletedSourceId] = useState(null);

  // Poll API health
  useEffect(() => {
    const check = async () => {
      const ok = await healthCheck();
      setOnline(ok);
      const dot = document.getElementById('status-dot');
      if (dot) {
        dot.className = `status-dot${ok ? '' : ' offline'}`;
        const statusText = dot.nextSibling;
        if (statusText) {
          statusText.textContent = ok ? 'API connected' : 'API offline';
        }
      }
    };
    check();
    const interval = setInterval(check, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleViewSource = (source) => {
    setSelectedSource(source);
    setView(VIEWS.SOURCE_DETAIL);
  };

  const handleBackFromDetail = () => {
    setView(VIEWS.UPLOAD);
    setSelectedSource(null);
  };

  const handleNav = (target) => {
    if (target !== VIEWS.SOURCE_DETAIL) setSelectedSource(null);
    setView(target);
  };

  const handleSourceDeleted = (sourceId) => {
    setDeletedSourceId(sourceId);
    // Clear after a tick so QueryView can react
    setTimeout(() => setDeletedSourceId(null), 200);
  };

  return (
    <div className="app-shell">
      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <Sidebar
        activeView={view}
        onNav={handleNav}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      <main className="main-content">
        <Topbar
          view={view}
          sourceFilename={selectedSource?.source_filename}
          onToggleMobile={() => setMobileSidebarOpen(!mobileSidebarOpen)}
          sourcesCount={sourcesInfo.count}
          onRefreshSources={sourcesInfo.refresh}
        />

        <div className="main-view-container">
          {view === VIEWS.QUERY && <QueryView deletedSourceId={deletedSourceId} />}

          {view === VIEWS.UPLOAD && (
            <UploadView
              onViewSource={handleViewSource}
              onSourcesUpdate={setSourcesInfo}
              onSourceDeleted={handleSourceDeleted}
            />
          )}

          {view === VIEWS.SOURCE_DETAIL && selectedSource && (
            <SourceDetailView
              source={selectedSource}
              onBack={handleBackFromDetail}
            />
          )}
        </div>
      </main>
    </div>
  );
}
