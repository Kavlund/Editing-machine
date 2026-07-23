// ── State ────────────────────────────────────────────────────────────────

const state = {
  clients: [],
  files: [],        // [{file, path}]
  folderName: '',
  clientId: '',
  editClientId: null,
  onboarding: {},   // rich fields extracted from the onboarding doc (words, inspiration URLs, etc.)
};

// ── DOM ──────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

const els = {
  dropZone:         $('drop-zone'),
  fileBrowse:       $('file-browse'),
  fileBrowseFolder: $('file-browse-folder'),
  filePreview:      $('file-preview'),
  previewFolder:    $('preview-folder-name'),
  previewCount:     $('preview-file-count'),
  previewSize:      $('preview-file-size'),
  fileList:         $('file-list'),
  clearBtn:         $('clear-files-btn'),
  progressWrap:     $('progress-wrap'),
  progressBar:      $('progress-bar'),
  progressLabel:    $('progress-label'),
  clientSelect:       $('client-select'),
  newClientQuick:     $('new-client-quick-btn'),
  workspaceArea:      $('workspace-area'),
  noClientPrompt:     $('no-client-prompt'),
  workspaceClientHdr: $('workspace-client-header'),
  wchDot:             $('wch-dot'),
  wchName:            $('wch-name'),
  wchEditBtn:         $('wch-edit-btn'),
  jobsSectionTitle:   $('jobs-section-title'),
  jobNotes:           $('job-notes'),
  submitBtn:          $('submit-btn'),
  jobsGrid:           $('jobs-grid'),
  refreshJobsBtn:     $('refresh-jobs-btn'),
  openClientsBtn:     $('open-clients-btn'),
  drawerOverlay:    $('drawer-overlay'),
  drawer:           $('clients-drawer'),
  closeDrawerBtn:   $('close-drawer-btn'),
  clientsList:      $('clients-list'),
  addClientDrawer:  $('add-client-drawer-btn'),
  modalOverlay:     $('modal-overlay'),
  modalTitle:       $('modal-title'),
  closeModalBtn:    $('close-modal-btn'),
  cancelModalBtn:   $('cancel-modal-btn'),
  clientForm:       $('client-form'),
  fName:            $('f-name'),
  fNiche:           $('f-niche'),
  fPrimary:         $('f-primary'),
  fPrimaryHex:      $('f-primary-hex'),
  fAccent:          $('f-accent'),
  fAccentHex:       $('f-accent-hex'),
  fCaptionColor:    $('f-caption-color'),
  fCaptionColorHex: $('f-caption-color-hex'),
  fTonePills:       $('f-tone-pills'),
  fIcp:             $('f-icp'),
  fCta:             $('f-cta'),
  fSpecific:        $('f-specific'),
  fLanguage:        $('f-language'),
  fSpeakers:        $('f-speakers'),
  fGrade:           $('f-grade'),
  fCapSize:         $('f-cap-size'),
  fCapY:            $('f-cap-y'),
  fTitleHand:       $('f-title-hand'),
  fTitleLine1:      $('f-title-line1'),
  fTitleLine2:      $('f-title-line2'),
  fTitleDur:        $('f-title-dur'),
  toastContainer:   $('toast-container'),
  brollSection:     $('broll-section'),
  brollDropZone:    $('broll-drop-zone'),
  brollFileInput:   $('broll-file-input'),
  brollList:        $('broll-list'),
  styleSection:     $('style-section'),
  styleDropZone:    $('style-drop-zone'),
  styleFileInput:   $('style-file-input'),
  styleList:        $('style-list'),
  styleProfile:     $('style-profile'),
};

// ── API ──────────────────────────────────────────────────────────────────

const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async post(path, data) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async put(path, data) {
    const res = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async del(path) {
    const res = await fetch(path, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};

// ── Confirm dialog ─────────────────────────────────────────────────────────
// Deliberately NOT the browser's confirm(): the browser offers "prevent this
// page from creating additional dialogs", and once that's ticked confirm()
// silently returns false forever — every delete then quietly does nothing.
// This one is ours, so it can never be suppressed.
function confirmDialog(message, confirmLabel = 'Delete') {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-box" role="dialog" aria-modal="true">
        <p class="confirm-msg"></p>
        <div class="confirm-actions">
          <button class="confirm-cancel" data-a="no">Cancel</button>
          <button class="confirm-danger" data-a="yes"></button>
        </div>
      </div>`;
    overlay.querySelector('.confirm-msg').textContent = message;
    overlay.querySelector('.confirm-danger').textContent = confirmLabel;

    const done = (v) => {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(false);
      else if (e.key === 'Enter') done(true);
    };
    overlay.addEventListener('click', e => {
      if (e.target === overlay) return done(false);
      const b = e.target.closest('[data-a]');
      if (b) done(b.dataset.a === 'yes');
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    setTimeout(() => overlay.querySelector('.confirm-danger').focus(), 20);
  });
}

// ── Utilities ────────────────────────────────────────────────────────────

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

function timeAgo(iso) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function isVideo(path) {
  return /\.(mov|mp4|avi|mkv|mxf|m4v|webm|mts|m2ts)$/i.test(path);
}

function filterFiles(files) {
  return files.filter(({ path }) => {
    const name = path.split('/').pop();
    return !name.startsWith('.') && name !== 'Thumbs.db' && name !== 'desktop.ini';
  });
}

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  els.toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Directory reading ────────────────────────────────────────────────────

async function readAllEntries(reader) {
  const all = [];
  const readBatch = () => new Promise((resolve, reject) =>
    reader.readEntries(entries => {
      if (!entries.length) return resolve();
      all.push(...entries);
      readBatch().then(resolve).catch(reject);
    }, reject)
  );
  await readBatch();
  return all;
}

async function traverseEntry(entry, base = '') {
  if (entry.isFile) {
    return new Promise((resolve, reject) =>
      entry.file(f => resolve([{ file: f, path: base + entry.name }]), reject)
    );
  }
  if (entry.isDirectory) {
    const entries = await readAllEntries(entry.createReader());
    const nested = await Promise.all(
      entries.map(e => traverseEntry(e, base + entry.name + '/'))
    );
    return nested.flat();
  }
  return [];
}

// ── File handling ────────────────────────────────────────────────────────

async function processDroppedItems(items) {
  const all = [];
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) {
      const files = await traverseEntry(entry);
      all.push(...files);
      if (entry.isDirectory && !state.folderName) {
        state.folderName = entry.name;
      }
    }
  }
  applyFiles(all);
}

function processInputFiles(fileList) {
  const files = Array.from(fileList).map(f => ({
    file: f,
    path: f.webkitRelativePath || f.name,
  }));
  if (files.length) {
    state.folderName = files[0].path.split('/')[0] || files[0].file.name;
  }
  applyFiles(files);
}

function applyFiles(raw) {
  state.files = filterFiles(raw);
  renderFilePreview();
  checkSubmitReady();
}

function renderFilePreview() {
  const files = state.files;
  if (!files.length) {
    els.filePreview.hidden = true;
    els.dropZone.classList.remove('has-files');
    return;
  }

  const videos = files.filter(f => isVideo(f.path));
  const totalBytes = files.reduce((sum, f) => sum + (f.file.size || 0), 0);

  els.previewFolder.textContent = state.folderName;
  els.previewCount.textContent = `${files.length} file${files.length !== 1 ? 's' : ''}${videos.length ? ` · ${videos.length} video${videos.length !== 1 ? 's' : ''}` : ''}`;
  els.previewSize.textContent = formatBytes(totalBytes);

  const shown = files.slice(0, 6);
  const more = files.length - shown.length;

  els.fileList.innerHTML = shown.map(({ file, path }) => `
    <div class="file-item">
      <span class="file-item-name">${path}</span>
      <span class="file-item-size">${formatBytes(file.size || 0)}</span>
    </div>
  `).join('') + (more > 0 ? `<div class="file-more">…and ${more} more</div>` : '');

  els.filePreview.hidden = false;
  els.dropZone.classList.add('has-files');
}

function clearFiles() {
  state.files = [];
  state.folderName = '';
  els.fileBrowse.value = '';
  renderFilePreview();
  checkSubmitReady();
}

// ── Submit readiness ─────────────────────────────────────────────────────

function checkSubmitReady() {
  els.submitBtn.disabled = !(state.files.length && state.clientId);
}

// ── Upload ───────────────────────────────────────────────────────────────

// Big uploads can die at the network edge before the server ever sees them, so
// the server cannot be the one to complain. Check here, before a byte is sent.
const UPLOAD_HEADROOM_BYTES = 600 * 1024 * 1024;   // room for the render to work
const SINGLE_UPLOAD_WARN    = 2 * 1024 * 1024 * 1024;  // only mention Drive for genuinely huge files

// Only ONE thing actually makes an upload impossible: no disk space. That's a hard
// stop. File size is just advice — a normal 1–2 GB video must always be allowed
// through, so a big file asks rather than blocks.
async function preflightUpload(totalBytes) {
  const gb = b => (b / 1e9).toFixed(2);
  let storage = null;
  try { storage = await api.get('/api/admin/storage'); } catch {}

  if (storage && typeof storage.free_gb === 'number') {
    const free = storage.free_gb * 1e9;
    if (free < totalBytes + UPLOAD_HEADROOM_BYTES) {
      return { block: true,
        message: `Not enough space. This upload is ${gb(totalBytes)} GB and only ${storage.free_gb.toFixed(2)} GB is free `
               + `(a render needs about 0.6 GB of working room on top). `
               + `Delete some old jobs to free space, then try again.` };
    }
  }
  if (totalBytes > SINGLE_UPLOAD_WARN) {
    return { block: false,
      message: `This upload is ${gb(totalBytes)} GB. Very large uploads sometimes drop part-way and restart from zero. `
             + `If that happens, put the file in the client's Drive "Source" folder and use "Pull from Drive" instead. `
             + `Upload it now anyway?` };
  }
  return null;   // good to go
}

