/* Processing page: polls real job status from Flask (/api/status/<id>). No fake timers. */
(() => {
  const { job_id: jobId } = JSON.parse(document.getElementById('page-data').textContent);
  const list = document.getElementById('stage-list');
  const items = Object.fromEntries([...list.children].map((li) => [li.dataset.key, li]));
  const bar = document.getElementById('proc-bar');
  const msg = document.getElementById('proc-msg');
  const title = document.getElementById('proc-title');
  const elapsedEl = document.getElementById('elapsed');
  const errBox = document.getElementById('proc-error');
  const errText = document.getElementById('proc-error-text');
  const errTitle = document.getElementById('proc-error-title');

  const LABEL = { done: 'Done', active: 'Working', pending: 'Waiting', error: 'Failed' };
  const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
  const CROSS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>';

  const started = Date.now();
  let timer = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    elapsedEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000);

  function render(st) {
    st.stages.forEach((s, i) => {
      const li = items[s.key];
      if (!li) return;
      li.dataset.state = s.state;
      li.querySelector('[data-role="state"]').textContent = LABEL[s.state];
      const ic = li.querySelector('[data-role="ic"]');
      if (s.state === 'done') ic.innerHTML = CHECK;
      else if (s.state === 'error') ic.innerHTML = CROSS;
      else if (s.state === 'active') ic.innerHTML = '<span class="spinner"></span>';
      else ic.textContent = String(i + 1);
    });
    const done = st.stages.filter((s) => s.state === 'done').length;
    const pct = Math.round((done / st.stage_count) * 100);
    bar.firstElementChild.style.width = pct + '%';
    bar.setAttribute('aria-valuenow', String(pct));
    if (st.message) msg.textContent = st.message;
  }

  function fail(st) {
    clearInterval(timer);
    title.textContent = 'Analysis stopped';
    errTitle.textContent = st.error_kind === 'unavailable'
      ? 'The analysis modules aren’t connected yet'
      : st.error_kind === 'analysis' ? 'We couldn’t analyse these videos' : 'Something went wrong';
    errText.textContent = st.error || 'Unknown error.';
    errBox.hidden = false;
    msg.textContent = '';
  }

  let failures = 0;
  async function poll() {
    try {
      const res = await fetch(`/api/status/${jobId}`, { cache: 'no-store' });
      if (res.status === 404) return fail({ error: 'This analysis no longer exists.', error_kind: 'internal' });
      const st = await res.json();
      failures = 0;
      render(st);
      if (st.status === 'done') {
        clearInterval(timer);
        title.textContent = 'Analysis complete';
        msg.textContent = 'Opening your results…';
        return void (window.location.href = st.redirect);
      }
      if (st.status === 'error') return fail(st);
    } catch (_) {
      failures += 1;
      msg.textContent = 'Connection lost. Retrying…';
    }
    setTimeout(poll, Math.min(800 * (1 + failures), 5000));
  }
  poll();
})();
