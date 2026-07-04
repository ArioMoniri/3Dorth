// Header controls, right-hand side:
//   * "Switch to trame UI" — navigates to config.trame_url when a public tunnel
//     is up, else the local fallback http://localhost:8081.
//   * "Share" — reveals a small popover with the current public URL (copyable)
//     when config.public is set, else a hint to run ./scripts/share.sh.
//
// config comes from GET /api/config: { app, react_url, trame_url, public }.

import { useState } from 'react';

const TRAME_FALLBACK = 'http://localhost:8081';

export default function ShareSwitch({ config }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const isPublic = Boolean(config?.public);
  // This app is React; "the other UI" is trame. Prefer the public tunnel URL.
  const switchUrl = config?.trame_url || TRAME_FALLBACK;
  // The public URL to share for THIS (React) UI.
  const shareUrl = config?.react_url || null;

  const copy = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (e.g. non-secure context) — leave the field for the
      // user to select manually.
      setCopied(false);
    }
  };

  return (
    <div className="share-switch">
      <button
        className="hdr-btn"
        onClick={() => {
          window.location.assign(switchUrl);
        }}
        title={`Open the trame UI (${switchUrl})`}
      >
        Switch to trame UI
      </button>

      <div className="share-wrap">
        <button
          className={`hdr-btn${open ? ' active' : ''}`}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          Share
        </button>
        {open && (
          <div className="share-popover" role="dialog" aria-label="Share this UI">
            {isPublic && shareUrl ? (
              <>
                <div className="share-popover-title">Public link (React UI)</div>
                <div className="share-row">
                  <input
                    className="share-url"
                    readOnly
                    value={shareUrl}
                    onFocus={(e) => e.target.select()}
                  />
                  <button className="share-copy" onClick={copy}>
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <div className="share-hint">
                  Anyone with this link reaches the running React app.
                </div>
              </>
            ) : (
              <>
                <div className="share-popover-title">No public link yet</div>
                <div className="share-hint">
                  Start a tunnel with{' '}
                  <code>./scripts/share.sh</code> to get a shareable URL, then
                  reload this page.
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
