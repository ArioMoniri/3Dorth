// Phase VI — in-AR / in-3D clipping-plane cross-section.
//
// A three.js canvas that loads the SAME computed surface as the "View in AR"
// model-viewer (GET /api/session/{sid}/model.glb, per-vertex colour baked in)
// and lets the user scrub a clipping plane through it to inspect a
// cross-section. This works on every browser/device (desktop, iOS, Android) —
// it does NOT require WebXR.
//
// If the browser additionally exposes navigator.xr with an 'immersive-ar'
// session, we ALSO show an "Enter AR" button that starts a real WebXR AR
// session (Android Chrome only, broadly) and keeps the same clip-plane
// controls live while in AR. Everywhere else the button is hidden and we say
// so plainly — the desktop 3D clip always works regardless of WebXR support.
//
// Honesty rail: this reuses the exact GLB the server baked colours into. We
// never fabricate geometry or a slice; the clip plane is a pure client-side
// render-time cut through the real computed mesh. Coordinates are the app's
// array-oriented world frame (identity direction) — no radiological
// orientation is implied anywhere in this view.

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { modelGlbUrl } from '../api';

const AXES = ['x', 'y', 'z'];
const AXIS_NORMAL = {
  x: new THREE.Vector3(-1, 0, 0),
  y: new THREE.Vector3(0, -1, 0),
  z: new THREE.Vector3(0, 0, -1),
};

