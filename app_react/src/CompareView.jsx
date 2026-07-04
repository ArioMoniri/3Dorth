// Phase IV — linked compare cross-sections (side by side).
//
// Renders TWO MPRViewer instances: LEFT = reference volume, RIGHT = target
// volume. The link is wired through the LOCKED /compare-slice-map endpoint:
// when the reference viewer reports a crosshair change, we POST
// { reference_side, target_side, world_xyz_mm } (debounced) and feed the
// returned target.slices into the right viewer's externalCrosshair prop.
//
// Honesty rail: the server tells us whether the registration is reliable
// (inlier_fraction >= threshold). We NEVER hide an unreliable registration —
// the banner turns amber and states the note + inlier_fraction verbatim, and
// makes clear the right panel's matched slice should not be trusted.

import { useEffect, useRef, useState } from 'react';

import { compareSliceMap } from './api';
import MPRViewer from './mpr/MPRViewer';

const DEBOUNCE_MS = 120;

// Convert the server's {axial,coronal,sagittal} slice-index dict into the
// {ix,iy,iz} voxel shape MPRViewer's externalCrosshair expects.
// axial fixes z, coronal fixes y, sagittal fixes x (array-oriented planes) —
// same convention App.jsx uses for pickedCrosshair from pick-to-slices.
function slicesToCrosshair(slices, seq) {
  if (!slices) return null;
  return {
    ix: slices.sagittal,
    iy: slices.coronal,
    iz: slices.axial,
    _seq: seq,
  };
}

export default function CompareView({
  sessionId,
  referenceSide,
  targetSide,
  params,
  manualTransform,
}) {
  const [targetCrosshair, setTargetCrosshair] = useState(null);
  const [registration, setRegistration] = useState(null);
  const [linkError, setLinkError] = useState(null);
  const [linking, setLinking] = useState(false);

  const debounceRef = useRef(null);
  const requestIdRef = useRef(0);
  const seqRef = useRef(0);

  // Reset the link state whenever the pair of sides (or session) changes —
  // a stale registration banner from a previous pair must never linger.
  useEffect(() => {
    setTargetCrosshair(null);
    setRegistration(null);
    setLinkError(null);
  }, [sessionId, referenceSide, targetSide]);

  async function pushLink(worldXyz) {
    if (!sessionId || !referenceSide || !targetSide) return;
    const myId = (requestIdRef.current += 1);
    setLinking(true);
    try {
      const res = await compareSliceMap(sessionId, {
        referenceSide,
        targetSide,
        worldXyz,
        params,
        manualTransform,
      });
      if (requestIdRef.current !== myId) return; // superseded — drop stale
      seqRef.current += 1;
      setTargetCrosshair(slicesToCrosshair(res.target.slices, seqRef.current));
      setRegistration(res.registration);
      setLinkError(null);
    } catch (e) {
      if (requestIdRef.current !== myId) return;
      setLinkError(e?.message || String(e));
    } finally {
      if (requestIdRef.current === myId) setLinking(false);
    }
  }

  // Debounced handler for the reference viewer's crosshair changes.
  function onReferenceCrosshairChange(_voxel, worldXyz) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      pushLink(worldXyz);
    }, DEBOUNCE_MS);
  }

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  return (
    <div className="compare-view">
      {registration && (
        <div
          className={`compare-banner ${registration.reliable ? 'reliable' : 'unreliable'}`}
        >
          {registration.reliable ? (
            <>
              <strong>Registration reliable.</strong> {registration.note} (rms{' '}
              {registration.rms_mm} mm · inlier fraction{' '}
              {registration.inlier_fraction})
            </>
          ) : (
            <>
              <strong>Registration UNRELIABLE — do not trust the target slice.</strong>{' '}
              {registration.note} (rms {registration.rms_mm} mm · inlier fraction{' '}
              {registration.inlier_fraction})
            </>
          )}
        </div>
      )}
      {linkError && (
        <div className="compare-banner unreliable">
          <strong>Could not link slices.</strong> {linkError}
        </div>
      )}
      {!registration && !linkError && (
        <div className="compare-banner pending">
          Move the crosshair in the reference volume (left) to link a matching
          slice in the target volume (right). {linking ? 'Linking…' : ''}
        </div>
      )}

      <div className="compare-grid">
        <div className="compare-pane">
          <div className="compare-pane-label">Reference volume</div>
          <MPRViewer
            sessionId={sessionId}
            side={referenceSide}
            externalCrosshair={null}
            onCrosshairChange={onReferenceCrosshairChange}
          />
        </div>
        <div className="compare-pane">
          <div className="compare-pane-label">
            Target volume
            {registration && !registration.reliable && (
              <span className="compare-pane-warn"> · unreliable match</span>
            )}
          </div>
          <MPRViewer
            sessionId={sessionId}
            side={targetSide}
            externalCrosshair={targetCrosshair}
            onCrosshairChange={() => {}}
          />
        </div>
      </div>
    </div>
  );
}