async function handleSubmit() {
  if (!state.files.length || !state.clientId) return;

  const totalBytes = state.files.reduce((n, f) => n + (f.file?.size || 0), 0);
  const problem = await preflightUpload(totalBytes);
  if (problem) {
    if (problem.block) {                       // genuinely can't work — stop
      await confirmDialog(problem.message, 'OK');
      return;
    }
    const go = await confirmDialog(problem.message, 'Upload anyway');
    if (!go) return;                           // their choice; default is to proceed
  }

  els.submitBtn.disabled = true;
  els.submitBtn.textContent = 'Uploading...';
  els.progressWrap.hidden = false;
  setProgress(0);

  const formData = new FormData();
  formData.append('client_id', state.clientId);
  formData.append('folder_name', state.folderName);
  formData.append('notes', els.jobNotes.value.trim());

  for (const { file, path } of state.files) {
    formData.append('files', file, path);
  }

  try {
    const job = await uploadWithProgress(formData);
    setProgress(100);
    toast(`Job created for ${job.client_name}`, 'success');
    setTimeout(() => {
      clearFiles();
      els.jobNotes.value = '';
      els.progressWrap.hidden = true;
      setProgress(0);
      els.submitBtn.textContent = 'Start Processing';
      checkSubmitReady();
      loadJobs();
    }, 600);
  } catch (err) {
    toast('Upload failed: ' + err.message, 'error');
    els.submitBtn.disabled = false;
    els.submitBtn.textContent = 'Start Processing';
    els.progressWrap.hidden = true;
    setProgress(0);
  }
}

function setProgress(pct) {
  els.progressBar.style.transform = `scaleX(${pct / 100})`;
  els.progressLabel.textContent = pct < 100 ? `Uploading… ${pct}%` : 'Done';
}

// ── Pull source footage straight from the client's Drive Source folder ──────
(function () {
  const btn = $('drive-pull-btn'), panel = $('drive-picker');
  const list = $('drive-picker-list'), nameInput = $('drive-job-name'), createBtn = $('drive-create-btn');
  const scriptInput = $('drive-script');
  if (!btn) return;
  const note = (t) => `<p class="empty-state" style="font-size:.8rem">${t}</p>`;
  const selected = () => [...list.querySelectorAll('input:checked')].map(c =>
    ({ id: c.dataset.id, name: c.dataset.name, size: Number(c.dataset.size) }));
  function refreshCreate() {
    const s = selected();
    createBtn.disabled = !(s.length && state.clientId);
    if (s.length && !nameInput.value) nameInput.value = s[0].name.replace(/\.[^.]+$/, '');
  }
  btn.addEventListener('click', async () => {
    if (!state.clientId) { toast('Pick a client first', 'error'); return; }
    panel.hidden = !panel.hidden;
    if (panel.hidden) return;
    list.innerHTML = note('Loading the Drive folder…');
    try {
      const d = await (await fetch(`/api/clients/${state.clientId}/drive-source`, { cache: 'no-store' })).json();
      if (!d.available) { list.innerHTML = note('Google Drive is not connected.'); return; }
      if (!d.clips.length) { list.innerHTML = note('No clips in this creator\'s Drive Source folder yet.'); return; }
      list.innerHTML = d.clips.map(c =>
        `<label style="display:flex;align-items:center;gap:8px;font-size:.85rem;cursor:pointer;">
           <input type="checkbox" data-id="${c.id}" data-name="${escapeHtml(c.name)}" data-size="${c.size}">
           <span style="flex:1;">${escapeHtml(c.name)}</span>
           <span style="color:var(--text-dim);">${formatBytes(c.size)}</span>
         </label>`).join('');
      list.querySelectorAll('input').forEach(c => c.addEventListener('change', refreshCreate));
    } catch (e) { list.innerHTML = note('Could not load the Drive folder.'); }
  });
  createBtn.addEventListener('click', async () => {
    // Never bail silently — always say why.
    const clips = selected();
    if (!clips.length) { toast('Tick at least one clip first', 'error'); return; }
    if (!state.clientId) { toast('Pick a client first', 'error'); return; }
    createBtn.disabled = true; createBtn.textContent = 'Creating…';
    try {
      const res = await fetch('/api/jobs/from-drive', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: state.clientId,
          folder_name: nameInput.value.trim() || clips[0].name,
          notes: els.jobNotes.value.trim(), clips,
        }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `server returned ${res.status}`);
      }
      const job = await res.json();
      // One press: pull from Drive AND start editing straight away — with the
      // script attached, so the same script-grounded clean cut applies here
      // exactly like it does for a normal computer upload.
      createBtn.textContent = 'Starting…';
      const script = scriptInput ? scriptInput.value.trim() : '';
      await api.post(`/api/jobs/${job.id}/run`, { instructions: '', broll_count: 'ai', script });
      toast(`Editing started for ${job.client_name}`, 'success');
      panel.hidden = true; nameInput.value = ''; els.jobNotes.value = '';
      if (scriptInput) scriptInput.value = '';
      loadJobs();
    } catch (e) { toast('Could not start: ' + (e.message || e), 'error'); }
    createBtn.disabled = false; createBtn.textContent = 'Create job and start editing';
  });
})();

// An upload is an XHR owned by THIS page. Navigating away (e.g. to the Control
// Center) unloads the page and silently kills the transfer, so the whole upload
// is lost with no error. Track it and refuse to leave quietly.
let uploadInFlight = 0;

function uploadWithProgress(formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    uploadInFlight++;
    const done = () => { uploadInFlight = Math.max(0, uploadInFlight - 1); };
    xhr.addEventListener('loadend', done);
    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 95));
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        // Surface the server's actual explanation (e.g. "not enough space,
        // delete old jobs") instead of a bare status code.
        let detail = '';
        try { detail = (JSON.parse(xhr.responseText) || {}).detail || ''; } catch {}
        reject(new Error(detail || `${xhr.status} ${xhr.statusText}`));
      }
    });
    xhr.addEventListener('error', () => reject(new Error('Network error')));
    xhr.open('POST', '/api/upload');
    xhr.send(formData);
  });
}

// ── Clients ──────────────────────────────────────────────────────────────

async function loadClients() {
  state.clients = await api.get('/api/clients');
  renderClientSelect();
  renderClientsDrawer();
  updateWorkspace();
}

function renderClientSelect() {
  const saved = els.clientSelect.value;
  els.clientSelect.innerHTML = '<option value="">Choose a client to get started...</option>' +
    state.clients.map(c =>
      `<option value="${c.id}"${c.id === saved ? ' selected' : ''}>${c.name}</option>`
    ).join('');
  if (saved && state.clients.find(c => c.id === saved)) {
    state.clientId = saved;
  }
}

function renderClientsDrawer() {
  if (!state.clients.length) {
    els.clientsList.innerHTML = '<p class="empty-state">No clients yet.</p>';
    return;
  }
  els.clientsList.innerHTML = state.clients.map(c => `
    <div class="client-item" data-id="${c.id}">
      <span class="client-color-dot" style="background:${c.brand?.accent_color || '#6366f1'}"></span>
      <span class="client-item-name">${c.name}</span>
      <div class="client-item-actions">
        <button class="btn-icon" onclick="openModal('${c.id}')" title="Edit">
          <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
        </button>
        <button class="btn-icon" onclick="deleteClient('${c.id}', '${c.name.replace(/'/g, "\\'")}')" title="Delete">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        </button>
      </div>
    </div>
  `).join('');
}

async function deleteClient(id, name) {
  if (!await confirmDialog(`Delete client "${name}"? This cannot be undone.`, 'Delete client')) return;
  try {
    await api.del(`/api/clients/${id}`);
    if (state.clientId === id) {
      state.clientId = '';
      checkSubmitReady();
    }
    await loadClients();
    toast(`Deleted ${name}`);
  } catch (err) {
    toast('Delete failed: ' + err.message, 'error');
  }
}

// ── Client Modal ─────────────────────────────────────────────────────────

function openModal(clientId = null) {
  state.editClientId = clientId;
  els.modalTitle.textContent = clientId ? 'Edit Client' : 'New Client';
  loadBroll(clientId);
  loadStyleSection(clientId);

  if (clientId) {
    const c = state.clients.find(x => x.id === clientId);
    if (c) fillModalForm(c);
  } else {
    els.clientForm.reset();
    state.onboarding = {};   // fresh client — no carried-over onboarding data
    resetBriefZone();
    syncColorHex(els.fPrimary, els.fPrimaryHex);
    syncColorHex(els.fAccent, els.fAccentHex);
    els.fCaptionColor.value = '#ffffff';
    els.fCaptionColorHex.value = '#ffffff';
    els.fGrade.value = 'colorlevels=rimax=0.92:gimax=0.92:bimax=0.88,eq=saturation=1.0:contrast=1.02,unsharp=5:5:0.3:5:5:0.0';
    els.fCapSize.value = 60;
    els.fCapY.value = 1300;
    els.fTitleHand.value = '';
    els.fTitleLine1.value = '';
    els.fTitleLine2.value = '';
    els.fTitleDur.value = 4.5;
    setTonePills([]);
  }

  els.modalOverlay.hidden = false;
  els.fName.focus();
}

// ── Brand brief analysis ──────────────────────────────────────────────────

