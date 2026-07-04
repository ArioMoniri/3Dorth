// Header controls, right-hand side:
//   * The public Cloudflare link for THIS (React) UI, shown INLINE + copyable
//     (like the trame header) as soon as a tunnel is up — not hidden behind a
//     click. When there is no tunnel it shows "Local only" with a hint.
//   * "Switch to trame UI" — the other frontend (its public URL when available,
//     else the local fallback).
//
// config comes from GET /api/config: { app, react_url, trame_url, public }, and
// App.jsx polls it every ~6 s so this updates live after a tunnel (re)starts.

import { useState } from 'react';

const TRAME_FALLBACK = 'http://localhost:8081';

export default function ShareSwitch({ config }) {
  const [copied, setCopied] = useState(false);

  const isPublic = Boolean(config?.public);
  const switchUrl = config?.trame_url || TRAME_FALLBACK;
  const shareUrl = config?.react_url || null;

  const copy = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="share-switch">
      {isPublic && shareUrl ? (
        <div className="share-inline" title="Public Cloudflare link for the React UI">
          <span className="share-label">Public link</span>
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
      ) : (
        <span
          className="share-none"
          title="No public tunnel running — start one with ./scripts/share.sh"
        >
          Local only
        </span>
      )}

      <button
        className="hdr-btn"
        onClick={() => window.location.assign(switchUrl)}
        title={`Open the trame UI (${switchUrl})`}
      >
        Switch to trame UI
      </button>
    </div>
  );
}
