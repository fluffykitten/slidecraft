/**
 * Preview Manager
 * Handles page thumbnail generation and interactive visual page range selection.
 */

class PreviewManager {
  constructor() {
    this.modal = document.getElementById('previewModal');
    this.grid = document.getElementById('previewGrid');
    this.title = document.getElementById('previewModalTitle');
    this.subtitle = document.getElementById('previewModalSubtitle');
    this.closeBtn = document.getElementById('closePreviewBtn');
    this.selectAllBtn = document.getElementById('selectAllPagesBtn');
    this.deselectAllBtn = document.getElementById('deselectAllPagesBtn');
    this.applyBtn = document.getElementById('applyPageSelectionBtn');
    this.countLabel = document.getElementById('selectedPagesCount');
    this.pageRangeInput = document.getElementById('pageRangeInput');

    this.currentFile = null;
    this.totalPages = 0;
    this.selectedPages = new Set();
    this.customRegions = {}; // page_num -> list of custom elements
    this.regionEditor = new window.RegionEditor();

    this.initEvents();
  }

  initEvents() {
    this.closeBtn.addEventListener('click', () => this.hide());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.hide();
    });

    this.selectAllBtn.addEventListener('click', () => {
      for (let i = 1; i <= this.totalPages; i++) {
        this.selectedPages.add(i);
      }
      this.updateSelectionUI();
    });

    this.deselectAllBtn.addEventListener('click', () => {
      this.selectedPages.clear();
      this.updateSelectionUI();
    });

    this.applyBtn.addEventListener('click', () => {
      const rangeStr = this.computeRangeString();
      if (this.pageRangeInput) {
        this.pageRangeInput.value = rangeStr;
      }
      this.hide();
      if (window.showToast) {
        window.showToast(`Selected ${this.selectedPages.size} pages (${rangeStr})`, 'success');
      }
    });
  }

  show() {
    this.modal.style.display = 'flex';
  }

  hide() {
    this.modal.style.display = 'none';
  }

  async loadDocumentPreview(file) {
    this.currentFile = file;
    this.title.textContent = `Select Pages: ${file.name}`;
    this.subtitle.textContent = 'Generating real-time page thumbnails...';
    this.grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-secondary);"><div class="spinner" style="margin: 0 auto 16px;"></div>Rendering slide previews...</div>';
    this.show();

    try {
      const formData = new FormData();
      formData.append('file', file);

      const { data } = await window.safeFetch('/api/preview', {
        method: 'POST',
        body: formData
      });
      this.totalPages = data.total_pages;
      this.subtitle.textContent = `${this.totalPages} pages detected. Click any slide to include or exclude.`;

      // Initialize all pages as selected by default
      this.selectedPages.clear();
      for (let i = 1; i <= this.totalPages; i++) {
        this.selectedPages.add(i);
      }

      this.renderPages(data.pages);
    } catch (err) {
      this.grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--accent-rose);">Error loading preview: ${err.message}</div>`;
      if (window.showToast) window.showToast(err.message, 'error');
    }
  }

  renderPages(pages) {
    this.grid.innerHTML = '';
    pages.forEach((p) => {
      const card = document.createElement('div');
      card.className = 'page-thumb-card selected';
      card.dataset.pageNum = p.page_num;

      const hasCustom = this.customRegions[p.page_num] && this.customRegions[p.page_num].length > 0;
      const customBadgeHtml = hasCustom
        ? `<div class="custom-region-indicator" id="customBadge_${p.page_num}">${this.customRegions[p.page_num].length} Custom Regions</div>`
        : `<div class="custom-region-indicator" id="customBadge_${p.page_num}" style="display: none;"></div>`;

      card.innerHTML = `
        <img class="page-thumb-img" src="${p.thumbnail_base64}" alt="Slide ${p.page_num}">
        <div class="page-badge-check">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <div class="page-label">Page ${p.page_num}</div>
        ${customBadgeHtml}
        <button type="button" class="btn-inspect-slide" data-page="${p.page_num}" title="Visually inspect and tune text vs image elements">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <span>Inspect Regions</span>
        </button>
      `;

      card.addEventListener('click', () => {
        const num = p.page_num;
        if (this.selectedPages.has(num)) {
          this.selectedPages.delete(num);
          card.classList.remove('selected');
        } else {
          this.selectedPages.add(num);
          card.classList.add('selected');
        }
        this.updateSelectionUI();
      });

      const inspectBtn = card.querySelector('.btn-inspect-slide');
      inspectBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.regionEditor.open(
          this.currentFile,
          p.page_num,
          this.customRegions[p.page_num] || null,
          p.thumbnail_base64,
          (pageNum, regions) => {
            this.customRegions[pageNum] = regions;
            this.updateCustomRegionBadges();
          }
        );
      });

      this.grid.appendChild(card);
    });

    this.updateSelectionUI();
  }

  updateCustomRegionBadges() {
    Object.keys(this.customRegions).forEach((pageNumStr) => {
      const pageNum = parseInt(pageNumStr, 10);
      const regions = this.customRegions[pageNum];
      const badge = document.getElementById(`customBadge_${pageNum}`);
      if (badge) {
        if (regions && regions.length > 0) {
          badge.textContent = `${regions.length} Custom Regions`;
          badge.style.display = 'inline-flex';
        } else {
          badge.style.display = 'none';
        }
      }
    });
  }

  updateSelectionUI() {
    const cards = this.grid.querySelectorAll('.page-thumb-card');
    cards.forEach((card) => {
      const num = parseInt(card.dataset.pageNum, 10);
      if (this.selectedPages.has(num)) {
        card.classList.add('selected');
      } else {
        card.classList.remove('selected');
      }
    });

    const count = this.selectedPages.size;
    this.countLabel.textContent = `${count} of ${this.totalPages} pages selected`;
    this.applyBtn.disabled = count === 0;
  }

  computeRangeString() {
    if (this.selectedPages.size === 0) return '';
    if (this.selectedPages.size === this.totalPages) return 'All';

    const sorted = Array.from(this.selectedPages).sort((a, b) => a - b);
    const ranges = [];
    let start = sorted[0];
    let end = start;

    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i] === end + 1) {
        end = sorted[i];
      } else {
        ranges.push(start === end ? `${start}` : `${start}-${end}`);
        start = sorted[i];
        end = start;
      }
    }
    ranges.push(start === end ? `${start}` : `${start}-${end}`);
    return ranges.join(', ');
  }
}

window.PreviewManager = PreviewManager;