async function analyzeBrief(file) {
  const zone  = $('brief-upload-zone');
  const inner = $('brief-upload-inner');

  zone.classList.add('brief-loading');
  inner.innerHTML = `<span class="brief-spinner"></span><span class="brief-upload-label">Analyzing document...</span>`;

  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/clients/analyze-brief', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Analysis failed');
    }
    const data = await res.json();

    // Fill every field we got back
    if (data.name)     els.fName.value  = data.name;
    if (data.niche)    els.fNiche.value = data.niche;
    if (data.icp)      els.fIcp.value   = data.icp;
    if (data.cta_text) els.fCta.value   = data.cta_text;
    if (data.tone?.length) setTonePills(data.tone);
    if (data.language) els.fLanguage.value = data.language;

    if (data.primary_color && /^#[0-9a-f]{6}$/i.test(data.primary_color)) {
      els.fPrimary.value    = data.primary_color;
      els.fPrimaryHex.value = data.primary_color;
    }
    if (data.accent_color && /^#[0-9a-f]{6}$/i.test(data.accent_color)) {
      els.fAccent.value    = data.accent_color;
      els.fAccentHex.value = data.accent_color;
    }
    // Caption color: use explicit value, fall back to accent so brand color shows in video
    const capColor = (data.caption_color && /^#[0-9a-f]{6}$/i.test(data.caption_color))
      ? data.caption_color
      : (data.accent_color && /^#[0-9a-f]{6}$/i.test(data.accent_color))
        ? data.accent_color
        : null;
    if (capColor) {
      els.fCaptionColor.value    = capColor;
      els.fCaptionColorHex.value = capColor;
    }

    // Capture the rich onboarding fields (words, inspiration URLs, etc.) so they
    // persist on save even though they have no dedicated form inputs.
    state.onboarding = {
      words_favor:           Array.isArray(data.words_favor) ? data.words_favor : [],
      words_avoid:           Array.isArray(data.words_avoid) ? data.words_avoid : [],
      brand_characteristics: Array.isArray(data.brand_characteristics) ? data.brand_characteristics : [],
      inspiration_urls:      Array.isArray(data.inspiration_urls) ? data.inspiration_urls : [],
      core_philosophy:       data.core_philosophy || '',
      font:                  data.font || '',
    };

    const ob = state.onboarding;
    const extras = [];
    if (ob.inspiration_urls.length) extras.push(`${ob.inspiration_urls.length} inspiration link${ob.inspiration_urls.length !== 1 ? 's' : ''}`);
    if (ob.words_favor.length)      extras.push(`${ob.words_favor.length} words to favor`);
    if (ob.words_avoid.length)      extras.push(`${ob.words_avoid.length} words to avoid`);
    if (ob.brand_characteristics.length) extras.push(`${ob.brand_characteristics.length} brand traits`);
    const extrasLine = extras.length
      ? `<div class="brief-extras">Also captured: ${extras.join(' · ')}</div>` : '';

    zone.classList.remove('brief-loading');
    zone.classList.add('brief-done');
    inner.innerHTML = `<svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" style="color:var(--green);flex-shrink:0"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg><span class="brief-upload-label" style="color:var(--green)">Fields filled from document — review and save</span>${extrasLine}<button type="button" class="brief-reset-btn" id="brief-reset-btn">Clear</button>`;
    $('brief-reset-btn')?.addEventListener('click', resetBriefZone);

  } catch (err) {
    zone.classList.remove('brief-loading');
    zone.classList.add('brief-error');
    inner.innerHTML = `<span class="brief-upload-label" style="color:var(--red)">${err.message}</span><button type="button" class="brief-reset-btn" id="brief-reset-btn">Try again</button>`;
    $('brief-reset-btn')?.addEventListener('click', resetBriefZone);
  }
}

function resetBriefZone() {
  const zone  = $('brief-upload-zone');
  const inner = $('brief-upload-inner');
  zone.className = 'brief-upload-zone';
  inner.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-muted);flex-shrink:0"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><span class="brief-upload-label">Upload brand document to auto-fill</span><span class="brief-upload-hint">PDF, Word, image or text</span>`;
}

function setTonePills(active) {
  els.fTonePills.querySelectorAll('.tone-pill').forEach(p => {
    p.classList.toggle('active', active.includes(p.dataset.tone));
  });
}

function getActiveTones() {
  return [...els.fTonePills.querySelectorAll('.tone-pill.active')].map(p => p.dataset.tone);
}

function fillModalForm(c) {
  els.fName.value  = c.name;
  els.fNiche.value = c.niche || '';
  els.fIcp.value   = c.icp  || '';
  els.fCta.value   = c.cta_text || '';
  els.fSpecific.value = c.specific_instructions || '';
  setTonePills(c.tone || []);

  // Load stored onboarding data so re-saving the client preserves it
  state.onboarding = {
    words_favor:           c.words_favor || [],
    words_avoid:           c.words_avoid || [],
    brand_characteristics: c.brand_characteristics || [],
    inspiration_urls:      c.inspiration_urls || [],
    core_philosophy:       c.core_philosophy || '',
    font:                  c.brand?.font || '',
  };

  const capColor = c.editing?.caption_color || '#ffffff';
  els.fCaptionColor.value    = capColor;
  els.fCaptionColorHex.value = capColor;

  els.fPrimary.value    = c.brand?.primary_color || '#ffffff';
  els.fPrimaryHex.value = c.brand?.primary_color || '#ffffff';
  els.fAccent.value     = c.brand?.accent_color  || '#6366f1';
  els.fAccentHex.value  = c.brand?.accent_color  || '#6366f1';

  els.fLanguage.value = c.editing?.language || 'en';
  els.fSpeakers.value = String(c.editing?.num_speakers ?? 2);
  els.fGrade.value    = c.editing?.grade || '';
  els.fCapSize.value  = c.editing?.caption_font_size ?? 60;
  els.fCapY.value     = c.editing?.caption_y ?? 1300;

  const t = c.editing?.title || {};
  els.fTitleHand.value  = t.handwritten || '';
  els.fTitleLine1.value = (t.impact_lines || [])[0] || '';
  els.fTitleLine2.value = (t.impact_lines || [])[1] || '';
  els.fTitleDur.value   = t.duration ?? 4.5;
}

function closeModal() {
  els.modalOverlay.hidden = true;
  state.editClientId = null;
}

async function handleFormSubmit(e) {
  e.preventDefault();

  const ob = state.onboarding || {};
  const payload = {
    name:     els.fName.value.trim(),
    niche:    els.fNiche.value.trim(),
    tone:     getActiveTones(),
    icp:      els.fIcp.value.trim(),
    cta_text: els.fCta.value.trim(),
    specific_instructions: els.fSpecific.value.trim(),   // highest-priority hard rules
    // Rich onboarding data (from the onboarding-doc reader) — persisted on the client
    words_favor:           ob.words_favor || [],
    words_avoid:           ob.words_avoid || [],
    brand_characteristics: ob.brand_characteristics || [],
    inspiration_urls:      ob.inspiration_urls || [],
    core_philosophy:       ob.core_philosophy || '',
    brand: {
      primary_color: els.fPrimaryHex.value,
      accent_color:  els.fAccentHex.value,
      font:          ob.font || '',
    },
    editing: {
      language:          els.fLanguage.value,
      num_speakers:      Number(els.fSpeakers.value),
      grade:             els.fGrade.value.trim(),
      caption_font_size: Number(els.fCapSize.value),
      caption_y:         Number(els.fCapY.value),
      caption_color:     els.fCaptionColorHex.value,
      title: (() => {
        const line1 = els.fTitleLine1.value.trim().toUpperCase();
        const line2 = els.fTitleLine2.value.trim().toUpperCase();
        if (!line1) return null;
        return {
          handwritten:   els.fTitleHand.value.trim() || null,
          impact_lines:  line2 ? [line1, line2] : [line1],
          duration:      Number(els.fTitleDur.value),
        };
      })(),
    },
  };

  const btn = $('save-client-btn');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    if (state.editClientId) {
      await api.put(`/api/clients/${state.editClientId}`, payload);
      toast('Client updated', 'success');
    } else {
      await api.post('/api/clients', payload);
      toast('Client created', 'success');
    }
    await loadClients();
    closeModal();
  } catch (err) {
    toast('Save failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Client';
  }
}

// ── Color input sync ─────────────────────────────────────────────────────

function syncColorHex(picker, hex) {
  hex.value = picker.value;
}

function syncPickerFromHex(hex, picker) {
  const val = hex.value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(val)) picker.value = val;
}

// ── Drawer ───────────────────────────────────────────────────────────────

function openDrawer() {
  els.drawer.classList.add('open');
  els.drawerOverlay.classList.add('open');
}

function closeDrawer() {
  els.drawer.classList.remove('open');
  els.drawerOverlay.classList.remove('open');
}

// ── Jobs ─────────────────────────────────────────────────────────────────

const RUNNING = new Set(['normalizing', 'transcribing', 'generating_edl', 'rendering']);
let _pollTimer = null;

function updateWorkspace() {
  const client = state.clients.find(c => c.id === state.clientId);
  if (client) {
    els.workspaceArea.hidden = false;
    els.noClientPrompt.hidden = true;
    els.jobsSectionTitle.textContent = `${client.name}'s Jobs`;
    const color = client.brand?.accent_color || '#6366f1';
    els.wchDot.style.background = color;
    els.wchName.textContent = client.name;
  } else {
    els.workspaceArea.hidden = true;
    els.noClientPrompt.hidden = false;
  }
}

let _lastJobsSnapshot = '';
const _logOpenJobs = new Set();   // job ids whose technical log is expanded

function toggleJobLog(jobId) {
  const wasOpen = _logOpenJobs.has(jobId);
  if (wasOpen) _logOpenJobs.delete(jobId); else _logOpenJobs.add(jobId);

  const panel = document.getElementById(`log-${jobId}`);
  const btn   = panel?.previousElementSibling;
  if (panel) panel.classList.toggle('open', !wasOpen);
  if (btn)   btn.classList.toggle('open', !wasOpen);
  if (!wasOpen && panel) panel.scrollTop = panel.scrollHeight;
}

async function loadJobs() {
  try {
    const allJobs = await api.get('/api/jobs');
    const jobs = (state.clientId
      ? allJobs.filter(j => j.client_id === state.clientId)
      : allJobs).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    // Only touch the DOM when something actually changed — otherwise the
    // 3s poll re-renders identical cards, resetting animations/spinners and
    // causing a visible flicker/jump.
    const snapshot = JSON.stringify(jobs.map(j => [
      j.id, j.status, (j.log || []).length, j.output_size, j.broll_count,
    ]));
    if (snapshot !== _lastJobsSnapshot) {
      _lastJobsSnapshot = snapshot;
      renderJobs(jobs);
    }
    managePoll(jobs);
  } catch {
    els.jobsGrid.innerHTML = '<p class="empty-state">Could not load jobs.</p>';
    _lastJobsSnapshot = '';
  }
}

