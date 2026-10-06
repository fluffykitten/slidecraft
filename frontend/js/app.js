/**
 * SlideCraft App Logic
 * Coordinates drag & drop, batch conversion, options, and results presentation.
 */

// Toast Notification Utility
window.showToast = function (message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const iconSvg = type === 'success'
    ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
    : type === 'error'
    ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>'
    : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#18181b" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';

  toast.innerHTML = `${iconSvg}<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.22s ease';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
};

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  const browseBtn = document.getElementById('browseBtn');
  const fileList = document.getElementById('fileList');
  const convertBtn = document.getElementById('convertBtn');
  const convertBtnText = document.getElementById('convertBtnText');
  const conversionModeSelect = document.getElementById('conversionModeSelect');
  const headingFontSelect = document.getElementById('headingFontSelect');
  const bodyFontSelect = document.getElementById('bodyFontSelect');
  const ratioSelect = document.getElementById('ratioSelect');
  const aiToggle = document.getElementById('aiToggle');
  const pageRangeInput = document.getElementById('pageRangeInput');
  const resultsCard = document.getElementById('resultsCard');
  const resultsList = document.getElementById('resultsList');
  const convertAnotherBtn = document.getElementById('convertAnotherBtn');

  // AI & Settings elements
  const aiStatusPill = document.getElementById('aiStatusPill');
  const aiStatusText = document.getElementById('aiStatusText');
  const openSettingsBtn = document.getElementById('openSettingsBtn');
  const closeSettingsBtn = document.getElementById('closeSettingsBtn');
  const settingsModal = document.getElementById('settingsModal');
  const backendUrlInput = document.getElementById('backendUrlInput');
  const testBackendBtn = document.getElementById('testBackendBtn');
  const backendTestStatus = document.getElementById('backendTestStatus');
  const geminiApiKeyInput = document.getElementById('geminiApiKeyInput');
  const testApiKeyBtn = document.getElementById('testApiKeyBtn');
  const apiKeyTestStatus = document.getElementById('apiKeyTestStatus');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');
  const backendNoticeBanner = document.getElementById('backendNoticeBanner');
  const openSettingsFromBannerBtn = document.getElementById('openSettingsFromBannerBtn');

  if (openSettingsFromBannerBtn) {
    openSettingsFromBannerBtn.addEventListener('click', () => {
      openSettingsBtn.click();
    });
  }

  // State
  let selectedFiles = [];
  let serverHasGeminiKey = false;
  let customGeminiKey = localStorage.getItem('slidecraft_gemini_key') || '';
  let selectedModel = localStorage.getItem('slidecraft_ai_model') || 'gemini-3.5-flash-lite';

  // Model Select Elements
  const modelSelect = document.getElementById('modelSelect');
  const settingsModelSelect = document.getElementById('settingsModelSelect');
  const modelSelectGroup = document.getElementById('modelSelectGroup');

  // Initialize helper modules
  const previewManager = new window.PreviewManager();
  const progressTracker = new window.ProgressTracker({
    onComplete: (data) => handleConversionComplete(data),
    onError: (data) => handleConversionError(data)
  });

  // Fetch available AI models from backend
  async function fetchAvailableModels() {
    try {
      const { data } = await window.safeFetch('/api/models');
      if (data) {
        const models = data.models || [];
        populateModelDropdowns(models, data.default_model);
      }
    } catch (e) {
      console.warn('Models fetch error:', e.message);
    }
  }

  function populateModelDropdowns(models, defaultModelId) {
    if (!modelSelect || !models.length) return;

    const savedModel = localStorage.getItem('slidecraft_ai_model') || defaultModelId || 'gemini-3.6-flash';
    selectedModel = savedModel;

    [modelSelect, settingsModelSelect].forEach(selectElem => {
      if (!selectElem) return;
      selectElem.innerHTML = '';
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = `${m.name} (${m.badge})`;
        if (m.id === selectedModel) {
          opt.selected = true;
        }
        selectElem.appendChild(opt);
      });
    });

    updateAIStatusUI();
  }

  if (modelSelect) {
    modelSelect.addEventListener('change', () => {
      selectedModel = modelSelect.value;
      localStorage.setItem('slidecraft_ai_model', selectedModel);
      if (settingsModelSelect) settingsModelSelect.value = selectedModel;
      updateAIStatusUI();
    });
  }

  if (settingsModelSelect) {
    settingsModelSelect.addEventListener('change', () => {
      selectedModel = settingsModelSelect.value;
      localStorage.setItem('slidecraft_ai_model', selectedModel);
      if (modelSelect) modelSelect.value = selectedModel;
      updateAIStatusUI();
    });
  }

  // Check server configuration
  async function fetchServerConfig() {
    try {
      const { data: config } = await window.safeFetch('/api/config');
      if (config) {
        serverHasGeminiKey = config.has_gemini_key;
        updateAIStatusUI();
        if (backendNoticeBanner) backendNoticeBanner.style.display = 'none';
      }
    } catch (e) {
      console.warn('Config fetch error:', e.message);
      if (backendNoticeBanner && (window.isStaticHosted() || !window.getApiBaseUrl())) {
        backendNoticeBanner.style.display = 'flex';
      }
    }
  }

  fetchServerConfig();
  fetchAvailableModels();

  function getModelDisplayName(id) {
    const map = {
      'gemini-3.6-flash': 'Gemini 3.6 Flash',
      'gemini-3.5-flash': 'Gemini 3.5 Flash',
      'gemini-3.5-flash-lite': 'Gemini 3.5 Flash-Lite',
      'gemini-3.8-flash': 'Gemini 3.8 Flash',
      'gemini-3.1-flash-lite': 'Gemini 3.1 Flash-Lite',
      'gemini-3-flash-preview': 'Gemini 3 Flash Preview'
    };
    return map[id] || id;
  }

  function updateAIStatusUI() {
    const hasKey = Boolean(customGeminiKey || serverHasGeminiKey);
    const activeModelName = getModelDisplayName(selectedModel);

    if (!aiToggle.checked) {
      if (aiStatusPill && aiStatusText) {
        aiStatusPill.className = 'ai-pill inactive';
        aiStatusText.textContent = 'AI Disabled (Rule-based)';
      }
      if (modelSelect) modelSelect.disabled = true;
      if (modelSelectGroup) modelSelectGroup.style.opacity = '0.5';
    } else if (hasKey) {
      if (aiStatusPill && aiStatusText) {
        aiStatusPill.className = 'ai-pill';
        aiStatusText.textContent = `${activeModelName} Active`;
      }
      if (modelSelect) modelSelect.disabled = false;
      if (modelSelectGroup) modelSelectGroup.style.opacity = '1';
    } else {
      if (aiStatusPill && aiStatusText) {
        aiStatusPill.className = 'ai-pill inactive';
        aiStatusText.textContent = 'Smart Algorithmic Mode';
      }
      if (modelSelect) modelSelect.disabled = false;
      if (modelSelectGroup) modelSelectGroup.style.opacity = '1';
    }
  }

  aiToggle.addEventListener('change', updateAIStatusUI);

  // Settings Modal Handlers
  openSettingsBtn.addEventListener('click', () => {
    if (backendUrlInput) backendUrlInput.value = window.getApiBaseUrl();
    geminiApiKeyInput.value = customGeminiKey;
    if (settingsModelSelect) settingsModelSelect.value = selectedModel;
    if (backendTestStatus) backendTestStatus.textContent = '';
    apiKeyTestStatus.textContent = '';
    settingsModal.style.display = 'flex';
  });

  closeSettingsBtn.addEventListener('click', () => {
    settingsModal.style.display = 'none';
  });

  settingsModal.addEventListener('click', (e) => {
    if (e.target === settingsModal) settingsModal.style.display = 'none';
  });

  if (testBackendBtn) {
    testBackendBtn.addEventListener('click', async () => {
      const candidateUrl = (backendUrlInput.value || '').trim().replace(/\/+$/, '');
      const testEndpoint = candidateUrl ? `${candidateUrl}/api/config` : '/api/config';

      backendTestStatus.style.color = 'var(--text-secondary)';
      backendTestStatus.textContent = 'Testing backend connection...';

      try {
        const res = await fetch(testEndpoint);
        const text = await res.text();
        let json = null;
        try { json = JSON.parse(text); } catch (_) {}

        if (res.ok && json) {
          backendTestStatus.style.color = 'var(--accent-emerald)';
          backendTestStatus.textContent = '✓ Connected to backend successfully!';
        } else if (res.status === 404) {
          backendTestStatus.style.color = 'var(--accent-rose)';
          backendTestStatus.textContent = '✗ 404 Not Found: Check backend URL path.';
        } else {
          backendTestStatus.style.color = 'var(--accent-rose)';
          backendTestStatus.textContent = `✗ Server responded with HTTP ${res.status}`;
        }
      } catch (err) {
        backendTestStatus.style.color = 'var(--accent-rose)';
        backendTestStatus.textContent = '✗ Connection failed: ' + err.message;
      }
    });
  }

  testApiKeyBtn.addEventListener('click', async () => {
    const key = geminiApiKeyInput.value.trim();
    if (!key) {
      apiKeyTestStatus.style.color = 'var(--accent-rose)';
      apiKeyTestStatus.textContent = 'Please enter an API key first.';
      return;
    }

    apiKeyTestStatus.style.color = 'var(--text-secondary)';
    apiKeyTestStatus.textContent = 'Testing connection...';

    try {
      const { data: result } = await window.safeFetch('/api/test-gemini', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key })
      });

      if (result && result.valid) {
        apiKeyTestStatus.style.color = 'var(--accent-emerald)';
        apiKeyTestStatus.textContent = '✓ Verified! Key is valid.';
      } else {
        apiKeyTestStatus.style.color = 'var(--accent-rose)';
        apiKeyTestStatus.textContent = '✗ ' + ((result && result.message) || 'Verification failed');
      }
    } catch (err) {
      apiKeyTestStatus.style.color = 'var(--accent-rose)';
      apiKeyTestStatus.textContent = '✗ ' + err.message;
    }
  });

  saveSettingsBtn.addEventListener('click', () => {
    if (backendUrlInput) {
      const newBackendUrl = backendUrlInput.value.trim();
      window.setApiBaseUrl(newBackendUrl);
    }

    customGeminiKey = geminiApiKeyInput.value.trim();
    if (settingsModelSelect) {
      selectedModel = settingsModelSelect.value;
      localStorage.setItem('slidecraft_ai_model', selectedModel);
      if (modelSelect) modelSelect.value = selectedModel;
    }
    if (customGeminiKey) {
      localStorage.setItem('slidecraft_gemini_key', customGeminiKey);
      window.showToast('Settings saved! Custom Gemini key active.', 'success');
    } else {
      localStorage.removeItem('slidecraft_gemini_key');
      window.showToast('Settings saved!', 'info');
    }
    settingsModal.style.display = 'none';
    fetchServerConfig();
    fetchAvailableModels();
    updateAIStatusUI();
  });

  // Drag and Drop Handling
  ['dragenter', 'dragover'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (files.length === 0) {
      window.showToast('Please drop PDF files only.', 'error');
      return;
    }
    addFiles(files);
  });

  browseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  dropzone.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      const files = Array.from(fileInput.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      addFiles(files);
      fileInput.value = '';
    }
  });

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function addFiles(newFiles) {
    newFiles.forEach(f => {
      if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
        selectedFiles.push(f);
      }
    });
    renderFileList();
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
  }

  function renderFileList() {
    if (selectedFiles.length === 0) {
      fileList.style.display = 'none';
      convertBtn.disabled = true;
      convertBtnText.textContent = 'Convert to PowerPoint';
      return;
    }

    fileList.style.display = 'flex';
    fileList.innerHTML = '';
    convertBtn.disabled = false;
    convertBtnText.textContent = selectedFiles.length > 1
      ? `Convert ${selectedFiles.length} PDFs to PowerPoint`
      : 'Convert to PowerPoint';

    selectedFiles.forEach((file, idx) => {
      const card = document.createElement('div');
      card.className = 'file-card';
      card.innerHTML = `
        <div class="file-info">
          <div class="file-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
          </div>
          <div class="file-details">
            <div class="file-name" title="${file.name}">${file.name}</div>
            <div class="file-meta">
              <span>${formatBytes(file.size)}</span>
              <span>•</span>
              <span>Ready to convert</span>
            </div>
          </div>
        </div>
        <div class="file-actions">
          <button type="button" class="btn-subtle btn-sm preview-btn" data-index="${idx}" title="Preview & select pages">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <span>Preview & Select</span>
          </button>
          <button type="button" class="btn-remove remove-btn" data-index="${idx}" title="Remove file">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      `;

      card.querySelector('.preview-btn').addEventListener('click', () => {
        previewManager.loadDocumentPreview(selectedFiles[idx]);
      });

      card.querySelector('.remove-btn').addEventListener('click', () => {
        removeFile(idx);
      });

      fileList.appendChild(card);
    });
  }

  // Conversion Execution
  convertBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;

    convertBtn.disabled = true;
    convertBtnText.textContent = 'Uploading & Starting...';
    resultsCard.style.display = 'none';

    const formData = new FormData();
    selectedFiles.forEach(file => {
      formData.append('files', file);
    });

    if (pageRangeInput) {
      const rangeVal = pageRangeInput.value.trim();
      if (rangeVal && rangeVal.toLowerCase() !== 'all') {
        formData.append('page_range', rangeVal);
      }
    }
    formData.append('slide_ratio', ratioSelect.value);
    formData.append('conversion_mode', conversionModeSelect ? conversionModeSelect.value : 'visual');
    formData.append('heading_font', headingFontSelect ? headingFontSelect.value : 'auto');
    formData.append('body_font', bodyFontSelect ? bodyFontSelect.value : 'auto');
    formData.append('ai_enabled', aiToggle.checked);
    formData.append('ai_model', modelSelect ? modelSelect.value : selectedModel);

    const apiKey = customGeminiKey;
    if (apiKey) {
      formData.append('gemini_api_key', apiKey);
    }

    if (previewManager && previewManager.customRegions && Object.keys(previewManager.customRegions).length > 0) {
      formData.append('custom_regions', JSON.stringify(previewManager.customRegions));
    }

    try {
      const { data: resData } = await window.safeFetch('/api/convert', {
        method: 'POST',
        body: formData
      });

      const tasks = (resData && resData.tasks) || [];
      if (tasks.length === 0) {
        throw new Error('No conversion tasks created');
      }

      // Track tasks (in sequence for batch, or single)
      runBatchTasks(tasks);

    } catch (err) {
      window.showToast(err.message, 'error');
      convertBtn.disabled = false;
      convertBtnText.textContent = 'Convert to PowerPoint';
      progressTracker.hide();
    }
  });

  const completedResults = [];

  async function runBatchTasks(tasks) {
    completedResults.length = 0;
    for (let i = 0; i < tasks.length; i++) {
      const t = tasks[i];
      await new Promise((resolve) => {
        progressTracker.onComplete = (data) => {
          completedResults.push(data);
          resolve();
        };
        progressTracker.onError = (data) => {
          window.showToast(`Error converting ${t.filename}: ${data.error || 'Failed'}`, 'error');
          resolve();
        };
        progressTracker.trackTask(t.task_id, t.filename);
      });
    }

    // All tasks in batch completed
    progressTracker.hide();
    renderResults(completedResults);
  }

  function handleConversionComplete(data) {
    window.showToast('Presentation generated successfully!', 'success');
  }

  function handleConversionError(data) {
    window.showToast(`Conversion failed: ${data.error || data.message}`, 'error');
    convertBtn.disabled = false;
    convertBtnText.textContent = 'Retry Conversion';
  }

  function renderResults(results) {
    if (results.length === 0) return;

    resultsCard.style.display = 'block';
    resultsList.innerHTML = '';
    resultsCard.scrollIntoView({ behavior: 'smooth' });

    results.forEach(res => {
      const item = document.createElement('div');
      item.className = 'result-item';

      const baseStem = res.filename.replace(/\.pdf$/i, '');
      const pptxName = `${baseStem}.pptx`;

      item.innerHTML = `
        <div class="result-item-info">
          <div class="pptx-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <text x="7" y="16" font-size="6" font-weight="bold" fill="currentColor">PPT</text>
            </svg>
          </div>
          <div>
            <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-primary);">${pptxName}</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 2px;">
              ${res.total_pages ? `${res.total_pages} slides` : 'All slides'} • Editable Slide Picture Elements
            </div>
          </div>
        </div>
        <a href="${window.getApiUrl(res.download_url)}" class="btn-download" download="${pptxName}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Download PPTX</span>
        </a>
      `;

      resultsList.appendChild(item);
    });

    convertBtn.disabled = false;
    convertBtnText.textContent = 'Convert to PowerPoint';
  }

  convertAnotherBtn.addEventListener('click', () => {
    resultsCard.style.display = 'none';
    selectedFiles = [];
    renderFileList();
    if (pageRangeInput) {
      pageRangeInput.value = '';
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
});
