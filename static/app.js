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

async function handleSubmit() {
  if (!state.files.length || !state.clientId) return;

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

function uploadWithProgress(formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', e => {
      if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 95));
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`${xhr.status} ${xhr.statusText}`));
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
  if (!confirm(`Delete client "${name}"? This cannot be undone.`)) return;
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

  if (/captions\.mov|animations[/\\]|exit status 234/i.test(msg)) {
    return {
      title:  'Internal file conflict',
      detail: 'The pipeline accidentally tried to process an overlay file as source footage.',
      fix:    'This has been fixed. Click Retry — it will not happen again.',
    };
  }
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
  if (/compose\.py|ffmpeg/i.test(msg)) {
    return {
      title:  'Render failed',
      detail: 'ffmpeg ran into an error while compositing the final video.',
      fix:    'Check that the footage is not corrupt. Try re-uploading the original clip.',
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
      isDone
        ? `<a class="btn btn-sm btn-outline" href="/api/jobs/${j.id}/download">Download</a>`
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
            <span class="badge badge-${j.status}">${STATUS_LABELS[j.status] || j.status}</span>
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
  if (!clientId) { els.styleSection.hidden = true; return; }
  els.styleSection.hidden = false;
  els.styleList.innerHTML = '';
  try {
    const data = await api.get(`/api/clients/${clientId}/style-refs`);
    renderStyleRefs(data.clips || [], clientId);
    renderStyleProfile(data.profile, (data.clips || []).length);
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

function renderStyleProfile(profile, clipCount = 0) {
  if (!profile || !profile.summary) { els.styleProfile.hidden = true; return; }
  const row = (label, val) => val ? `<div class="style-row"><span class="style-k">${label}</span><span class="style-v">${escapeHtml(val)}</span></div>` : '';
  const feats = Array.isArray(profile.features) && profile.features.length
    ? `<ul class="style-features">${profile.features.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>` : '';
  const applied = [];
  if (profile.grade_warmth && profile.grade_warmth !== 'neutral') applied.push(`${profile.grade_warmth} grade`);
  if (profile.grade_contrast && profile.grade_contrast !== 'normal') applied.push(`${profile.grade_contrast} contrast`);
  if (profile.grade_saturation && profile.grade_saturation !== 'normal') applied.push(`${profile.grade_saturation} colour`);
  if (profile.caption_size) applied.push(`${profile.caption_size} captions`);
  const appliedLine = applied.length
    ? `<div class="style-applied">✓ Auto-applied: ${escapeHtml(applied.join(' · '))}</div>` : '';
  const header = clipCount
    ? `<div class="style-header">Every video for this client now uses this style — drawn from ${clipCount} reference clip${clipCount !== 1 ? 's' : ''}:</div>` : '';
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
    ${appliedLine}`;
}

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
    renderStyleProfile(last.profile, (last.clips || []).length);
    const c = state.clients.find(x => x.id === clientId);
    if (c) c.style_profile = last.profile;
    toast('Style references analyzed — this client’s edits now match that style', 'success');
  }
}

async function deleteStyleRef(clientId, name) {
  try {
    const res = await api.del(`/api/clients/${clientId}/style-refs/${encodeURIComponent(name)}`);
    renderStyleRefs(res.clips || [], clientId);
    renderStyleProfile(res.profile, (res.clips || []).length);
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