export default function ClipViewer({ sessionId }) {
  const mountRef = useRef(null);
  const stateRef = useRef({}); // three.js objects that must survive re-renders

  const [axis, setAxis] = useState('z');
  const [sliderPos, setSliderPos] = useState(0.5); // 0..1 along the bbox extent
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [errorMsg, setErrorMsg] = useState(null);
  const [xrSupported, setXrSupported] = useState(false);
  const [xrChecked, setXrChecked] = useState(false);
  const [inAr, setInAr] = useState(false);

  const axisRef = useRef(axis);
  const sliderRef = useRef(sliderPos);
  axisRef.current = axis;
  sliderRef.current = sliderPos;

  // ---- feature-detect WebXR immersive-ar (never assume support) -----------
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        if (navigator.xr && navigator.xr.isSessionSupported) {
          const ok = await navigator.xr.isSessionSupported('immersive-ar');
          if (!cancelled) setXrSupported(Boolean(ok));
        } else {
          if (!cancelled) setXrSupported(false);
        }
      } catch {
        if (!cancelled) setXrSupported(false);
      } finally {
        if (!cancelled) setXrChecked(true);
      }
    }
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  // ---- mount the three.js scene --------------------------------------------
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const width = mount.clientWidth || 640;
    const height = mount.clientHeight || 480;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0c0c10);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 5000);
    camera.position.set(0, 0, 300);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    renderer.localClippingEnabled = true;
    renderer.xr.enabled = true;
    mount.appendChild(renderer.domElement);

    const hemi = new THREE.HemisphereLight(0xffffff, 0x33333a, 1.1);
    scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 0.6);
    dir.position.set(1, 1, 1);
    scene.add(dir);

    // Simple orbit-style manual rotation (no OrbitControls dependency — keep
    // the dependency surface small): drag to rotate the model, wheel to zoom.
    const rig = new THREE.Group();
    scene.add(rig);

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    const onPointerDown = (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onPointerMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      rig.rotation.y += dx * 0.01;
      rig.rotation.x += dy * 0.01;
    };
    const onPointerUp = () => {
      dragging = false;
    };
    const onWheel = (e) => {
      e.preventDefault();
      camera.position.z = Math.max(
        20,
        Math.min(2000, camera.position.z * (1 + e.deltaY * 0.001)),
      );
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false });

    const clipPlane = new THREE.Plane(AXIS_NORMAL.z.clone(), 0);
    let mesh = null;
    let bbox = null;
    let cancelled = false;

    function applyClip() {
      if (!bbox || !mesh) return;
      const a = axisRef.current;
      const t = sliderRef.current;
      const min = bbox.min[a];
      const max = bbox.max[a];
      const worldCoord = min + t * (max - min);
      clipPlane.normal.copy(AXIS_NORMAL[a]);
      // Plane constant so that points with coord < worldCoord are kept
      // (normal is negative-axis, so constant = worldCoord satisfies
      // normal.dot(p) + constant >= 0  <=>  -coord + worldCoord >= 0).
      clipPlane.constant = worldCoord;
    }

    const loader = new GLTFLoader();
    const url = modelGlbUrl(sessionId);
    loader.load(
      url,
      (gltf) => {
        if (cancelled) return;
        const root = gltf.scene;
        root.traverse((child) => {
          if (child.isMesh) {
            mesh = child;
            const mat = child.material;
            const mats = Array.isArray(mat) ? mat : [mat];
            mats.forEach((m) => {
              if (!m) return;
              m.clippingPlanes = [clipPlane];
              m.clipShadows = true;
              m.side = THREE.DoubleSide; // show the cut face, not a hollow shell
              m.vertexColors = true;
              m.needsUpdate = true;
            });
          }
        });
        rig.add(root);

        bbox = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3();
        bbox.getSize(size);
        const center = new THREE.Vector3();
        bbox.getCenter(center);
        root.position.sub(center); // center the model in the rig
        bbox.translate(root.position);

        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        camera.position.set(0, 0, maxDim * 2.2);
        camera.near = maxDim * 0.01;
        camera.far = maxDim * 20;
        camera.updateProjectionMatrix();

        applyClip();
        setStatus('ready');
      },
      undefined,
      (err) => {
        if (cancelled) return;
        setStatus('error');
        setErrorMsg(err?.message || String(err));
      },
    );

    let raf = null;
    function renderLoop() {
      applyClip();
      renderer.render(scene, camera);
    }
    renderer.setAnimationLoop(renderLoop);

    function onResize() {
      const w = mount.clientWidth || width;
      const h = mount.clientHeight || height;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(mount);

    stateRef.current = { renderer, camera, applyClip };

    return () => {
      cancelled = true;
      if (raf) cancelAnimationFrame(raf);
      renderer.setAnimationLoop(null);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('wheel', onWheel);
      renderer.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Re-apply the clip immediately when axis/slider change (render loop also
  // re-applies every frame, but this avoids a one-frame lag on drag-end).
  useEffect(() => {
    stateRef.current.applyClip?.();
  }, [axis, sliderPos]);

  async function enterAr() {
    const { renderer } = stateRef.current;
    if (!renderer || !navigator.xr) return;
    try {
      const session = await navigator.xr.requestSession('immersive-ar', {
        optionalFeatures: ['local-floor'],
      });
      renderer.xr.setSession(session);
      setInAr(true);
      session.addEventListener('end', () => setInAr(false));
    } catch (e) {
      setErrorMsg(e?.message || String(e));
    }
  }

  return (
    <div className="clipviewer">
      <div className="clipviewer-canvas-wrap" ref={mountRef}>
        {status === 'loading' && (
          <div className="clipviewer-overlay">
            <div className="spinner" />
            <div>Loading computed surface…</div>
          </div>
        )}
        {status === 'error' && (
          <div className="clipviewer-overlay clipviewer-error">
            <strong>Could not load the surface.</strong>
            <div>{errorMsg}</div>
          </div>
        )}
      </div>

      <div className="clipviewer-controls">
        <div className="clipviewer-row">
          <span className="clipviewer-label">Clip axis</span>
          <div className="clipviewer-axis-group" role="group" aria-label="Clip axis">
            {AXES.map((a) => (
              <button
                key={a}
                type="button"
                className={a === axis ? 'active' : ''}
                onClick={() => setAxis(a)}
              >
                {a.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="clipviewer-row">
          <span className="clipviewer-label">Cross-section position</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.001}
            value={sliderPos}
            onChange={(e) => setSliderPos(Number(e.target.value))}
            aria-label="Clip plane position"
          />
          <span className="clipviewer-value">{(sliderPos * 100).toFixed(0)}%</span>
        </div>

        <div className="clipviewer-row clipviewer-ar-row">
          {xrChecked && xrSupported ? (
            <button type="button" className="clipviewer-ar-btn" onClick={enterAr} disabled={inAr}>
              {inAr ? 'In AR…' : 'Enter AR'}
            </button>
          ) : xrChecked ? (
            <div className="clipviewer-ar-note">
              AR not available on this device/browser (WebXR immersive-ar
              required — Android Chrome). The 3D cross-section above works
              everywhere.
            </div>
          ) : (
            <div className="clipviewer-ar-note">Checking AR support…</div>
          )}
        </div>
      </div>

      <div className="clipviewer-note">
        Research / de-identified / not for diagnosis. Array-oriented geometry
        (world = index × spacing + offset, identity direction) — axes are X/Y/Z
        of that frame, not radiological orientation or laterality.
      </div>
    </div>
  );
}
