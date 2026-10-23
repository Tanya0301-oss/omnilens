import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import Button from '../components/Button';
import CitationChip from '../components/CitationChip';
import DocumentPreview from '../components/DocumentPreview';
import SourceHighlight from '../components/SourceHighlight';
import MediaPreview from '../components/MediaPreview';
import Pipeline from '../components/Pipeline';
import heroIllustration from '../assets/omnilens-hero.png';

export default function Landing() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [activeEvidenceTab, setActiveEvidenceTab] = useState('bbox');

  const scrollTo = (id) => (e) => {
    e.preventDefault();
    setMobileMenuOpen(false);
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="landing-root">
      {/* ============================================================
          1. REFINED STICKY NAVBAR
          ============================================================ */}
      <header className="navbar-sticky">
        <div className="navbar-inner">
          {/* Left: OmniLens Wordmark */}
          <Link to="/" className="navbar-brand">
            <span className="navbar-logo-symbol">O</span>
            <span className="navbar-logo-text">OmniLens</span>
          </Link>

          {/* Center: Navigation Links */}
          <nav className={`navbar-links${mobileMenuOpen ? ' mobile-open' : ''}`}>
            <a href="#product" onClick={scrollTo('product')} className="nav-link">
              Product
            </a>
            <a href="#how-it-works" onClick={scrollTo('how-it-works')} className="nav-link">
              How it works
            </a>
            <a href="#capabilities" onClick={scrollTo('capabilities')} className="nav-link">
              Capabilities
            </a>
            <a href="#principles" onClick={scrollTo('principles')} className="nav-link">
              Architecture
            </a>
          </nav>

          {/* Right: Try it out CTA */}
          <div className="navbar-actions">
            <Button to="/app" className="nav-cta-btn">
              Try it out
            </Button>
            <button
              className="navbar-mobile-toggle"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle Navigation Menu"
            >
              <span className={`toggle-line${mobileMenuOpen ? ' open' : ''}`} />
              <span className={`toggle-line${mobileMenuOpen ? ' open' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      <main className="landing-content">
        {/* ============================================================
            2. HERO SECTION (Two-Part Composition)
            ============================================================ */}
        <section id="product" className="hero-section">
          {/* Subtle atmospheric dark crimson radial ambient light */}
          <div className="hero-ambient-glow" />

          <div className="hero-layout">
            {/* Left: Headline, Value Proposition, Action Buttons */}
            <div className="hero-left">
              <div className="hero-eyebrow">
                <span className="eyebrow-pip" />
                MULTIMODAL AI INTELLIGENCE
              </div>

              <h1 className="hero-title">
                Ask anything across your documents, images, and media.
              </h1>

              <p className="hero-subtitle">
                Upload PDFs, images, and other media. OmniLens indexes their text and visual
                content so you can ask natural-language questions and trace every answer back to its source.
              </p>

              <div className="hero-cta-group">
                <Button to="/app" className="hero-primary-btn">
                  Try it out
                </Button>
                <a
                  href="#how-it-works"
                  onClick={scrollTo('how-it-works')}
                  className="hero-secondary-anchor"
                >
                  Explore how it works ↓
                </a>
              </div>

              {/* Technical differentiator tags */}
              <div className="hero-feature-tags">
                <span className="feature-tag">Cross-modal retrieval</span>
                <span className="feature-tag">Two-stage reranking</span>
                <span className="feature-tag">Evidence grounding</span>
              </div>
            </div>

            {/* Right: Custom Multimodal AI Intelligence Lens Visual */}
            <div className="hero-right hero-visual-container">
              <div className="hero-visual-art-wrapper">
                <img
                  src={heroIllustration}
                  alt="OmniLens Multimodal AI Intelligence Core"
                  className="hero-lens-artwork"
                  loading="eager"
                />
                {/* Subtle technical metadata pins matching OmniLens design */}
                <div className="hero-pin pin-doc">
                  <span className="pin-dot" />
                  <span className="pin-text">BOUNDING REGION · TABLE 2.1</span>
                </div>
                <div className="hero-pin pin-media">
                  <span className="pin-dot media-dot" />
                  <span className="pin-text">TEMPORAL ANCHOR · 09:30:36</span>
                </div>
                <div className="hero-pin pin-lens">
                  <span className="pin-dot lens-dot" />
                  <span className="pin-text">FOCAL APERTURE · MULTIMODAL CORE</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ============================================================
            3. MEDIA INPUT VISUAL
            ============================================================ */}
        <section className="section-container media-inputs-section">
          <MediaPreview />
        </section>

        {/* ============================================================
            4. SECTION: ONE QUERY, MULTIPLE MODALITIES
            ============================================================ */}
        <section id="capabilities" className="section-container crossmodal-section">
          <div className="section-header">
            <span className="section-eyebrow">CROSS-MODAL SEARCH</span>
            <h2 className="section-headline">
              One question. Multiple kinds of evidence.
            </h2>
            <p className="section-description">
              A single query can retrieve relevant text, document regions, or visual content
              instead of searching each format separately.
            </p>
          </div>

          <div className="crossmodal-showcase">
            {/* Left: Input query state */}
            <div className="crossmodal-query-side">
              <div className="crossmodal-query-box">
                <span className="query-box-label">USER QUERY</span>
                <p className="query-box-text">
                  "What does the diagram on page 7 show?"
                </p>
                <div className="query-box-meta">
                  <span className="meta-pill">Shared Embedding Space</span>
                  <span className="meta-pill">Cosine Similarity Top-k = 5</span>
                </div>
              </div>

              <div className="crossmodal-explainer">
                <div className="explainer-bullet">
                  <span className="bullet-num">01</span>
                  <div>
                    <h4 className="bullet-title">Joint representation</h4>
                    <p className="bullet-text">Text tokens and image region features reside in the same embedding geometry.</p>
                  </div>
                </div>
                <div className="explainer-bullet">
                  <span className="bullet-num">02</span>
                  <div>
                    <h4 className="bullet-title">Cross-modal reranking</h4>
                    <p className="bullet-text">CrossEncoder scores both textual context and visual descriptions simultaneously.</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Heterogeneous evidence results */}
            <div className="crossmodal-results-side">
              <div className="results-list-header">
                <span className="results-title">RETRIEVED MULTIMODAL CANDIDATES</span>
                <span className="results-stats">3 of 5 chunks shown</span>
              </div>

              <div className="retrieval-cards">
                {/* Result 1: TEXT */}
                <div className="retrieval-item">
                  <div className="retrieval-meta">
                    <span className="badge-type text">TEXT</span>
                    <span className="retrieval-source">research.pdf · p. 7</span>
                    <span className="retrieval-score">score: 0.941</span>
                  </div>
                  <p className="retrieval-snippet">
                    "...Figure 3 illustrates the cross-attention alignment between image patch tokens
                    and layout boundary segments, demonstrating how visual coordinates match tabular values."
                  </p>
                </div>

                {/* Result 2: IMAGE REGION */}
                <div className="retrieval-item highlighted-item">
                  <div className="retrieval-meta">
                    <span className="badge-type image">IMAGE REGION</span>
                    <span className="retrieval-source">research.pdf · region 02</span>
                    <span className="retrieval-score">score: 0.934</span>
                  </div>
                  <div className="retrieval-image-preview">
                    <div className="diagram-sketch">
                      <div className="diagram-box">
                        <span className="diagram-label">ENCODER</span>
                      </div>
                      <span className="diagram-arrow">➔</span>
                      <div className="diagram-box accent">
                        <span className="diagram-label">FUSION</span>
                      </div>
                      <span className="diagram-arrow">➔</span>
                      <div className="diagram-box">
                        <span className="diagram-label">LLM</span>
                      </div>
                    </div>
                    <span className="diagram-caption">
                      [Extracted figure snippet: Architecture flow diagram, Page 7]
                    </span>
                  </div>
                </div>

                {/* Result 3: DOCUMENT / APPENDIX */}
                <div className="retrieval-item">
                  <div className="retrieval-meta">
                    <span className="badge-type text">DOCUMENT</span>
                    <span className="retrieval-source">appendix.pdf · p. 19</span>
                    <span className="retrieval-score">score: 0.887</span>
                  </div>
                  <p className="retrieval-snippet">
                    "...Experimental benchmark configurations confirming validation accuracy across
                    the 20 question-answer test set with verified bounding boxes."
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ============================================================
            5. SECTION: GROUNDED ANSWERS ("Answers you can trace.")
            ============================================================ */}
        <section className="section-container grounding-section">
          <div className="section-header">
            <span className="section-eyebrow">EVIDENCE GROUNDING</span>
            <h2 className="section-headline">
              Answers you can trace.
            </h2>
            <p className="section-description">
              Every synthesized claim links back to verifiable source locations, page numbers,
              and extracted bounding boxes.
            </p>
          </div>

          <div className="grounding-split-layout">
            {/* Left: Question -> Answer -> Citations */}
            <div className="grounding-left">
              <div className="grounding-query-card">
                <div className="grounding-tag">USER QUERY</div>
                <div className="grounding-question">
                  "What was the total quarterly revenue reported in Q3?"
                </div>
              </div>

              <div className="grounding-arrow-indicator">
                <span className="arrow-line" />
                <span className="arrow-tag">OMNILENS GENERATION WITH CITATIONS</span>
              </div>

              <div className="grounding-answer-card">
                <div className="grounding-tag">GROUNDED ANSWER</div>
                <p className="grounding-answer-text">
                  Q3 total revenue reached <mark className="highlight-pill">$48.2 million</mark>, driven
                  primarily by enterprise software subscriptions and cloud service contracts. Operating
                  margin expanded by 4.2% year over year during the same fiscal cycle.
                </p>

                <div className="grounding-citations-group">
                  <span className="citations-label">Source Evidence:</span>
                  <div className="citations-row">
                    <CitationChip filename="report.pdf" page={4} active={true} score={0.942} />
                    <CitationChip filename="q3_financials.pdf" page={12} score={0.885} />
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Exact Source Document Preview with Highlighted Region */}
            <div className="grounding-right">
              <div className="grounding-tabs">
                <button
                  className={`grounding-tab-btn${activeEvidenceTab === 'bbox' ? ' active' : ''}`}
                  onClick={() => setActiveEvidenceTab('bbox')}
                >
                  Region Coordinates [BBOX]
                </button>
                <button
                  className={`grounding-tab-btn${activeEvidenceTab === 'doc' ? ' active' : ''}`}
                  onClick={() => setActiveEvidenceTab('doc')}
                >
                  Document Sheet Preview
                </button>
              </div>

              {activeEvidenceTab === 'bbox' ? (
                <SourceHighlight
                  source="report.pdf"
                  location="Page 4 · Table 2.1"
                  score={0.942}
                  chunkType="financial_table_region"
                  excerpt="Fiscal Q3 consolidated software revenues reached $48.2M, representing 18.4% year-over-year organic expansion across enterprise contracts."
                />
              ) : (
                <DocumentPreview
                  filename="report.pdf"
                  page={4}
                  title="Q3 Performance Summary & Segment Breakdown"
                  highlightRegion="Region 03 · Table 2.1"
                  highlightText="Fiscal Q3 consolidated software revenues reached $48.2M, representing 18.4% organic expansion."
                />
              )}
            </div>
          </div>
        </section>

        {/* ============================================================
            6. SECTION: HOW OMNILENS WORKS (Technical Pipeline)
            ============================================================ */}
        <section id="how-it-works" className="section-container pipeline-section">
          <div className="section-header">
            <span className="section-eyebrow">SYSTEM ARCHITECTURE</span>
            <h2 className="section-headline">
              How OmniLens works
            </h2>
            <p className="section-description">
              A specialized multimodal pipeline designed around evidence verification, not ungrounded generation.
            </p>
          </div>

          <Pipeline />
        </section>

        {/* ============================================================
            7. SECTION: WHY OMNILENS (Technical Principles)
            ============================================================ */}
        <section id="principles" className="section-container principles-section">
          <div className="section-header">
            <span className="section-eyebrow">DESIGN PRINCIPLES</span>
            <h2 className="section-headline">
              Built around evidence, not just generation.
            </h2>
          </div>

          <div className="principles-grid">
            <div className="principle-card">
              <span className="principle-num">01</span>
              <h3 className="principle-title">MULTIMODAL</h3>
              <p className="principle-body">
                Text, images, layout, and media treated as first-class, searchable content rather than plain text summaries.
              </p>
            </div>

            <div className="principle-card">
              <span className="principle-num">02</span>
              <h3 className="principle-title">CROSS-MODAL</h3>
              <p className="principle-body">
                A single natural-language query can retrieve evidence from different content types across a shared vector space.
              </p>
            </div>

            <div className="principle-card">
              <span className="principle-num">03</span>
              <h3 className="principle-title">GROUNDED</h3>
              <p className="principle-body">
                Answers point back to exact source locations with page numbers, bounding box regions, or media timestamps.
              </p>
            </div>

            <div className="principle-card">
              <span className="principle-num">04</span>
              <h3 className="principle-title">RETRIEVE → RERANK → GENERATE</h3>
              <p className="principle-body">
                Relevant evidence is filtered and prioritized with cross-encoders before synthesizing the grounded response.
              </p>
            </div>
          </div>
        </section>

        {/* ============================================================
            8. FINAL CTA
            ============================================================ */}
        <section className="section-container final-cta-section">
          <div className="final-cta-card">
            <div className="final-cta-content">
              <h2 className="final-cta-headline">
                Your knowledge is already in your files.
              </h2>
              <p className="final-cta-subtext">
                Upload them. Ask questions. Follow the evidence.
              </p>
              <div className="final-cta-actions">
                <Button to="/app" className="cta-launch-btn">
                  Try OmniLens
                </Button>
              </div>
            </div>

            {/* Subtle product preview element beside CTA */}
            <div className="final-cta-visual">
              <div className="mini-card-preview">
                <div className="mini-preview-top">
                  <span className="mini-preview-dot" />
                  <span className="mini-preview-file">quarterly_brief.pdf</span>
                </div>
                <div className="mini-preview-text">
                  "Evidence validated across 3 cross-modal chunks with exact page pointers."
                </div>
                <div className="mini-preview-chips">
                  <CitationChip filename="brief.pdf" page={2} score={0.96} />
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ============================================================
          9. FOOTER
          ============================================================ */}
      <footer className="landing-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <span className="footer-title">OmniLens</span>
            <span className="footer-tagline">
              Multimodal AI Intelligence & Visual RAG Platform
            </span>
          </div>
          <div className="footer-meta">
            Built with FastAPI · ChromaDB · Groq · React
          </div>
        </div>
      </footer>
    </div>
  );
}