function managePoll(jobs) {
  const anyRunning = jobs.some(j => RUNNING.has(j.status));
  if (anyRunning && !_pollTimer) {
    _pollTimer = setInterval(loadJobs, 3000);
  } else if (!anyRunning && _pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

const STATUS_LABELS = {
  uploaded:       'Uploaded',
  normalizing:    'Normalizing...',
  transcribing:   'Transcribing...',
  generating_edl: 'Building EDL...',
  rendering:      'Rendering...',
  done:           'Done',
  failed:         'Failed',
  cancelled:      'Cancelled',
};

function getFriendlyError(log) {
  const errors = (log || []).filter(l => l.msg.startsWith('ERROR'));
  if (!errors.length) return null;
  const msg = errors[errors.length - 1].msg;

  if (/No video files found/i.test(msg)) {
    return {
      title:  'No footage found',
      detail: 'The uploaded folder contained no recognised video files.',
      fix:    'Re-upload your footage. Supported formats: .mov, .mp4, .mkv, .avi, .mxf.',
    };
  }
  if (/elevenlabs|ELEVENLABS_API_KEY/i.test(msg)) {
    return {
      title:  'Transcription key missing',
      detail: 'ElevenLabs could not be reached. The API key is likely missing or invalid.',
      fix:    'Add a valid ELEVENLABS_API_KEY to your .env file and restart the server.',
    };
  }
  if (/No on-camera speech/i.test(msg)) {
    return {
      title:  'No speech detected',
      detail: 'The transcription found no on-camera speaker in this footage.',
      fix:    'Open the client profile and check the Speaker setting. For solo footage set it to speaker_0.',
    };
  }
  if (/compose\.py|ffmpeg|FFMPEG ERROR/i.test(msg)) {
    return {
      title:  'Render failed',
      detail: 'ffmpeg hit an error while compositing the final video (overlays or captions).',
      fix:    'Open Technical details below for the exact ffmpeg error (the line starting "FFMPEG ERROR") and send it to Savas. If it was a one-off, a re-render may clear it.',
    };
  }
  if (/normalize|_v30/i.test(msg)) {
    return {
      title:  'Normalization failed',
      detail: 'Could not convert the footage to 1080x1920 30fps.',
      fix:    'Make sure the footage is a standard video format. Try re-exporting from your camera app.',
    };
  }
  return {
    title:  'Pipeline error',
    detail: msg.replace(/^ERROR:\s*/i, '').slice(0, 160),
    fix:    'Click Retry. If it keeps failing, check the full log above for more detail.',
  };
}

const PIPELINE_STEPS = [
  { status: 'normalizing',    label: 'Prepare'    },
  { status: 'transcribing',   label: 'Transcribe' },
  { status: 'generating_edl', label: 'AI Edit'    },
  { status: 'rendering',      label: 'Render'     },
  { status: 'done',           label: 'Finish'     },
];

const CHECK_SVG = '<svg viewBox="0 0 20 20" fill="none"><path d="M5 10.5l3.2 3.2L15 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function renderProgressSteps(job) {
  const jobStatus  = job.status;
  const currentIdx = PIPELINE_STEPS.findIndex(s => s.status === jobStatus);
  const lastMsg = [...(job.log || [])].reverse().find(l => l && l.msg && !l.msg.startsWith('ERROR'));
  const liveText = lastMsg ? lastMsg.msg : (STATUS_LABELS[jobStatus] || 'Working…');

  const row = PIPELINE_STEPS.map((s, i) => {
    const done    = i < currentIdx || jobStatus === 'done';
    const active  = i === currentIdx && jobStatus !== 'done';
    const cls     = done ? 'done' : active ? 'active' : 'upcoming';
    const node    = done ? CHECK_SVG : active ? '<span class="stage-spin"></span>' : (i + 1);
    const connCls = done ? 'done' : active ? 'active' : '';
    const conn    = i < PIPELINE_STEPS.length - 1 ? `<div class="stage-conn ${connCls}"></div>` : '';
    return `<div class="stage ${cls}"><div class="stage-node">${node}</div><div class="stage-name">${s.label}</div></div>${conn}`;
  }).join('');

  return `<div class="stage-tracker">
    <div class="stage-row">${row}</div>
    <div class="stage-live">
      <span class="stage-live-dot"></span>
      <span class="stage-live-text">${escapeHtml(liveText)}</span>
    </div>
  </div>`;
}

function renderJobs(jobs) {
  if (!jobs.length) {
    const client = state.clients.find(c => c.id === state.clientId);
    const name = client ? client.name : 'this client';
    els.jobsGrid.innerHTML = `<p class="empty-state">No jobs yet for ${escapeHtml(name)}. Drop footage above to get started.</p>`;
    return;
  }

  // Preserve any instructions / B-roll count the user is mid-editing, so a
  // re-render (triggered by another job's log growing) never wipes their input.
  const draftInstr = {}, draftBroll = {}, draftScript = {};
  document.querySelectorAll('.edit-instr[data-job]').forEach(t => { draftInstr[t.dataset.job] = t.value; });
  document.querySelectorAll('.broll-count-select[data-job]').forEach(s => { draftBroll[s.dataset.job] = s.value; });
  document.querySelectorAll('.edit-script[data-job]').forEach(t => { draftScript[t.dataset.job] = t.value; });
  const _active = document.activeElement;
  const focusedJob = _active?.classList?.contains('edit-instr') ? _active.dataset.job : null;
  const focusedScriptJob = _active?.classList?.contains('edit-script') ? _active.dataset.job : null;

  els.jobsGrid.innerHTML = jobs.map(j => {
    const videoCount = (j.files || []).filter(f => isVideo(f.path)).length;
    const meta = [
      j.client_name,
      `${(j.files || []).length} file${j.files?.length !== 1 ? 's' : ''}` +
        (videoCount ? ` (${videoCount} video${videoCount !== 1 ? 's' : ''})` : ''),
      formatBytes(j.total_bytes || 0),
    ].join(' · ');

    const isRunning  = RUNNING.has(j.status);
    const isDone     = j.status === 'done';
    // A previously finished render that is still retrievable (Drive link or a
    // local file), regardless of what the current render is doing.
    const hasPrevious = !isDone && Boolean(j.drive_link || j.output_path);
    const isFailed   = j.status === 'failed';
    const isCancelled = j.status === 'cancelled';
    const canRun     = j.status === 'uploaded' || isFailed || isCancelled;

    const safeFolder = (j.folder_name || 'untitled').replace(/'/g, "\\'");
    const savedInstructions = (j.palmier_instructions || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const savedScript = (j.script || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const savedBroll = (j.broll_count === 0 || j.broll_count) ? String(j.broll_count) : 'ai';
    const brollOpts = ['ai', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
      .map(v => {
        const label = v === 'ai' ? 'AI decides' : (v === '0' ? 'None' : v);
        const sel = v === savedBroll ? ' selected' : '';
        return `<option value="${v}"${sel}>${label}</option>`;
      }).join('');
    const instructionsHtml = canRun ? `
      <div class="edit-instr-row">
        <textarea
          class="edit-instr"
          data-job="${j.id}"
          placeholder="Filler words are cut automatically. Add optional instructions — e.g. add a hook that matches the topic, subtle zoom, add B-roll where it fits (or say 'keep the ums' to leave fillers in)"
          rows="2"
        >${savedInstructions}</textarea>
        <div class="broll-count-row">
          <label class="broll-count-label" for="broll-count-${j.id}">B-roll clips</label>
          <select class="broll-count-select" id="broll-count-${j.id}" data-job="${j.id}">${brollOpts}</select>
        </div>
        <div class="edit-script-block">
          <label class="edit-script-label" for="script-${j.id}">Script <span class="edit-script-hint">optional · paste what the client meant to say for a bulletproof clean cut in any language</span></label>
          <textarea
            class="edit-script"
            id="script-${j.id}"
            data-job="${j.id}"
            placeholder="Paste the exact script here. We hold the video against it and remove every hesitation, filler and false start — including the Danish ones the auto-cut can miss."
            rows="3"
          >${savedScript}</textarea>
        </div>
      </div>` : '';
    const actions = [
      canRun
        ? `<button class="btn btn-sm btn-primary" onclick="runPipeline('${j.id}')">${isFailed || isCancelled ? 'Retry' : 'Start Editing'}</button>`
        : '',
      isRunning
        ? `<button class="btn btn-sm btn-stop" onclick="stopJob('${j.id}')">Stop</button>`
        : '',
      isDone
        ? `<button class="btn btn-sm btn-outline" onclick="runPipeline('${j.id}')">Re-render</button>`
        : '',
      // Fail-safe: once a video has rendered successfully it stays reachable,
      // even while a re-render is running or after one fails. Hiding it made a
      // finished video look permanently deleted whenever a re-render got stuck.
      isDone
        ? `<a class="btn btn-sm btn-outline" href="/api/jobs/${j.id}/download">Download</a>`
        : (hasPrevious
            ? `<a class="btn btn-sm btn-outline" href="/api/jobs/${j.id}/download" title="The last version that finished rendering">Download last version</a>`
            : ''),
      isDone
        ? `<button class="btn btn-sm btn-outline" onclick="openZoomTimeline('${j.id}','${safeFolder}')">Zoom timeline</button>`
        : '',
      isDone
        ? `<button class="btn btn-sm btn-chat" onclick="openJobChat('${j.id}','${safeFolder}')">Edit video</button>`
        : '',
    ].filter(Boolean).join('');

    const progressHtml = isRunning ? renderProgressSteps(j) : '';

    const errorInfo = isFailed ? getFriendlyError(j.log) : null;
    const errorHtml = errorInfo
      ? `<div class="job-error-box">
           <div class="job-error-title">${errorInfo.title}</div>
           <div class="job-error-detail">${errorInfo.detail}</div>
           <div class="job-error-fix"><span class="job-error-fix-label">What to do:</span> ${errorInfo.fix}</div>
         </div>`
      : '';

    const logCount = (j.log || []).length;
    const logOpen  = _logOpenJobs.has(j.id);
    const logHtml = logCount
      ? `<div class="job-log-wrap">
           <button class="job-log-toggle${logOpen ? ' open' : ''}" onclick="toggleJobLog('${j.id}')">
             <svg class="job-log-arrow" viewBox="0 0 20 20" fill="none"><path d="M6 8l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
             <span>Technical details</span>
             <span class="job-log-count">${logCount}</span>
           </button>
           <div class="job-log${logOpen ? ' open' : ''}" id="log-${j.id}">
             <div class="log-entries">
               ${(j.log || []).map(l =>
                 `<div class="log-line${l.msg.startsWith('ERROR') ? ' log-error' : ''}">
                    <span class="log-time">${new Date(l.time).toLocaleTimeString()}</span>
                    <span>${escapeHtml(l.msg)}</span>
                  </div>`
               ).join('')}
             </div>
           </div>
         </div>`
      : '';

    return `
      <div class="job-card${isRunning ? ' job-running' : ''}${isDone ? ' job-done' : ''}${isFailed ? ' job-failed' : ''}">
        <div class="job-main">
          <div class="job-info">
            <div class="job-name">${escapeHtml(j.folder_name || 'untitled')}</div>
            <div class="job-meta">${escapeHtml(meta)}</div>
            ${j.notes ? `<div class="job-meta job-notes">${escapeHtml(j.notes)}</div>` : ''}
          </div>
          <div class="job-right">
            <div class="job-badge-row">
              <span class="badge badge-${j.status}">${STATUS_LABELS[j.status] || j.status}</span>
              <button class="job-del" title="Delete this job" onclick="deleteJob('${j.id}')">&times;</button>
            </div>
            ${actions ? `<div class="job-actions">${actions}</div>` : ''}
            <span class="job-time">${timeAgo(j.created_at)}</span>
          </div>
        </div>
        ${instructionsHtml}
        ${progressHtml}
        ${errorHtml}
        ${logHtml}
      </div>
    `;
  }).join('');

  // Restore in-progress drafts + focus captured before the rebuild
  document.querySelectorAll('.edit-instr[data-job]').forEach(t => {
    if (draftInstr[t.dataset.job] !== undefined) t.value = draftInstr[t.dataset.job];
    if (t.dataset.job === focusedJob) {
      t.focus();
      t.setSelectionRange(t.value.length, t.value.length);
    }
  });
  document.querySelectorAll('.broll-count-select[data-job]').forEach(s => {
    if (draftBroll[s.dataset.job] !== undefined) s.value = draftBroll[s.dataset.job];
  });
  document.querySelectorAll('.edit-script[data-job]').forEach(t => {
    if (draftScript[t.dataset.job] !== undefined) t.value = draftScript[t.dataset.job];
    if (t.dataset.job === focusedScriptJob) {
      t.focus();
      t.setSelectionRange(t.value.length, t.value.length);
    }
  });

  // Scroll open logs to bottom (only if the user has expanded them)
  jobs.forEach(j => {
    if (_logOpenJobs.has(j.id)) {
      const el = document.getElementById(`log-${j.id}`);
      if (el) el.scrollTop = el.scrollHeight;
    }
  });
}

window.toggleJobLog = toggleJobLog;

// ── Deleting jobs ─────────────────────────────────────────────────────────
window.deleteJob = async function (jobId) {
  if (!await confirmDialog('Delete this job and its files? Finished videos already in Drive are not affected.', 'Delete job')) return;
  try {
    await api.del(`/api/jobs/${jobId}`);
    toast('Job deleted', 'success');
    loadJobs();
  } catch (e) { toast('Could not delete: ' + e.message, 'error'); }
};

async function clearFailedJobs() {
  if (!await confirmDialog('Delete every failed and cancelled job, and their files? Finished videos in Drive are not affected.', 'Clear failed')) return;
  try {
    const r = await api.post('/api/jobs/clear', { statuses: ['failed', 'cancelled'] });
    toast(`Deleted ${r.deleted} job(s)` + (r.freed_mb ? `, freed ${r.freed_mb} MB` : ''), 'success');
    loadJobs();
  } catch (e) { toast('Could not clear: ' + e.message, 'error'); }
}
const _clearFailedBtn = $('clear-failed-btn');
if (_clearFailedBtn) _clearFailedBtn.addEventListener('click', clearFailedJobs);

// ── Pipeline controls ─────────────────────────────────────────────────────

async function runPipeline(jobId) {
  const textarea = document.querySelector(`.edit-instr[data-job="${jobId}"]`);
  const instructions = textarea ? textarea.value.trim() : '';
  const scriptEl = document.querySelector(`.edit-script[data-job="${jobId}"]`);
  const script = scriptEl ? scriptEl.value.trim() : '';
  const brollSel = document.querySelector(`.broll-count-select[data-job="${jobId}"]`);
  const broll_count = brollSel ? brollSel.value : 'ai';   // 'ai' | '0'..'10'
  try {
    await api.post(`/api/jobs/${jobId}/run`, { instructions, broll_count, script });
    toast(instructions ? 'AI editing started' : 'Editing started', 'success');
    await loadJobs();
  } catch (err) {
    toast('Could not start: ' + err.message, 'error');
  }
}

async function stopJob(jobId) {
  try {
    await api.post(`/api/jobs/${jobId}/cancel`, {});
    toast('Job stopped', 'info');
    await loadJobs();
  } catch (err) {
    toast('Could not stop: ' + err.message, 'error');
  }
}
window.stopJob = stopJob;

// ── B-roll library ────────────────────────────────────────────────────────

async function loadBroll(clientId) {
  if (!clientId) { els.brollSection.hidden = true; return; }
  els.brollSection.hidden = false;
  try {
    const clips = await api.get(`/api/clients/${clientId}/broll`);
    renderBrollList(clips, clientId);
  } catch { els.brollList.innerHTML = '<p class="empty-state" style="font-size:.8rem">Could not load B-roll.</p>'; }
}

// ── Style references (multiple clips → one combined style) ──────────────────

async function loadStyleSection(clientId) {
  if (!clientId) {
    els.styleSection.hidden = true;
    const ms = $('memory-section'); if (ms) ms.hidden = true;
    return;
  }
  els.styleSection.hidden = false;
  els.styleList.innerHTML = '';
  loadClientMemory(clientId);          // what this creator has taught us
  try {
    const data = await api.get(`/api/clients/${clientId}/style-refs`);
    renderStyleRefs(data.clips || [], clientId);
    renderStyleProfile(data.profile, (data.clips || []).length, clientId);
  } catch {
    renderStyleProfile(null, 0);
  }
}

function renderStyleRefs(clips, clientId) {
  if (!clips.length) { els.styleList.innerHTML = ''; return; }
  els.styleList.innerHTML = clips.map(name => `
    <div class="broll-clip-card">
      <div class="broll-clip-row">
        <span class="broll-clip-name">${escapeHtml(name)}</span>
        <button class="btn-icon" onclick="deleteStyleRef('${clientId}','${escapeHtml(name)}')" title="Remove">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </button>
      </div>
    </div>`).join('');
}

function renderStyleProfile(profile, clipCount = 0, clientId = null) {
  if (!profile || !profile.summary) { els.styleProfile.hidden = true; return; }
  const row = (label, val) => val ? `<div class="style-row"><span class="style-k">${label}</span><span class="style-v">${escapeHtml(val)}</span></div>` : '';
  const feats = Array.isArray(profile.features) && profile.features.length
    ? `<ul class="style-features">${profile.features.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>` : '';
  const isUpper = profile.caption_uppercase === true || String(profile.caption_uppercase).toLowerCase() === 'true';
  const applied = [];
  if (profile.grade_warmth && profile.grade_warmth !== 'neutral') applied.push(`${profile.grade_warmth} grade`);
  if (profile.grade_contrast && profile.grade_contrast !== 'normal') applied.push(`${profile.grade_contrast} contrast`);
  if (profile.grade_saturation && profile.grade_saturation !== 'normal') applied.push(`${profile.grade_saturation} colour`);
  if (profile.caption_size) applied.push(`${profile.caption_size} captions`);
  if (profile.caption_position) applied.push(`${profile.caption_position} placement`);
  if (isUpper) applied.push('ALL-CAPS captions');
  if (profile.caption_text_color && String(profile.caption_text_color).toLowerCase() !== 'none') applied.push(`${profile.caption_text_color} text`);
  if (profile.caption_highlight_color && String(profile.caption_highlight_color).toLowerCase() !== 'none') applied.push(`${profile.caption_highlight_color} highlight`);
  if (profile.caption_font && !['none', 'rounded', 'classic'].includes(String(profile.caption_font).toLowerCase())) applied.push(`${profile.caption_font} caption font`);
  if (typeof profile.cuts_per_minute === 'number' && profile.cuts_per_minute > 0) applied.push(`${profile.cuts_per_minute} cuts/min pacing`);
  else if (profile.pacing && profile.pacing !== 'medium') applied.push(`${profile.pacing} cuts`);
  if (profile.broll_intensity && !['none', 'ai'].includes(String(profile.broll_intensity).toLowerCase())) applied.push(`${profile.broll_intensity} B-roll`);
  if (profile.zoom_intensity && String(profile.zoom_intensity).toLowerCase() !== 'none') applied.push(`${profile.zoom_intensity} movement`);
  const appliedLine = applied.length
    ? `<div class="style-applied">✓ Auto-applied: ${escapeHtml(applied.join(' · '))}</div>` : '';
  const header = clipCount
    ? `<div class="style-header">Every video for this client now uses this style — drawn from ${clipCount} reference clip${clipCount !== 1 ? 's' : ''}:</div>` : '';
  const reBtn = clientId
    ? `<button class="btn btn-sm btn-outline" style="margin-top:12px" onclick="resyncStyle('${clientId}')">Re-apply latest style engine</button>` : '';
  els.styleProfile.hidden = false;
  els.styleProfile.innerHTML = `
    ${header}
    <div class="style-summary">${escapeHtml(profile.summary)}</div>
    ${feats}
    ${row('Captions', profile.caption_style)}
    ${row('Colour', profile.color_mood)}
    ${row('Pacing', profile.pacing)}
    ${row('Energy', profile.energy)}
    ${row('Text/hooks', profile.text_overlays)}
    ${appliedLine}
    ${reBtn}`;
}

async function resyncStyle(clientId) {
  const prev = state.clients.find(x => x.id === clientId)?.style_profile;
  els.styleProfile.innerHTML = `<div class="style-summary"><span class="brief-spinner"></span> Re-analyzing the reference clips with the latest style engine…</div>`;
  try {
    const r = await fetch(`/api/clients/${clientId}/style-refs/resynthesize`, { method: 'POST' });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || 'failed'); }
    const d = await r.json();
    renderStyleProfile(d.profile, (d.clips || []).length, clientId);
    const c = state.clients.find(x => x.id === clientId);
    if (c) c.style_profile = d.profile;
    toast('Style refreshed — new caption placement, colours and pacing now apply', 'success');
  } catch (e) {
    toast('Could not re-analyze: ' + e.message, 'error');
    renderStyleProfile(prev, 1, clientId);
  }
}
window.resyncStyle = resyncStyle;

async function uploadStyleRefs(clientId, files) {
  const n = files.length;
  els.styleProfile.hidden = false;
  els.styleProfile.innerHTML = `<div class="style-summary"><span class="brief-spinner"></span> Analyzing ${n} clip${n !== 1 ? 's' : ''} and combining the style…</div>`;
  let last = null;
  for (const file of files) {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`/api/clients/${clientId}/style-refs`, { method: 'POST', body: fd });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Analysis failed'); }
      last = await res.json();
    } catch (err) {
      toast(`Failed on ${file.name}: ${err.message}`, 'error');
    }
  }
  if (last) {
    renderStyleRefs(last.clips || [], clientId);
    renderStyleProfile(last.profile, (last.clips || []).length, clientId);
    const c = state.clients.find(x => x.id === clientId);
    if (c) c.style_profile = last.profile;
    toast('Style references analyzed — this client’s edits now match that style', 'success');
  }
}

async function deleteStyleRef(clientId, name) {
  try {
    const res = await api.del(`/api/clients/${clientId}/style-refs/${encodeURIComponent(name)}`);
    renderStyleRefs(res.clips || [], clientId);
    renderStyleProfile(res.profile, (res.clips || []).length, clientId);
    const c = state.clients.find(x => x.id === clientId);
    if (c) c.style_profile = res.profile || undefined;
  } catch (e) { toast('Could not remove clip: ' + e.message, 'error'); }
}
window.deleteStyleRef = deleteStyleRef;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderBrollList(clips, clientId) {
  if (!clips.length) {
    els.brollList.innerHTML = '<p style="font-size:.8rem;color:var(--text-dim);margin:8px 0">No clips yet.</p>';
    return;
  }
  els.brollList.innerHTML = clips.map(c => {
    let tagHtml;
    if (c.tag && (c.tag.description || (c.tag.keywords && c.tag.keywords.length))) {
      const kw = (c.tag.keywords || []).slice(0, 8)
        .map(k => `<span class="broll-kw">${escapeHtml(k)}</span>`).join('');
      tagHtml = `
        <div class="broll-clip-tag">
          <span class="broll-tag-desc">${escapeHtml(c.tag.description || '')}</span>
          <div class="broll-kw-row">${kw}</div>
        </div>`;
    } else {
      tagHtml = `<div class="broll-clip-tag"><span class="broll-tag-pending">Not analyzed yet — will be tagged on next render</span></div>`;
    }
    return `
    <div class="broll-clip-card">
      <div class="broll-clip-row">
        <span class="broll-clip-name">${escapeHtml(c.name)}</span>
        <span class="broll-clip-size">${formatBytes(c.size)}</span>
        <button class="btn-icon" onclick="deleteBroll('${clientId}','${escapeHtml(c.name)}')" title="Remove">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </button>
      </div>
      ${tagHtml}
    </div>`;
  }).join('');
}

async function uploadBroll(clientId, files) {
  let ok = 0;
  const n = files.length;
  toast(`Uploading and analyzing ${n} clip${n !== 1 ? 's' : ''}...`, 'info');
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(`/api/clients/${clientId}/broll`, { method: 'POST', body: fd });
      if (!res.ok) throw new Error(await res.text());
      ok++;
    } catch (e) { toast(`Failed to upload ${file.name}: ${e.message}`, 'error'); }
  }
  await loadBroll(clientId);
  if (ok) toast(`${ok} clip${ok !== 1 ? 's' : ''} added and analyzed`, 'success');
}

