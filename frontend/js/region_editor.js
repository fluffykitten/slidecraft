/**
 * Interactive Slide Region Inspector & Editor
 * Allows users to visually view, adjust, toggle, or draw custom regions for any slide.
 */

class RegionEditor {
  constructor() {
    this.modal = document.getElementById('regionEditorModal');
    this.title = document.getElementById('regionEditorTitle');
    this.pageBadge = document.getElementById('regionEditorPageBadge');
    this.subtitle = document.getElementById('regionEditorSubtitle');
    this.closeBtn = document.getElementById('closeRegionEditorBtn');
    this.autoDetectBtn = document.getElementById('editorAutoDetectBtn');
    this.autoDetectText = document.getElementById('editorAutoDetectText');
    this.addLayerBtn = document.getElementById('editorAddLayerBtn');
    this.addTextBtn = document.getElementById('editorAddTextBtn');
    this.addPicBtn = document.getElementById('editorAddPicBtn');
    this.addTableBtn = document.getElementById('editorAddTableBtn');
    this.deleteBoxBtn = document.getElementById('editorDeleteBoxBtn');
    this.saveBtn = document.getElementById('editorSaveBtn');
    this.img = document.getElementById('regionEditorImg');
    this.overlay = document.getElementById('regionOverlayLayer');
    this.canvasContainer = document.getElementById('regionCanvasContainer');
    this.countText = document.getElementById('regionCountText');
    this.countGraphic = document.getElementById('regionCountGraphic');
    this.countTable = document.getElementById('regionCountTable');

    this.currentFile = null;
    this.currentPageNum = 1;
    this.conversionMode = 'visual';
    this.onSaveCallback = null;
    this.regions = []; // [{ id, name, type: "text"|"graphic"|"table", box_2d: [ymin, xmin, ymax, xmax], rows?: [] }]
    this.selectedRegionId = null;
    this.drawMode = 'graphic'; // 'text' | 'graphic' | 'table'

    this.dragState = null; // { type: 'move'|'resize'|'draw', ... }

    this.initEvents();
  }

