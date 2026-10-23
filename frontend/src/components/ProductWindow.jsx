import React from 'react';

/**
 * ProductWindow — Reusable realistic desktop window frame for OmniLens UI previews.
 * Features realistic title bar, system dots, status pill, and content viewport.
 */
export default function ProductWindow({
  title = 'OmniLens — Multimodal Workspace',
  status = 'Index active',
  children,
  className = '',
  sidebarContent = null,
}) {
  return (
    <div className={`product-window ${className}`}>
      {/* Top Chrome Bar */}
      <div className="product-window-header">
        <div className="product-window-controls">
          <span className="window-dot" />
          <span className="window-dot" />
          <span className="window-dot" />
        </div>
        <div className="product-window-title">
          <span className="product-window-appname">OmniLens</span>
          <span className="product-window-divider">/</span>
          <span className="product-window-subtitle">{title}</span>
        </div>
        <div className="product-window-meta">
          <span className="window-status-badge">
            <span className="window-status-dot" />
            {status}
          </span>
        </div>
      </div>

      {/* Main Window Body */}
      <div className="product-window-layout">
        {sidebarContent && (
          <aside className="product-window-sidebar">
            {sidebarContent}
          </aside>
        )}
        <div className="product-window-canvas">
          {children}
        </div>
      </div>
    </div>
  );
}