async function deleteBroll(clientId, name) {
  try {
    await api.del(`/api/clients/${clientId}/broll/${encodeURIComponent(name)}`);
  } catch (e) {
    toast('Could not remove clip: ' + e.message, 'error');
  }
  await loadBroll(clientId);
}

window.deleteBroll = deleteBroll;

// ── Event bindings ───────────────────────────────────────────────────────

function bindEvents() {
  // Click ripple on every button (premium tactile feedback)
  document.addEventListener('pointerdown', e => {
    const btn = e.target.closest('.btn');
    if (!btn || btn.disabled) return;
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const r = document.createElement('span');
    r.className = 'ripple';
    r.style.width = r.style.height = size + 'px';
    r.style.left = (e.clientX - rect.left - size / 2) + 'px';
    r.style.top  = (e.clientY - rect.top  - size / 2) + 'px';
    btn.appendChild(r);
    setTimeout(() => r.remove(), 600);
  });

  // Drop zone drag/drop
  els.dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    els.dropZone.classList.add('drag-over');
  });
  els.dropZone.addEventListener('dragleave', e => {
    if (!els.dropZone.contains(e.relatedTarget)) {
      els.dropZone.classList.remove('drag-over');
    }
  });
  els.dropZone.addEventListener('drop', e => {
    e.preventDefault();
    els.dropZone.classList.remove('drag-over');
    if (e.dataTransfer.items.length) {
      processDroppedItems(Array.from(e.dataTransfer.items));
    }
  });
  // Clicks on the zone (not on a label) open the file picker
  els.dropZone.addEventListener('click', e => {
    if (e.target.tagName !== 'LABEL') els.fileBrowse.click();
  });


  // File inputs (individual files and folder)
  els.fileBrowse.addEventListener('change', e => processInputFiles(e.target.files));
  els.fileBrowseFolder.addEventListener('change', e => processInputFiles(e.target.files));

  // Clear files
  els.clearBtn.addEventListener('click', clearFiles);

  // Client select — switches workspace
  els.clientSelect.addEventListener('change', e => {
    state.clientId = e.target.value;
    checkSubmitReady();
    updateWorkspace();
    loadJobs();
  });

  // Edit profile shortcut in workspace header
  els.wchEditBtn.addEventListener('click', () => openModal(state.clientId));

  // Quick add client
  els.newClientQuick.addEventListener('click', () => openModal());

  // Submit
  els.submitBtn.addEventListener('click', handleSubmit);

  // Refresh jobs
  els.refreshJobsBtn.addEventListener('click', loadJobs);

  // Drawer
  els.openClientsBtn.addEventListener('click', openDrawer);
  els.closeDrawerBtn.addEventListener('click', closeDrawer);
  els.drawerOverlay.addEventListener('click', closeDrawer);
  els.addClientDrawer.addEventListener('click', () => { closeDrawer(); openModal(); });

  // Modal
  els.closeModalBtn.addEventListener('click', closeModal);
  els.cancelModalBtn.addEventListener('click', closeModal);
  els.modalOverlay.addEventListener('click', e => { if (e.target === els.modalOverlay) closeModal(); });
  els.clientForm.addEventListener('submit', handleFormSubmit);

  // Color sync
  els.fPrimary.addEventListener('input', () => syncColorHex(els.fPrimary, els.fPrimaryHex));
  els.fPrimaryHex.addEventListener('input', () => syncPickerFromHex(els.fPrimaryHex, els.fPrimary));
  els.fAccent.addEventListener('input', () => syncColorHex(els.fAccent, els.fAccentHex));
  els.fAccentHex.addEventListener('input', () => syncPickerFromHex(els.fAccentHex, els.fAccent));
  els.fCaptionColor.addEventListener('input', () => syncColorHex(els.fCaptionColor, els.fCaptionColorHex));
  els.fCaptionColorHex.addEventListener('input', () => syncPickerFromHex(els.fCaptionColorHex, els.fCaptionColor));

  // Tone pill toggles
  els.fTonePills.addEventListener('click', e => {
    const pill = e.target.closest('.tone-pill');
    if (pill) pill.classList.toggle('active');
  });

  // Brand brief upload zone
  const briefZone  = $('brief-upload-zone');
  const briefInput = $('brief-file-input');

  briefZone.addEventListener('click', () => briefInput.click());
  briefInput.addEventListener('change', e => {
    if (e.target.files[0]) analyzeBrief(e.target.files[0]);
    briefInput.value = '';
  });

  briefZone.addEventListener('dragover', e => {
    e.preventDefault();
    briefZone.classList.add('brief-drag');
  });
  briefZone.addEventListener('dragleave', e => {
    if (!briefZone.contains(e.relatedTarget)) briefZone.classList.remove('brief-drag');
  });
  briefZone.addEventListener('drop', e => {
    e.preventDefault();
    briefZone.classList.remove('brief-drag');
    const f = e.dataTransfer.files[0];
    if (f) analyzeBrief(f);
  });

  // B-roll drop zone
  els.brollFileInput.addEventListener('change', e => {
    const files = [...e.target.files];
    if (files.length && state.editClientId) uploadBroll(state.editClientId, files);
    e.target.value = '';
  });
  // Click anywhere in the zone opens the native file browser (Finder / Explorer).
  // Guard against the input's own bubbled click re-triggering this handler.
  els.brollDropZone.addEventListener('click', e => {
    if (e.target !== els.brollFileInput) els.brollFileInput.click();
  });
  els.brollDropZone.addEventListener('dragover', e => { e.preventDefault(); els.brollDropZone.classList.add('broll-drag'); });
  els.brollDropZone.addEventListener('dragleave', e => { if (!els.brollDropZone.contains(e.relatedTarget)) els.brollDropZone.classList.remove('broll-drag'); });
  els.brollDropZone.addEventListener('drop', e => {
    e.preventDefault();
    els.brollDropZone.classList.remove('broll-drag');
    const files = [...e.dataTransfer.files].filter(f => f.type.startsWith('video/'));
    if (files.length && state.editClientId) uploadBroll(state.editClientId, files);
  });

  // Style references drop zone (multiple clips)
  els.styleFileInput.addEventListener('change', e => {
    const files = [...e.target.files];
    if (files.length && state.editClientId) uploadStyleRefs(state.editClientId, files);
    e.target.value = '';
  });
  els.styleDropZone.addEventListener('click', e => {
    if (e.target !== els.styleFileInput) els.styleFileInput.click();
  });
  els.styleDropZone.addEventListener('dragover', e => { e.preventDefault(); els.styleDropZone.classList.add('broll-drag'); });
  els.styleDropZone.addEventListener('dragleave', e => { if (!els.styleDropZone.contains(e.relatedTarget)) els.styleDropZone.classList.remove('broll-drag'); });
  els.styleDropZone.addEventListener('drop', e => {
    e.preventDefault();
    els.styleDropZone.classList.remove('broll-drag');
    const files = [...e.dataTransfer.files].filter(f => f.type.startsWith('video/'));
    if (files.length && state.editClientId) uploadStyleRefs(state.editClientId, files);
  });

  // Logout
  document.getElementById('logout-btn')?.addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/login';
  });

  // Keyboard
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (!els.modalOverlay.hidden) closeModal();
      else closeDrawer();
    }
  });
}

