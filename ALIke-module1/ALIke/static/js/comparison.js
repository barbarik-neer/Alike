/* Comparison page: synchronised playback driven by the DTW alignment path,
   live skeleton overlays from landmarks.json, and error navigation. */
(() => {
  const data = JSON.parse(document.getElementById('page-data').textContent);
  const errors = data.errors || [];
  const align = data.alignment || [];
  const fps = data.sample_fps || 10;
  const $ = (id) => document.getElementById(id);

  const vid = { reference: $('vid-reference'), learner: $('vid-learner') };
  const cv = { reference: $('cv-reference'), learner: $('cv-learner') };
  const vidAnnot = $('vid-annot');
  const hasVideo = !!(vid.reference && vid.learner);
  const ACCENT = { reference: '#42D9E8', learner: '#9065FF' };
  const SEV = { high: '#FF626F', medium: '#FFBF69', low: '#FFBF69' };   // low shares yellow with medium
  const OK = '#42C98A';
  const HIGHLIGHT_WINDOW = 0.5;       // seconds around an error that its joints stay highlighted

  // MediaPipe Pose landmark indices
  const JOINTS = {
    nose: [0], left_shoulder: [11], right_shoulder: [12], left_elbow: [13], right_elbow: [14],
    left_wrist: [15], right_wrist: [16], left_hip: [23], right_hip: [24], left_knee: [25],
    right_knee: [26], left_ankle: [27], right_ankle: [28],
    shoulders: [11, 12], hips: [23, 24], left_arm: [11, 13, 15], right_arm: [12, 14, 16],
    left_leg: [23, 25, 27], right_leg: [24, 26, 28],
    upper_body: [11, 12, 13, 14, 15, 16], lower_body: [23, 24, 25, 26, 27, 28],
  };
  const BONES = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
                 [23, 25], [25, 27], [24, 26], [26, 28]];
  const DOTS = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];

  let lm = null;            // landmarks.json
  let map = [];             // reference sample index -> (fractional) learner sample index
  let duration = data.duration || 0;
  let playing = false, speed = 1, selected = -1, annotMode = false;
  let virtualTime = 0;      // used when there are no videos (sample page)
  let pending = null;       // seek requested before video metadata arrived

  const label = (s) => String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const mmss = (s) => `${Math.floor(s / 60)}:${(Math.max(0, s) % 60).toFixed(1).padStart(4, '0')}`;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  // ---------------------------------------------------------- time <-> frame helpers
  const stamps = (side) => (lm && lm[side] && lm[side].timestamps) || null;
  const tsOf = (side, i) => { const t = stamps(side); return t && t[i] != null ? t[i] : i / fps; };
  function tsOfF(side, f) {                               // fractional index -> time
    const lo = Math.floor(f), hi = Math.ceil(f);
    const a = tsOf(side, lo), b = tsOf(side, hi);
    return a + (b - a) * (f - lo);
  }
  function idxAt(side, t) {                               // nearest sample index to a time
    const ts = stamps(side);
    if (!ts || !ts.length) return Math.max(0, Math.round(t * fps));
    let lo = 0, hi = ts.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (ts[mid] < t) lo = mid + 1; else hi = mid; }
    return lo > 0 && Math.abs(ts[lo - 1] - t) <= Math.abs(ts[lo] - t) ? lo - 1 : lo;
  }

  function buildMap() {
    const n = stamps('reference') ? stamps('reference').length
      : (align.length ? Math.max(...align.map((p) => p[0])) + 1 : 0);
    const sum = new Array(n).fill(0), cnt = new Array(n).fill(0);
    align.forEach(([r, l]) => { if (r < n) { sum[r] += l; cnt[r] += 1; } });
    let last = 0;
    map = [];
    for (let i = 0; i < n; i += 1) { if (cnt[i]) last = sum[i] / cnt[i]; map.push(last); }
  }

  function learnerTimeFor(refTime) {
    if (!map.length) return refTime;
    const ri = clamp(idxAt('reference', refTime), 0, map.length - 1);
    return tsOfF('learner', map[ri]);
  }
  function slopeAt(refTime) {                             // local learner-speed / reference-speed
    if (map.length < 3) return 1;
    const i = clamp(idxAt('reference', refTime), 0, map.length - 1), w = 5;
    const a = Math.max(0, i - w), b = Math.min(map.length - 1, i + w);
    const dRef = tsOf('reference', b) - tsOf('reference', a);
    const dLrn = tsOfF('learner', map[b]) - tsOfF('learner', map[a]);
    return dRef > 0 ? clamp(dLrn / dRef, 0.5, 2) : 1;
  }
  const errRefTime = (e) => (lm && e.reference_frame != null ? tsOf('reference', e.reference_frame) : e.timestamp);
  const errLrnTime = (e) => (lm && e.learner_frame != null ? tsOf('learner', e.learner_frame) : learnerTimeFor(errRefTime(e)));
  const curTime = () => (hasVideo ? vid.reference.currentTime : virtualTime);

  // ------------------------------------------------------------------ drawing
  function highlights(refTime) {
    const out = {};
    const rank = { low: 1, medium: 2, high: 3 };
    errors.forEach((e) => {
      if (Math.abs(errRefTime(e) - refTime) > HIGHLIGHT_WINDOW) return;
      const key = String(e.joint || '').toLowerCase().replace(/\s+/g, '_');
      (JOINTS[key] || []).forEach((k) => {
        if (!out[k] || rank[e.severity] > rank[out[k]]) out[k] = e.severity;
      });
    });
    return out;
  }

  function drawSide(side, hl) {
    const canvas = cv[side], video = vid[side];
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!lm || !lm[side]) return;

    const pts = lm[side].points[idxAt(side, video.currentTime)];
    if (!pts) return;
    const vw = video.videoWidth || 4, vh = video.videoHeight || 3;
    const scale = Math.min(w / vw, h / vh), dw = vw * scale, dh = vh * scale;
    const ox = (w - dw) / 2, oy = (h - dh) / 2;
    const P = (k) => [ox + pts[k][0] * dw, oy + pts[k][1] * dh];
    const seen = (k) => pts[k] && pts[k][2] >= 0.3;

    ctx.lineCap = 'round';
    ctx.lineWidth = 3.5;
    BONES.forEach(([a, b]) => {
      if (!seen(a) || !seen(b)) return;
      const both = hl[a] && hl[b];
      ctx.strokeStyle = both ? SEV[hl[a]] : ACCENT[side];
      ctx.globalAlpha = both ? 0.95 : 0.8;
      const [x1, y1] = P(a), [x2, y2] = P(b);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    });
    ctx.globalAlpha = 1;
    DOTS.forEach((k) => {
      if (!seen(k)) return;
      const [x, y] = P(k);
      const sev = hl[k];
      if (sev) {
        ctx.strokeStyle = SEV[sev]; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.arc(x, y, sev === 'high' ? 13 : 11, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.fillStyle = sev ? SEV[sev] : OK;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
    });
  }

  function draw() {
    if (!hasVideo || annotMode) return;
    const hl = highlights(curTime());
    drawSide('reference', hl);
    drawSide('learner', hl);
  }

  // ----------------------------------------------------------------------- UI
  const scrub = $('scrub');
  const btnPlay = $('btn-play'), btnPrev = $('btn-prev'), btnNext = $('btn-next');
  const ICON_PLAY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4l14 8-14 8z" fill="currentColor"/></svg>';
  const ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/></svg>';

  function updateUI() {
    const t = curTime();
    scrub.max = String(duration || 1);
    scrub.value = String(t);
    $('time-now').textContent = mmss(t);
    $('time-total').textContent = mmss(duration);
    $('t-reference').textContent = mmss(t);
    $('t-learner').textContent = mmss(hasVideo ? vid.learner.currentTime : learnerTimeFor(t));
    btnPrev.disabled = !errors.some((e) => errRefTime(e) < t - 0.15);
    btnNext.disabled = !errors.some((e) => errRefTime(e) > t + 0.15);
  }

  function buildTicks() {
    const box = $('ticks');
    box.innerHTML = '';
    if (!duration) return;
    errors.forEach((e, i) => {
      const b = document.createElement('button');
      b.className = `tick ${e.severity}` + (i === selected ? ' active' : '');
      b.style.left = `${clamp(errRefTime(e) / duration, 0, 1) * 100}%`;
      b.title = `${label(e.joint)} · ${mmss(e.timestamp)}`;
      b.setAttribute('aria-label', b.title);
      b.addEventListener('click', () => select(i));
      box.appendChild(b);
    });
  }

  // ---------------------------------------------------------------- seeking
  function seekPair(refT, lrnT) {
    refT = clamp(refT, 0, duration || refT);
    virtualTime = refT;
    if (hasVideo) {
      const ready = vid.reference.readyState >= 1 && vid.learner.readyState >= 1;
      if (ready) { vid.reference.currentTime = refT; vid.learner.currentTime = lrnT; }
      else pending = { ref: refT, lrn: lrnT };
    }
    updateUI(); draw();
  }
  const seekTo = (t) => seekPair(t, learnerTimeFor(t));

  function annotatedTimeFor(e) {
    const k = align.findIndex((p) => p[0] >= e.reference_frame);
    return (k < 0 ? 0 : k) / (data.video_fps || fps);
  }

  function select(i) {
    if (i < 0 || i >= errors.length) return;
    selected = i;
    const e = errors[i];
    const unit = e.unit || '°';
    const fmt = (v) => (v == null ? '—' : `${Number(v) % 1 ? Number(v).toFixed(1) : Number(v)}${unit}`);

    $('fix-joint').textContent = label(e.joint);
    const sev = $('fix-sev');
    sev.hidden = false; sev.className = `badge ${e.severity}`; sev.textContent = e.severity;
    $('fix-meta').textContent = `At ${mmss(e.timestamp)} · reference frame ${e.reference_frame ?? '–'} ↔ your frame ${e.learner_frame ?? '–'}`;
    $('fix-body').hidden = false;
    $('fix-ref').textContent = fmt(e.reference_value);
    $('fix-lrn').textContent = fmt(e.learner_value);
    $('fix-dev').textContent = fmt(e.deviation);
    $('fix-sugg').textContent = e.suggestion || e.description || 'No suggestion provided.';

    document.querySelectorAll('#mini-list .err-item').forEach((el) => el.classList.toggle('active', Number(el.dataset.index) === i));
    document.querySelectorAll('.tick').forEach((el, k) => el.classList.toggle('active', k === i));
    const active = document.querySelector(`#mini-list .err-item[data-index="${i}"]`);
    if (active) active.scrollIntoView({ block: 'nearest' });

    if (annotMode && vidAnnot) vidAnnot.currentTime = annotatedTimeFor(e);
    else { pausePlayback(); seekPair(errRefTime(e), errLrnTime(e)); }
  }

  function step(dir) {
    const t = curTime();
    const list = errors.map((e, i) => [errRefTime(e), i]);
    const pick = dir > 0 ? list.find(([rt]) => rt > t + 0.15) : [...list].reverse().find(([rt]) => rt < t - 0.15);
    if (pick) select(pick[1]);
  }

  // --------------------------------------------------------------- playback
  function applyRates(t) {
    if (!hasVideo) return;
    vid.reference.playbackRate = speed;
    const want = slopeAt(t) * speed;
    if (Math.abs(vid.learner.playbackRate - want) > 0.02) vid.learner.playbackRate = clamp(want, 0.0625, 16);
  }

  function loop() {
    if (!playing) return;
    const t = vid.reference.currentTime;
    const target = learnerTimeFor(t);
    if (Math.abs(vid.learner.currentTime - target) > 0.3) vid.learner.currentTime = target;
    applyRates(t);
    const lEnd = isFinite(vid.learner.duration) ? vid.learner.duration : Infinity;
    if (target >= lEnd - 0.05) { if (!vid.learner.paused) vid.learner.pause(); }
    else if (vid.learner.paused) vid.learner.play().catch(() => {});
    updateUI(); draw();
    requestAnimationFrame(loop);
  }

  function startPlayback() {
    if (!hasVideo || annotMode) return;
    if (vid.reference.ended || curTime() >= duration - 0.05) seekTo(0);
    playing = true;
    btnPlay.innerHTML = ICON_PAUSE; btnPlay.setAttribute('aria-label', 'Pause');
    applyRates(curTime());
    Promise.all([vid.reference.play(), vid.learner.play()]).catch(() => pausePlayback());
    requestAnimationFrame(loop);
  }
  function pausePlayback() {
    playing = false;
    btnPlay.innerHTML = ICON_PLAY; btnPlay.setAttribute('aria-label', 'Play');
    if (hasVideo) { vid.reference.pause(); vid.learner.pause(); }
    updateUI(); draw();
  }
  const togglePlay = () => (playing ? pausePlayback() : startPlayback());

  // ----------------------------------------------------------------- wiring
  btnPlay.addEventListener('click', togglePlay);
  btnPrev.addEventListener('click', () => step(-1));
  btnNext.addEventListener('click', () => step(1));
  scrub.addEventListener('input', () => seekTo(parseFloat(scrub.value)));
  $('speed').addEventListener('change', (e) => { speed = parseFloat(e.target.value); applyRates(curTime()); });
  document.querySelectorAll('#mini-list .err-item').forEach((el) => el.addEventListener('click', () => select(Number(el.dataset.index))));

  if (hasVideo) {
    btnPlay.disabled = false;
    const onMeta = () => {
      if (isFinite(vid.reference.duration)) { duration = vid.reference.duration; buildTicks(); }
      if (pending && vid.reference.readyState >= 1 && vid.learner.readyState >= 1) {
        vid.reference.currentTime = pending.ref; vid.learner.currentTime = pending.lrn; pending = null;
      }
      updateUI(); draw();
    };
    vid.reference.addEventListener('loadedmetadata', onMeta);
    vid.learner.addEventListener('loadedmetadata', onMeta);
    ['seeked', 'loadeddata'].forEach((ev) => { vid.reference.addEventListener(ev, () => { updateUI(); draw(); }); vid.learner.addEventListener(ev, draw); });
    vid.reference.addEventListener('ended', pausePlayback);
    if (window.ResizeObserver) document.querySelectorAll('.cmp-frame').forEach((f) => new ResizeObserver(draw).observe(f));
    else window.addEventListener('resize', draw);
  } else {
    btnPlay.disabled = true; btnPlay.title = 'No videos attached';
  }

  // live overlay / annotated video switch
  const modeLive = $('mode-live'), modeAnnot = $('mode-annot');
  function setMode(annot) {
    annotMode = annot && !!vidAnnot;
    if (annotMode) pausePlayback();
    $('stage-live').hidden = annotMode; $('stage-annot').hidden = !annotMode; $('controls').hidden = annotMode;
    modeLive.setAttribute('aria-pressed', String(!annotMode));
    modeAnnot.setAttribute('aria-pressed', String(annotMode));
    if (annotMode && selected >= 0) vidAnnot.currentTime = annotatedTimeFor(errors[selected]);
    if (!annotMode && vidAnnot) vidAnnot.pause();
    draw();
  }
  modeLive.addEventListener('click', () => setMode(false));
  modeAnnot.addEventListener('click', () => setMode(true));
  // no source videos but an annotated one exists -> show it straight away
  const noLive = !hasVideo && !!vidAnnot;

  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === ' ' && tag !== 'BUTTON') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowLeft') { seekTo(curTime() - 0.1); }
    else if (e.key === 'ArrowRight') { seekTo(curTime() + 0.1); }
    else if (e.key === 'n' || e.key === 'N') step(1);
    else if (e.key === 'p' || e.key === 'P') step(-1);
  });

  // -------------------------------------------------------------------- init
  async function init() {
    if (data.urls && data.urls.landmarks) {
      try {
        const res = await fetch(data.urls.landmarks, { cache: 'no-store' });
        if (res.ok) lm = await res.json();
      } catch (_) { /* overlays simply stay off */ }
    }
    buildMap();
    if (lm && !duration) duration = Math.max(...stamps('reference'));
    buildTicks(); updateUI();

    const params = new URLSearchParams(window.location.search);
    const wanted = params.get('error');
    if (wanted !== null && errors[Number(wanted)]) select(Number(wanted));
    else if (params.get('t') !== null) seekTo(parseFloat(params.get('t')) || 0);
    if (noLive) setMode(true);
    draw();
  }
  init();
})();
