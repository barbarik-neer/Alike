/* Upload page: two slots, client-side validation, upload with progress. */
(() => {
  const limits = JSON.parse(document.getElementById('page-data').textContent);
  const slots = {};
  const analyseBtn = document.getElementById('analyse-btn');
  const globalMsg = document.getElementById('global-msg');
  const readyTitle = document.getElementById('ready-title');
  const readySub = document.getElementById('ready-sub');
  const progress = document.getElementById('upload-progress');

  const ICONS = {
    err: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>',
    warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 6L9 17l-5-5"/></svg>',
  };

  const fmtSize = (b) => b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';
  const fmtDur = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  document.querySelectorAll('.slot').forEach((el) => {
    const q = (r) => el.querySelector(`[data-role="${r}"]`);
    const slot = {
      el, name: el.dataset.slot, file: null, valid: false, url: null,
      dropzone: q('dropzone'), input: q('input'), preview: q('preview'), video: q('video'),
      meta: q('meta'), nameEl: q('name'), details: q('details'), msg: q('msg'), badge: q('badge'),
    };
    slots[slot.name] = slot;

    q('browse').addEventListener('click', () => slot.input.click());
    q('replace').addEventListener('click', () => slot.input.click());
    q('remove').addEventListener('click', () => clearSlot(slot));
    slot.input.addEventListener('change', () => { if (slot.input.files[0]) loadFile(slot, slot.input.files[0]); });

    ['dragenter', 'dragover'].forEach((ev) => el.addEventListener(ev, (e) => { e.preventDefault(); slot.dropzone.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => el.addEventListener(ev, (e) => { e.preventDefault(); slot.dropzone.classList.remove('over'); }));
    el.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) loadFile(slot, f); });
  });

  function say(slot, kind, text) {
    if (!text) { slot.msg.hidden = true; slot.msg.textContent = ''; return; }
    slot.msg.hidden = false;
    slot.msg.className = 'slot-msg ' + kind;
    slot.msg.innerHTML = ICONS[kind] + '<span></span>';
    slot.msg.lastChild.textContent = text;
  }

  function clearSlot(slot, keepMsg) {
    if (slot.url) URL.revokeObjectURL(slot.url);
    slot.url = null; slot.file = null; slot.valid = false; slot.input.value = '';
    slot.video.removeAttribute('src'); slot.video.load();
    slot.preview.hidden = true; slot.meta.hidden = true; slot.badge.hidden = true;
    slot.dropzone.hidden = false;
    if (!keepMsg) say(slot, '', '');
    refresh();
  }

  function loadFile(slot, file) {
    clearSlot(slot, true);
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!limits.extensions.includes(ext)) {
      return say(slot, 'err', `.${ext} isn't supported. Use ${limits.extensions.join(', ').toUpperCase()}.`);
    }
    if (file.size > limits.max_mb * 1048576) {
      return say(slot, 'err', `That file is ${fmtSize(file.size)}. The limit is ${limits.max_mb} MB.`);
    }
    if (file.size === 0) return say(slot, 'err', 'That file is empty.');

    say(slot, 'ok', 'Checking video…');
    const url = URL.createObjectURL(file);
    const probe = document.createElement('video');
    probe.preload = 'metadata'; probe.muted = true;

    probe.onloadedmetadata = () => {
      const d = probe.duration;
      if (!isFinite(d) || d <= 0) {
        // Some containers don't report duration in the browser; the server re-checks.
        return accept(slot, file, url, null);
      }
      if (d < limits.min_duration) {
        URL.revokeObjectURL(url);
        return say(slot, 'err', `This video is only ${d.toFixed(1)}s long. Use at least ${limits.min_duration} seconds.`);
      }
      if (d > limits.max_duration) {
        URL.revokeObjectURL(url);
        return say(slot, 'err', `This video is ${Math.round(d)}s long. The limit is ${limits.max_duration} seconds.`);
      }
      accept(slot, file, url, d);
    };
    probe.onerror = () => {
      URL.revokeObjectURL(url);
      say(slot, 'err', "Your browser can't read this video. Try exporting it as MP4 (H.264).");
    };
    probe.src = url;
  }

  function accept(slot, file, url, duration) {
    slot.file = file; slot.valid = true; slot.url = url;
    slot.video.src = url;
    slot.dropzone.hidden = true; slot.preview.hidden = false; slot.meta.hidden = false; slot.badge.hidden = false;
    slot.nameEl.textContent = file.name;
    slot.details.textContent = `${fmtSize(file.size)} · ${duration ? fmtDur(duration) : 'duration unknown'}`;
    const [lo, hi] = limits.recommended;
    if (duration && (duration < lo || duration > hi)) {
      say(slot, 'warn', `${lo}–${hi} seconds gives the best results. This video will still be analysed.`);
    } else {
      say(slot, '', '');
    }
    refresh();
  }

  function refresh() {
    const both = slots.reference.valid && slots.learner.valid;
    analyseBtn.disabled = !both;
    if (both) {
      readyTitle.textContent = 'Both videos are ready';
      readySub.textContent = 'Start the analysis. This usually takes a minute or two.';
    } else {
      const missing = ['reference', 'learner'].filter((k) => !slots[k].valid)
        .map((k) => (k === 'reference' ? 'the reference tutorial' : 'your performance'));
      readyTitle.textContent = 'Add both videos to continue';
      readySub.textContent = `Still needed: ${missing.join(' and ')}.`;
    }
  }

  function showGlobal(text) {
    globalMsg.hidden = !text;
    if (text) globalMsg.querySelector('span').textContent = text;
  }

  analyseBtn.addEventListener('click', () => {
    if (!(slots.reference.valid && slots.learner.valid)) return;
    showGlobal('');
    const form = new FormData();
    form.append('reference', slots.reference.file);
    form.append('learner', slots.learner.file);

    analyseBtn.disabled = true;
    const label = analyseBtn.innerHTML;
    analyseBtn.textContent = 'Uploading…';
    progress.hidden = false;
    const bar = progress.firstElementChild;
    bar.style.width = '0%';

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = Math.round((e.loaded / e.total) * 100) + '%'; };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) { /* non-JSON error page */ }
      if (xhr.status === 202 && body.redirect) { window.location.href = body.redirect; return; }
      fail(body.error || `Upload failed (${xhr.status}).`, body.field);
    };
    xhr.onerror = () => fail("Couldn't reach the server. Check your connection and try again.");

    function fail(text, field) {
      progress.hidden = true;
      analyseBtn.innerHTML = label;
      if (field && slots[field]) { clearSlot(slots[field], true); say(slots[field], 'err', text); }
      else showGlobal(text);
      refresh();
    }
    xhr.send(form);
  });

  refresh();
})();