// ── Init ─────────────────────────────────────────────────────────────────

async function init() {
  bindEvents();
  await loadClients();
  await loadJobs();
  checkDiskSpace();
}

// A full volume makes uploads stall and renders fail. That used to be invisible
// until something broke, so warn while there is still time to act.
async function checkDiskSpace() {
  try {
    const d = await api.get('/api/admin/storage');
    if (!d || typeof d.free_gb !== 'number' || d.free_gb > 1.0) return;
    if (document.getElementById('disk-warning')) return;
    const bar = document.createElement('div');
    bar.id = 'disk-warning';
    bar.className = 'disk-warning';
    bar.innerHTML =
      `<strong>Storage almost full</strong> — only ${d.free_gb.toFixed(2)} GB of ${d.total_gb} GB left. ` +
      `Uploads will fail until you free space. ` +
      `<a href="/setup.html">Open Control Center</a> to delete old jobs ` +
      `(finished videos already in Drive are not affected).`;
    document.body.prepend(bar);
  } catch {}
}

init();

// expose for inline onclick handlers
window.openModal = openModal;
window.deleteClient = deleteClient;
window.runPipeline = runPipeline;


// ── AI Chat ───────────────────────────────────────────────────────────────

const chat = {
  open:    false,
  pending: false,
  history: [],
  jobId:   null,
  jobName: null,
};

