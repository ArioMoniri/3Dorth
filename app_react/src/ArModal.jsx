// Phase V — "View in AR" modal: in-page 3D (rotate/zoom, works everywhere) plus
// a one-tap AR launch on Android (Scene Viewer via glTF/GLB). iOS Quick Look
// needs a USDZ asset which the server does NOT generate, so we say so plainly
// rather than implying AR works everywhere — see the caption under the viewer.
//
// <model-viewer> is a web component registered globally by importing
// '@google/model-viewer' (side-effect import in main.jsx). It fetches its
// `src` itself, so modelGlbUrl(sessionId) — a plain "/api/..." path that
// flows through the Vite dev proxy — is all it needs.
//
// Phase VI adds a second tab: "Cross-section (3D/AR)", a three.js clipping
// plane through the SAME computed surface (see ./ar/ClipViewer.jsx). It works
// everywhere the model-viewer tab works, and additionally offers a real WebXR
// 'immersive-ar' session when the device/browser supports it (feature-detected
// — no assumption of support, degrades to a plain note otherwise).

import { useState } from 'react';

import { modelGlbUrl } from './api';
import ClipViewer from './ar/ClipViewer';

export default function ArModal({ sessionId, onClose }) {
  const src = modelGlbUrl(sessionId);
  const [tab, setTab] = useState('viewer'); // 'viewer' | 'clip'

  return (
    <div className="ar-modal-backdrop" onClick={onClose}>
      <div className="ar-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ar-modal-head">
          <div className="ar-modal-title">View in AR / 3D</div>
          <div className="ar-modal-tabs" role="group" aria-label="AR view mode">
            <button
              type="button"
              className={tab === 'viewer' ? 'active' : ''}
              onClick={() => setTab('viewer')}
            >
              Model viewer
            </button>
            <button
              type="button"
              className={tab === 'clip' ? 'active' : ''}
              onClick={() => setTab('clip')}
            >
              Cross-section (3D/AR)
            </button>
          </div>
          <button
            type="button"
            className="ar-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {tab === 'viewer' ? (
          <>
            <div className="ar-modal-body">
              {/* eslint-disable-next-line react/no-unknown-property */}
              <model-viewer
                src={src}
                camera-controls="true"
                ar="true"
                ar-modes="webxr scene-viewer quick-look"
                shadow-intensity="0.6"
                exposure="1"
                style={{ width: '100%', height: '100%', background: '#0c0c10' }}
              >
                <button slot="ar-button" className="ar-modal-arbtn" type="button">
                  View in your space
                </button>
              </model-viewer>
            </div>

            <div className="ar-modal-caption">
              In-browser 3D works everywhere; one-tap AR placement works on Android
              (glTF/Scene Viewer). iOS AR (USDZ) is not yet supported.
            </div>
            <div className="ar-modal-note">
              Research / de-identified / not for diagnosis. Array-oriented geometry
              — no radiological orientation is implied.
            </div>
          </>
        ) : (
          <div className="ar-modal-body ar-modal-body-clip">
            <ClipViewer sessionId={sessionId} />
          </div>
        )}
      </div>
    </div>
  );
}