  initEvents() {
    this.closeBtn.addEventListener('click', () => this.hide());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.hide();
    });

    this.autoDetectBtn.addEventListener('click', () => this.runAutoDetect());

    if (this.addLayerBtn) {
      this.addLayerBtn.addEventListener('click', () => {
        this.drawMode = 'graphic';
        this.highlightDrawMode();
        if (window.showToast) window.showToast('Click & drag on the slide to draw an Animatable Picture Layer', 'info');
      });
    }

    this.addTextBtn.addEventListener('click', () => {
      this.drawMode = 'text';
      this.highlightDrawMode();
      if (window.showToast) window.showToast('Click & drag on the slide to draw a Text Box', 'info');
    });

    this.addPicBtn.addEventListener('click', () => {
      this.drawMode = 'graphic';
      this.highlightDrawMode();
      if (window.showToast) window.showToast('Click & drag on the slide to draw a Picture Shape', 'info');
    });

    if (this.addTableBtn) {
      this.addTableBtn.addEventListener('click', () => {
        this.drawMode = 'table';
        this.highlightDrawMode();
        if (window.showToast) window.showToast('Click & drag on the slide to draw a Data Table', 'info');
      });
    }

    this.deleteBoxBtn.addEventListener('click', () => {
      if (this.selectedRegionId) {
        this.removeRegion(this.selectedRegionId);
      }
    });

    this.saveBtn.addEventListener('click', () => {
      if (this.onSaveCallback) {
        this.onSaveCallback(this.currentPageNum, this.getRegions());
      }
      this.hide();
      if (window.showToast) {
        const label = this.conversionMode === 'visual' ? 'picture layers' : 'custom regions';
        window.showToast(`Saved ${this.regions.length} ${label} for Slide ${this.currentPageNum}!`, 'success');
      }
    });

    // Keyboard shortcuts (Delete / Backspace)
    window.addEventListener('keydown', (e) => {
      if (this.modal.style.display !== 'none' && (e.key === 'Delete' || e.key === 'Backspace')) {
        if (this.selectedRegionId && document.activeElement.tagName !== 'INPUT') {
          e.preventDefault();
          this.removeRegion(this.selectedRegionId);
        }
      }
    });

    // Overlay Mouse Events for Drawing and Handling
    this.overlay.addEventListener('mousedown', (e) => this.handleOverlayMouseDown(e));
    window.addEventListener('mousemove', (e) => this.handleWindowMouseMove(e));
    window.addEventListener('mouseup', (e) => this.handleWindowMouseUp(e));
  }

  highlightDrawMode() {
    const isVisual = this.conversionMode === 'visual';
    if (this.addLayerBtn) {
      this.addLayerBtn.style.background = isVisual && this.drawMode === 'graphic' ? 'rgba(16, 185, 129, 0.25)' : 'transparent';
      this.addLayerBtn.style.borderColor = isVisual && this.drawMode === 'graphic' ? '#10b981' : 'var(--border-medium)';
    }
    this.addTextBtn.style.background = this.drawMode === 'text' ? 'var(--accent-blue-subtle)' : 'transparent';
    this.addTextBtn.style.borderColor = this.drawMode === 'text' ? 'var(--accent-blue)' : 'var(--border-medium)';
    this.addPicBtn.style.background = !isVisual && this.drawMode === 'graphic' ? 'var(--accent-emerald-subtle)' : 'transparent';
    this.addPicBtn.style.borderColor = !isVisual && this.drawMode === 'graphic' ? 'var(--accent-emerald)' : 'var(--border-medium)';
    if (this.addTableBtn) {
      this.addTableBtn.style.background = this.drawMode === 'table' ? 'rgba(139, 92, 246, 0.15)' : 'transparent';
      this.addTableBtn.style.borderColor = this.drawMode === 'table' ? '#8b5cf6' : 'var(--border-medium)';
    }
  }

  show() {
    this.modal.style.display = 'flex';
  }

  hide() {
    this.modal.style.display = 'none';
  }

  open(file, pageNum, existingRegions = null, initialImageSrc = null, onSave = null, conversionMode = 'visual') {
    this.currentFile = file;
    this.currentPageNum = pageNum;
    this.onSaveCallback = onSave;
    this.conversionMode = conversionMode || (document.getElementById('conversionModeSelect')?.value || 'visual');
    this.selectedRegionId = null;

    this.pageBadge.textContent = `Slide ${pageNum}`;
    this.regions = [];

    const isVisual = this.conversionMode === 'visual';
    const titleSpan = this.title.querySelector('span:first-child');
    if (titleSpan) {
      titleSpan.textContent = isVisual ? 'Visual Layer & Animation Inspector' : 'Slide Region Inspector';
    }
    if (this.subtitle) {
      this.subtitle.textContent = isVisual
        ? 'Customize picture layers for PowerPoint animations. Drag handles to resize, or click badge to rename.'
        : 'Click badge to toggle Text / Graphic. Drag handles to resize. Drag canvas to draw new region.';
    }
    if (this.addLayerBtn) this.addLayerBtn.style.display = isVisual ? 'inline-flex' : 'none';
    if (this.addTextBtn) this.addTextBtn.style.display = isVisual ? 'none' : 'inline-flex';
    if (this.addPicBtn) this.addPicBtn.style.display = isVisual ? 'none' : 'inline-flex';
    if (this.addTableBtn) this.addTableBtn.style.display = isVisual ? 'none' : 'inline-flex';
    this.drawMode = isVisual ? 'graphic' : 'text';

    if (initialImageSrc) {
      this.img.src = initialImageSrc;
    }

    this.show();
    this.highlightDrawMode();

    if (existingRegions && existingRegions.length > 0) {
      // Clone existing regions
      this.regions = JSON.parse(JSON.stringify(existingRegions));
      this.renderRegions();
    } else {
      // Auto-detect automatically on first open for frictionless UX!
      this.runAutoDetect();
    }
  }

  async runAutoDetect() {
    if (!this.currentFile) return;

    this.autoDetectBtn.disabled = true;
    this.autoDetectText.textContent = 'Detecting AI Elements...';

    const formData = new FormData();
    formData.append('file', this.currentFile);
    formData.append('page_num', this.currentPageNum);
    formData.append('detect_ai', 'true');
    formData.append('conversion_mode', this.conversionMode || 'visual');

    // Retrieve active AI model from localStorage or settings
    const activeModel = localStorage.getItem('slidecraft_ai_model') || 'gemini-3.5-flash-lite';
    formData.append('ai_model', activeModel);

    const customKey = localStorage.getItem('slidecraft_gemini_key');
    if (customKey) {
      formData.append('gemini_api_key', customKey);
    }

    try {
      const { data } = await window.safeFetch('/api/detect-slide-regions', {
        method: 'POST',
        body: formData
      });
      if (data.image_base64) {
        this.img.src = data.image_base64;
      }

      // Convert detected elements into local region objects
      const detectedElements = data.elements || [];
      const isVisual = this.conversionMode === 'visual';
      this.regions = detectedElements.map((el, i) => {
        let elType = 'graphic';
        if (!isVisual) {
          if (el.type === 'table') {
            elType = 'table';
          } else if (el.type === 'text' || el.text_primary) {
            elType = 'text';
          }
        }
        return {
          id: `reg_${Date.now()}_${i}`,
          name: el.name || (isVisual ? `Layer ${i + 1}` : `Element ${i + 1}`),
          type: elType,
          box_2d: el.box_2d || [0, 0, 1000, 1000],
          rows: el.rows || []
        };
      });

      this.renderRegions();
      if (window.showToast) {
        const desc = isVisual ? `${this.regions.length} animation picture layers` : `${this.regions.length} visual elements`;
        window.showToast(`Auto-detected ${desc}`, 'success');
      }
    } catch (err) {
      console.warn('Auto-detect error:', err);
      if (window.showToast) window.showToast(`Auto-detect note: ${err.message}`, 'info');
      this.renderRegions();
    } finally {
      this.autoDetectBtn.disabled = false;
      this.autoDetectText.textContent = 'Auto-Detect';
    }
  }

  renderRegions() {
    this.overlay.innerHTML = '';
    let textCount = 0;
    let graphicCount = 0;
    let tableCount = 0;
    const isVisual = this.conversionMode === 'visual';

    this.regions.forEach((reg, idx) => {
      if (reg.type === 'text') textCount++;
      else if (reg.type === 'table') tableCount++;
      else graphicCount++;

      const [ymin, xmin, ymax, xmax] = reg.box_2d;
      const topPct = (ymin / 1000) * 100;
      const leftPct = (xmin / 1000) * 100;
      const widthPct = Math.max(1, ((xmax - xmin) / 1000) * 100);
      const heightPct = Math.max(1, ((ymax - ymin) / 1000) * 100);

      const box = document.createElement('div');
      const boxType = isVisual ? 'graphic' : reg.type;
      box.className = `region-box type-${boxType} ${reg.id === this.selectedRegionId ? 'selected' : ''}`;
      box.dataset.id = reg.id;
      box.style.top = `${topPct}%`;
      box.style.left = `${leftPct}%`;
      box.style.width = `${widthPct}%`;
      box.style.height = `${heightPct}%`;

      // Type Badge Pill
      const badge = document.createElement('div');
      badge.className = 'region-badge';

      if (isVisual) {
        badge.style.background = '#10b981';
        badge.style.color = '#ffffff';
        badge.style.fontWeight = '600';
        badge.style.cursor = 'pointer';
        badge.innerHTML = `<span>🏷️ ${reg.name || ('Layer ' + (idx + 1))} ✏️</span>`;
        badge.title = 'Click to rename this picture layer (matches PowerPoint Animation & Selection Pane name)';
        badge.addEventListener('mousedown', (e) => e.stopPropagation());
        badge.addEventListener('click', (e) => {
          e.stopPropagation();
          const currentTitle = reg.name || `Layer ${idx + 1}`;
          const newName = prompt('Enter layer name for PowerPoint animation sequence (e.g. 1_Judul, 2_Diagram, 3_Langkah_1):', currentTitle);
          if (newName !== null && newName.trim()) {
            reg.name = newName.trim();
            this.renderRegions();
          }
        });
      } else {
        const labelText = reg.type === 'text' ? 'TEXT' : (reg.type === 'table' ? 'TABLE' : 'GRAPHIC');
        badge.innerHTML = `<span>${labelText}</span>`;
        badge.title = 'Click to cycle: Text Box → Graphic Shape → Data Table';
        badge.addEventListener('mousedown', (e) => e.stopPropagation());
        badge.addEventListener('click', (e) => {
          e.stopPropagation();
          this.toggleRegionType(reg.id);
        });
      }
      box.appendChild(badge);

      // Delete Button (x)
      const delBtn = document.createElement('div');
      delBtn.className = 'region-del-btn';
      delBtn.innerHTML = '✕';
      delBtn.title = 'Delete layer';
      delBtn.addEventListener('mousedown', (e) => e.stopPropagation());
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.removeRegion(reg.id);
      });
      box.appendChild(delBtn);

      // 8 Resize Handles
      ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach((hName) => {
        const handle = document.createElement('div');
        handle.className = `region-handle ${hName}`;
        handle.dataset.handle = hName;
        handle.dataset.id = reg.id;
        box.appendChild(handle);
      });

      this.overlay.appendChild(box);
    });

    if (isVisual) {
      if (this.countText) this.countText.style.display = 'none';
      if (this.countTable) this.countTable.style.display = 'none';
      if (this.countGraphic) {
        this.countGraphic.style.display = 'inline-flex';
        this.countGraphic.textContent = `${this.regions.length} Animatable Picture Layers`;
      }
    } else {
      if (this.countText) {
        this.countText.style.display = 'inline-flex';
        this.countText.textContent = `${textCount} Text Boxes`;
      }
      if (this.countGraphic) {
        this.countGraphic.style.display = 'inline-flex';
        this.countGraphic.textContent = `${graphicCount} Graphic Shapes`;
      }
      if (this.countTable) {
        this.countTable.style.display = 'inline-flex';
        this.countTable.textContent = `${tableCount} Tables`;
      }
    }
  }

  selectRegion(id) {
    this.selectedRegionId = id;
    this.renderRegions();
  }

  toggleRegionType(id) {
    const reg = this.regions.find((r) => r.id === id);
    if (reg) {
      if (reg.type === 'text') reg.type = 'graphic';
      else if (reg.type === 'graphic') reg.type = 'table';
      else reg.type = 'text';

      this.renderRegions();
      const typeNames = { text: 'Editable Text Box', graphic: 'Picture Shape', table: 'Data Table' };
      if (window.showToast) {
        window.showToast(`Changed to ${typeNames[reg.type]}`, 'info');
      }
    }
  }

  removeRegion(id) {
    this.regions = this.regions.filter((r) => r.id !== id);
    if (this.selectedRegionId === id) this.selectedRegionId = null;
    this.renderRegions();
  }

  getRegions() {
    return this.regions.map((r) => ({
      name: r.name,
      type: r.type,
      text_primary: r.type === 'text',
      box_2d: r.box_2d,
      rows: r.rows || []
    }));
  }

  // -------------------------------------------------------------
  // Mouse Drag, Resize, and Draw Coordinates
  // -------------------------------------------------------------
  handleOverlayMouseDown(e) {
    const rect = this.overlay.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const handleElem = e.target.closest('.region-handle');
    if (handleElem) {
      e.stopPropagation();
      const regionId = handleElem.dataset.id;
      const reg = this.regions.find((r) => r.id === regionId);
      if (!reg) return;

      this.selectRegion(regionId);
      this.dragState = {
        type: 'resize',
        handle: handleElem.dataset.handle,
        region: reg,
        startX: mouseX,
        startY: mouseY,
        startBox: [...reg.box_2d],
        rectWidth: rect.width,
        rectHeight: rect.height
      };
      return;
    }

    const boxElem = e.target.closest('.region-box');
    if (boxElem) {
      e.stopPropagation();
      const regionId = boxElem.dataset.id;
      const reg = this.regions.find((r) => r.id === regionId);
      if (!reg) return;

      this.selectRegion(regionId);
      this.dragState = {
        type: 'move',
        region: reg,
        startX: mouseX,
        startY: mouseY,
        startBox: [...reg.box_2d],
        rectWidth: rect.width,
        rectHeight: rect.height
      };
      return;
    }

    // Clicked empty canvas: start drawing a new region box!
    this.selectedRegionId = null;
    this.renderRegions();

    const startXNorm = Math.max(0, Math.min(1000, (mouseX / rect.width) * 1000));
    const startYNorm = Math.max(0, Math.min(1000, (mouseY / rect.height) * 1000));

    this.dragState = {
      type: 'draw',
      startXNorm,
      startYNorm,
      currentXNorm: startXNorm,
      currentYNorm: startYNorm,
      rectWidth: rect.width,
      rectHeight: rect.height
    };

    this.createGhostBox(mouseX, mouseY);
  }

  createGhostBox(x, y) {
    this.removeGhostBox();
    const ghost = document.createElement('div');
    ghost.id = 'regionGhostBox';
    ghost.className = 'region-drawing-box';
    ghost.style.left = `${x}px`;
    ghost.style.top = `${y}px`;
    ghost.style.width = '0px';
    ghost.style.height = '0px';
    this.overlay.appendChild(ghost);
  }

  removeGhostBox() {
    const existing = document.getElementById('regionGhostBox');
    if (existing) existing.remove();
  }

  handleWindowMouseMove(e) {
    if (!this.dragState) return;

    const rect = this.overlay.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    if (this.dragState.type === 'move') {
      const dxNorm = ((mouseX - this.dragState.startX) / this.dragState.rectWidth) * 1000;
      const dyNorm = ((mouseY - this.dragState.startY) / this.dragState.rectHeight) * 1000;

      const [y0, x0, y1, x1] = this.dragState.startBox;
      const boxW = x1 - x0;
      const boxH = y1 - y0;

      let newX0 = Math.max(0, Math.min(1000 - boxW, x0 + dxNorm));
      let newY0 = Math.max(0, Math.min(1000 - boxH, y0 + dyNorm));

      this.dragState.region.box_2d = [
        Math.round(newY0),
        Math.round(newX0),
        Math.round(newY0 + boxH),
        Math.round(newX0 + boxW)
      ];
      this.updateBoxDOM(this.dragState.region);
    } else if (this.dragState.type === 'resize') {
      const dxNorm = ((mouseX - this.dragState.startX) / this.dragState.rectWidth) * 1000;
      const dyNorm = ((mouseY - this.dragState.startY) / this.dragState.rectHeight) * 1000;

      let [y0, x0, y1, x1] = this.dragState.startBox;
      const h = this.dragState.handle;

      if (h.includes('w')) x0 = Math.max(0, Math.min(x1 - 20, x0 + dxNorm));
      if (h.includes('e')) x1 = Math.min(1000, Math.max(x0 + 20, x1 + dxNorm));
      if (h.includes('n')) y0 = Math.max(0, Math.min(y1 - 20, y0 + dyNorm));
      if (h.includes('s')) y1 = Math.min(1000, Math.max(y0 + 20, y1 + dyNorm));

      this.dragState.region.box_2d = [
        Math.round(y0),
        Math.round(x0),
        Math.round(y1),
        Math.round(x1)
      ];
      this.updateBoxDOM(this.dragState.region);
    } else if (this.dragState.type === 'draw') {
      const curXNorm = Math.max(0, Math.min(1000, (mouseX / this.dragState.rectWidth) * 1000));
      const curYNorm = Math.max(0, Math.min(1000, (mouseY / this.dragState.rectHeight) * 1000));

      this.dragState.currentXNorm = curXNorm;
      this.dragState.currentYNorm = curYNorm;

      const ghost = document.getElementById('regionGhostBox');
      if (ghost) {
        const xMinNorm = Math.min(this.dragState.startXNorm, curXNorm);
        const yMinNorm = Math.min(this.dragState.startYNorm, curYNorm);
        const xMaxNorm = Math.max(this.dragState.startXNorm, curXNorm);
        const yMaxNorm = Math.max(this.dragState.startYNorm, curYNorm);

        ghost.style.left = `${(xMinNorm / 1000) * 100}%`;
        ghost.style.top = `${(yMinNorm / 1000) * 100}%`;
        ghost.style.width = `${((xMaxNorm - xMinNorm) / 1000) * 100}%`;
        ghost.style.height = `${((yMaxNorm - yMinNorm) / 1000) * 100}%`;
      }
    }
  }

  updateBoxDOM(reg) {
    const box = this.overlay.querySelector(`.region-box[data-id="${reg.id}"]`);
    if (box) {
      const [ymin, xmin, ymax, xmax] = reg.box_2d;
      box.style.top = `${(ymin / 1000) * 100}%`;
      box.style.left = `${(xmin / 1000) * 100}%`;
      box.style.width = `${((xmax - xmin) / 1000) * 100}%`;
      box.style.height = `${((ymax - ymin) / 1000) * 100}%`;
    }
  }

  handleWindowMouseUp(e) {
    if (!this.dragState) return;

    if (this.dragState.type === 'draw') {
      this.removeGhostBox();
      const xMinNorm = Math.min(this.dragState.startXNorm, this.dragState.currentXNorm);
      const yMinNorm = Math.min(this.dragState.startYNorm, this.dragState.currentYNorm);
      const xMaxNorm = Math.max(this.dragState.startXNorm, this.dragState.currentXNorm);
      const yMaxNorm = Math.max(this.dragState.startYNorm, this.dragState.currentYNorm);

      // Only add if box has a minimum size (at least 15x15 normalized points)
      if ((xMaxNorm - xMinNorm) > 15 && (yMaxNorm - yMinNorm) > 15) {
        const isVisual = this.conversionMode === 'visual';
        const defaultNames = { text: 'Text Box', graphic: 'Picture Shape', table: 'Data Table' };
        const layerNum = this.regions.length + 1;
        const newReg = {
          id: `reg_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
          name: isVisual ? `Layer ${layerNum}` : (defaultNames[this.drawMode] || 'Element'),
          type: isVisual ? 'graphic' : this.drawMode,
          box_2d: [
            Math.round(yMinNorm),
            Math.round(xMinNorm),
            Math.round(yMaxNorm),
            Math.round(xMaxNorm)
          ]
        };
        this.regions.push(newReg);
        this.selectRegion(newReg.id);
      }
    }

    this.dragState = null;
  }
}

window.RegionEditor = RegionEditor;