const chatEls = {
  fab:      $('chat-fab'),
  badge:    $('chat-badge'),
  panel:    $('chat-panel'),
  messages: $('chat-messages'),
  input:    $('chat-input'),
  sendBtn:  $('chat-send-btn'),
  closeBtn: $('close-chat-btn'),
};

function chatSetMode(jobId, jobName) {
  chat.jobId   = jobId || null;
  chat.jobName = jobName || null;
  chat.history = [];
  const title    = chatEls.panel.querySelector('.chat-title');
  const subtitle = chatEls.panel.querySelector('.chat-subtitle');
  if (jobId) {
    title.textContent    = jobName || 'Edit Video';
    subtitle.textContent = 'Changes apply to this video only';
    chatEls.messages.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div>
          <div class="chat-welcome-title">Editing this video</div>
          <div class="chat-welcome-body">Changes go to this video only. Re-render starts automatically. Say "set as default" to change all future videos.</div>
        </div>
        <div class="chat-welcome-hints">
          <button class="chat-hint" data-hint="Move the captions up">Move captions up</button>
          <button class="chat-hint" data-hint="The color is too warm">Too warm</button>
          <button class="chat-hint" data-hint="Make the captions bigger">Bigger captions</button>
        </div>
      </div>`;
  } else {
    title.textContent    = 'AI Assistant';
    subtitle.textContent = 'Adjusts your client settings';
    chatEls.messages.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div>
          <div class="chat-welcome-title">How can I help?</div>
          <div class="chat-welcome-body">Describe the issue and I'll update your client settings directly.</div>
        </div>
        <div class="chat-welcome-hints">
          <button class="chat-hint" data-hint="The color is too warm">The color is too warm</button>
          <button class="chat-hint" data-hint="The saturation is too high">The saturation is too high</button>
          <button class="chat-hint" data-hint="Make the captions bigger">Make the captions bigger</button>
        </div>
      </div>`;
  }
  chatEls.messages.querySelectorAll('.chat-hint').forEach(btn => {
    btn.addEventListener('click', () => chatSend(btn.dataset.hint));
  });
}

function openJobChat(jobId, jobName) {
  chatSetMode(jobId, jobName);
  if (!chat.open) chatToggle();
  else requestAnimationFrame(() => { chatEls.input.focus(); chatScrollBottom(); });
}
window.openJobChat = openJobChat;

function chatToggle() {
  if (chat.open) {
    chat.open = false;
    chatEls.fab.classList.remove('is-open');
    chatEls.panel.classList.remove('is-open');
    chatEls.panel.classList.add('is-closing');
    chatEls.panel.addEventListener('animationend', () => {
      chatEls.panel.classList.remove('is-closing');
    }, { once: true });
  } else {
    if (!chat.jobId) chatSetMode(null, null);
    chat.open = true;
    chatEls.fab.classList.add('is-open');
    chatEls.panel.classList.add('is-open');
    chatEls.badge.classList.remove('visible');
    requestAnimationFrame(() => {
      chatEls.input.focus();
      chatScrollBottom();
    });
  }
}

function chatScrollBottom() {
  chatEls.messages.scrollTo({ top: chatEls.messages.scrollHeight, behavior: 'smooth' });
}

function chatHideWelcome() {
  const welcome = chatEls.messages.querySelector('.chat-welcome');
  if (welcome) welcome.remove();
}

function chatAddMessage(role, text, actions) {
  chatHideWelcome();

  const wrap = document.createElement('div');
  wrap.className = `chat-msg chat-msg-${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);

  if (actions && actions.length) {
    actions.forEach(a => {
      const chip = document.createElement('span');
      chip.className = 'chat-action-chip';
      if (a.type === 'settings_updated') {
        const keys = Object.keys(a.changes || {});
        chip.textContent = keys.length
          ? `${keys.join(', ')} updated for ${a.client_name}`
          : `Changes applied for ${a.client_name}`;
        wrap.appendChild(chip);
      } else if (a.type === 'job_rerendering') {
        chip.className += ' chat-action-chip-render';
        chip.textContent = 'Re-rendering video with changes...';
        wrap.appendChild(chip);
        setTimeout(() => loadJobs(), 1000);
      }
    });
  }

  chatEls.messages.appendChild(wrap);
  requestAnimationFrame(() => chatScrollBottom());
  return wrap;
}

function chatAddLoading() {
  chatHideWelcome();
  const wrap = document.createElement('div');
  wrap.className = 'chat-msg chat-msg-assistant chat-loading';
  wrap.innerHTML = `<div class="chat-bubble"><span class="chat-dot"></span><span class="chat-dot"></span><span class="chat-dot"></span></div>`;
  chatEls.messages.appendChild(wrap);
  requestAnimationFrame(() => chatScrollBottom());
  return wrap;
}

async function chatSend(text) {
  text = (text || chatEls.input.value).trim();
  if (!text || chat.pending) return;

  chatEls.input.value = '';
  chatEls.input.style.height = '';
  chatAddMessage('user', text);

  chat.pending = true;
  chatEls.sendBtn.disabled = true;

  const loader = chatAddLoading();

  try {
    const clientId = els.clientSelect.value || null;
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, client_id: clientId, job_id: chat.jobId || null, history: chat.history }),
    });

    const data = await res.json();
    loader.remove();

    const reply = data.reply || 'No response.';
    chatAddMessage('assistant', reply, data.actions || []);

    chat.history.push({ role: 'user',      content: text  });
    chat.history.push({ role: 'assistant', content: reply });

    if (data.actions && data.actions.length) {
      await loadClients();
    }

    if (!chat.open) {
      chatEls.badge.classList.add('visible');
    }
  } catch {
    loader.remove();
    chatAddMessage('assistant', 'Something went wrong. Please try again.');
  } finally {
    chat.pending = false;
    chatEls.sendBtn.disabled = false;
    if (chat.open) chatEls.input.focus();
  }
}

chatEls.fab.addEventListener('click', chatToggle);
chatEls.closeBtn.addEventListener('click', chatToggle);
chatEls.sendBtn.addEventListener('click', () => chatSend());

chatEls.input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); chatSend(); }
});

chatEls.input.addEventListener('input', () => {
  chatEls.input.style.height = 'auto';
  chatEls.input.style.height = Math.min(chatEls.input.scrollHeight, 120) + 'px';
});

chatEls.messages.addEventListener('click', e => {
  const hint = e.target.closest('.chat-hint');
  if (hint) chatSend(hint.dataset.hint);
});

// ── Zoom timeline: drag-and-drop punch-in markers ─────────────────────────
const zt = { jobId: null, duration: 0, t: 0, markers: [], selected: null, drag: null };
const ztEls = {
  overlay:  $('zt-overlay'),  video:   $('zt-video'),      fallback: $('zt-video-fallback'),
  bar:      $('zt-bar'),      progress:$('zt-progress'),   playhead: $('zt-playhead'),
  cur:      $('zt-time-cur'), dur:     $('zt-time-dur'),   add:      $('zt-add-btn'),
  sel:      $('zt-selected'), selAt:   $('zt-sel-at'),     selStr:   $('zt-sel-strength'),
  selDur:   $('zt-sel-duration'), del:  $('zt-del-btn'),   apply:    $('zt-apply-btn'),
  subtitle: $('zt-subtitle'),
};

function ztFmt(s) {
  s = Math.max(0, s || 0);
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

async function openZoomTimeline(jobId, jobName) {
  zt.jobId = jobId; zt.markers = []; zt.selected = null; zt.drag = null; zt.t = 0;
  ztEls.subtitle.textContent = jobName
    ? `"${jobName}" — drag markers to set where the video punches in`
    : 'Drag markers to set where the video punches in';
  ztEls.overlay.hidden = false;
  ztSetPlayhead(0);
  try {
    const r = await fetch(`/api/jobs/${jobId}/zooms`);
    const d = await r.json();
    zt.duration = d.duration || 0;
    zt.markers = (d.zooms || []).map(z => ({
      at: +z.at || 0, duration: +z.duration || 2.5, strength: +z.strength || 0.12,
    }));
    ztEls.dur.textContent = ztFmt(zt.duration);
    if (d.has_local_video) {
      ztEls.video.hidden = false; ztEls.fallback.hidden = true;
      ztEls.video.src = d.video_url;
      ztEls.video.onloadedmetadata = () => {
        if (!zt.duration || Math.abs(ztEls.video.duration - zt.duration) > 0.6) {
          zt.duration = ztEls.video.duration;
          ztEls.dur.textContent = ztFmt(zt.duration);
          ztRender();
        }
      };
    } else {
      ztEls.video.hidden = true; ztEls.fallback.hidden = false; ztEls.video.removeAttribute('src');
    }
    ztRender();
  } catch { toast('Could not load the timeline', 'error'); }
}
window.openZoomTimeline = openZoomTimeline;

function ztClose() {
  ztEls.overlay.hidden = true;
  try { ztEls.video.pause(); } catch {}
  ztEls.video.removeAttribute('src');
}

function ztSetPlayhead(t) {
  t = Math.min(zt.duration || 0, Math.max(0, t));
  zt.t = t;
  const pct = ((t / (zt.duration || 1)) * 100);
  ztEls.playhead.style.left = `${pct}%`;
  ztEls.progress.style.width = `${pct}%`;
  ztEls.cur.textContent = ztFmt(t);
}

function ztRender() {
  [...ztEls.bar.querySelectorAll('.zt-marker')].forEach(n => n.remove());
  const D = zt.duration || 1;
  zt.markers.forEach((m, i) => {
    const el = document.createElement('div');
    el.className = 'zt-marker' + (zt.selected === i ? ' sel' : '');
    el.style.left = `${Math.min(100, Math.max(0, (m.at / D) * 100))}%`;
    el.title = `Zoom at ${ztFmt(m.at)}`;
    el.innerHTML = '<span class="zt-marker-cap"></span>';
    el.addEventListener('pointerdown', e => ztStartDrag(e, i));
    ztEls.bar.appendChild(el);
  });
  if (zt.selected != null && zt.markers[zt.selected]) {
    const m = zt.markers[zt.selected];
    ztEls.sel.hidden = false;
    ztEls.selAt.textContent = ztFmt(m.at);
    ztEls.selStr.value = String(m.strength);
    ztEls.selDur.value = String(m.duration);
  } else {
    ztEls.sel.hidden = true;
  }
}

function ztPct(clientX) {
  const rect = ztEls.bar.getBoundingClientRect();
  return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
}

function ztStartDrag(e, i) {
  e.preventDefault(); e.stopPropagation();
  zt.selected = i; zt.drag = i;
  ztRender();
  const markerEl = ztEls.bar.querySelectorAll('.zt-marker')[i];
  markerEl?.classList.add('dragging');
  const move = ev => {
    const t = ztPct(ev.clientX) * zt.duration;
    zt.markers[i].at = Math.round(t * 100) / 100;
    if (markerEl) markerEl.style.left = `${(zt.markers[i].at / (zt.duration || 1)) * 100}%`;
    ztEls.selAt.textContent = ztFmt(zt.markers[i].at);
  };
  const up = () => {
    zt.drag = null;
    markerEl?.classList.remove('dragging');
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

ztEls.bar.addEventListener('pointerdown', e => {
  if (e.target.closest('.zt-marker')) return;   // markers handle their own drag
  ztSeek(ztPct(e.clientX) * zt.duration);
  zt.selected = null;
  ztRender();
});

function ztSeek(t) {
  ztSetPlayhead(t);
  if (ztEls.video.src && !ztEls.video.hidden) { try { ztEls.video.currentTime = zt.t; } catch {} }
}

ztEls.video.addEventListener('timeupdate', () => {
  if (!ztEls.video.hidden && zt.drag == null) ztSetPlayhead(ztEls.video.currentTime);
});

ztEls.add.addEventListener('click', () => {
  const t = Math.round(zt.t * 100) / 100;
  if (zt.markers.some(m => Math.abs(m.at - t) < 0.4)) {
    toast('There is already a zoom near here', 'info');
    return;
  }
  zt.markers.push({ at: t, duration: 2.5, strength: 0.12 });
  zt.selected = zt.markers.length - 1;
  ztRender();
});

ztEls.selStr.addEventListener('change', () => {
  if (zt.selected != null) zt.markers[zt.selected].strength = +ztEls.selStr.value;
});
ztEls.selDur.addEventListener('change', () => {
  if (zt.selected != null) zt.markers[zt.selected].duration = +ztEls.selDur.value;
});
ztEls.del.addEventListener('click', () => {
  if (zt.selected != null) { zt.markers.splice(zt.selected, 1); zt.selected = null; ztRender(); }
});

ztEls.apply.addEventListener('click', async () => {
  ztEls.apply.disabled = true;
  try {
    const r = await fetch(`/api/jobs/${zt.jobId}/zooms`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zooms: zt.markers }),
    });
    if (!r.ok) throw new Error();
    const n = zt.markers.length;
    toast(`${n} zoom${n !== 1 ? 's' : ''} applied — re-rendering`, 'success');
    ztClose();
    loadJobs();
  } catch {
    toast('Could not apply zooms', 'error');
  } finally {
    ztEls.apply.disabled = false;
  }
});

$('zt-close-btn').addEventListener('click', ztClose);
$('zt-cancel-btn').addEventListener('click', ztClose);
ztEls.overlay.addEventListener('click', e => { if (e.target === ztEls.overlay) ztClose(); });

// ── Per-creator style memory: learned habits, operator approves ────────────
const MEM_CAT = { caption: 'Captions', grade: 'Colour', broll: 'B-roll & photos', zoom: 'Zooms' };

async function loadClientMemory(clientId) {
  const sec = $('memory-section'), panel = $('memory-panel');
  if (!sec || !panel) return;
  if (!clientId) { sec.hidden = true; return; }
  try {
    const d = await api.get(`/api/clients/${clientId}/memory`);
    renderClientMemory(d, clientId);
  } catch {
    sec.hidden = true;
  }
}

function renderClientMemory(d, clientId) {
  const sec = $('memory-section'), panel = $('memory-panel');
  const pending = d.pending || [], accepted = d.accepted || [];
  if (!pending.length && !accepted.length) {
    sec.hidden = false;
    panel.innerHTML = `<div class="mem-empty">Nothing learned yet. Make a few edits to this client's videos and repeated changes will show up here.</div>`;
    return;
  }
  sec.hidden = false;
  const suggHtml = pending.map(s => `
    <div class="mem-sugg">
      <div class="mem-sugg-main">
        <span class="mem-cat">${escapeHtml(MEM_CAT[s.category] || s.category)}</span>
        <span class="mem-label">${escapeHtml(s.label)}</span>
        <span class="mem-count">seen ${s.count}×</span>
      </div>
      <div class="mem-actions">
        <button class="btn btn-sm btn-primary" onclick="acceptMemory('${clientId}','${s.id}')">Make default</button>
        <button class="btn btn-sm btn-ghost" onclick="ignoreMemory('${clientId}','${s.id}')">Ignore</button>
      </div>
    </div>`).join('');
  const accHtml = accepted.map(a => `
    <div class="mem-acc">
      <span class="mem-cat">${escapeHtml(MEM_CAT[a.category] || a.category)}</span>
      <span class="mem-label">${escapeHtml(a.label)}</span>
      <button class="btn-icon" title="Forget this" onclick="forgetMemory('${clientId}','${escapeHtml(a.key)}')">
        <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
      </button>
    </div>`).join('');
  panel.innerHTML =
    (pending.length ? `<div class="mem-head">Noticed a pattern</div>${suggHtml}` : '') +
    (accepted.length ? `<div class="mem-head">Now their default</div>${accHtml}` : '');
}

async function acceptMemory(clientId, id) {
  try {
    await api.post(`/api/clients/${clientId}/memory/${id}/accept`, {});
    toast('Saved as this client’s default for future videos', 'success');
    loadClientMemory(clientId);
  } catch (e) { toast('Could not save: ' + e.message, 'error'); }
}
async function ignoreMemory(clientId, id) {
  try {
    await api.post(`/api/clients/${clientId}/memory/${id}/ignore`, {});
    loadClientMemory(clientId);
  } catch (e) { toast('Could not ignore: ' + e.message, 'error'); }
}
async function forgetMemory(clientId, key) {
  if (!await confirmDialog('Forget this learned preference? Future videos go back to the normal default.', 'Forget')) return;
  try {
    await api.del(`/api/clients/${clientId}/memory/${encodeURIComponent(key)}`);
    toast('Forgotten', 'success');
    loadClientMemory(clientId);
  } catch (e) { toast('Could not forget: ' + e.message, 'error'); }
}
window.acceptMemory = acceptMemory;
window.ignoreMemory = ignoreMemory;
window.forgetMemory = forgetMemory;
window.loadClientMemory = loadClientMemory;

// ── Don't lose an upload by navigating away ───────────────────────────────
// The upload runs as an XHR on this page, so any navigation aborts it. Two
// guards: the browser's own unload prompt (covers refresh, back, closing the
// tab, typing a URL) and an in-app confirm for our own links, which can explain
// what is actually at stake instead of the generic browser wording.
window.addEventListener('beforeunload', e => {
  if (uploadInFlight > 0) { e.preventDefault(); e.returnValue = ''; return ''; }
});

document.addEventListener('click', async e => {
  if (uploadInFlight <= 0) return;
  const link = e.target.closest('a[href]');
  if (!link) return;
  const href = link.getAttribute('href') || '';
  // Ignore anchors, new tabs and non-navigating links
  if (!href || href.startsWith('#') || link.target === '_blank') return;
  if (link.hasAttribute('download')) return;

  e.preventDefault();
  e.stopPropagation();
  const ok = await confirmDialog(
    'A video is still uploading. Leaving this page now cancels the upload and you will have to start it again.',
    'Leave and cancel upload');
  if (ok) {
    uploadInFlight = 0;          // user chose to abandon it; skip the unload prompt
    window.location.href = href;
  }
}, true);
