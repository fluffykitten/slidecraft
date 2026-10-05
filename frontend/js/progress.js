/**
 * Progress Tracker
 * Manages Server-Sent Events (SSE) stream and live UI animations.
 */

class ProgressTracker {
  constructor(options = {}) {
    this.progressCard = document.getElementById('progressCard');
    this.progressBar = document.getElementById('progressBar');
    this.progressPct = document.getElementById('progressPct');
    this.progressTitle = document.getElementById('progressTitle');
    this.progressStatusText = document.getElementById('progressStatusText');

    this.step1 = document.getElementById('step1');
    this.step2 = document.getElementById('step2');
    this.step3 = document.getElementById('step3');
    this.step4 = document.getElementById('step4');

    this.eventSource = null;
    this.onComplete = options.onComplete || (() => {});
    this.onError = options.onError || (() => {});
  }

  show(filename = '') {
    this.progressCard.style.display = 'block';
    this.progressTitle.textContent = filename ? `Converting: ${filename}` : 'Converting Document...';
    this.progressBar.style.width = '0%';
    this.progressPct.textContent = '0%';
    this.resetSteps();
    this.progressCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  hide() {
    this.progressCard.style.display = 'none';
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  resetSteps() {
    [this.step1, this.step2, this.step3, this.step4].forEach((s) => {
      s.className = 'step-node step-item';
    });
  }

  updateSteps(status) {
    this.resetSteps();
    if (status === 'queued') {
      this.step1.classList.add('active');
    } else if (status === 'extracting') {
      this.step1.classList.add('active');
    } else if (status === 'analyzing') {
      this.step1.classList.add('completed');
      this.step2.classList.add('active');
    } else if (status === 'building') {
      this.step1.classList.add('completed');
      this.step2.classList.add('completed');
      this.step3.classList.add('active');
    } else if (status === 'completed') {
      this.step1.classList.add('completed');
      this.step2.classList.add('completed');
      this.step3.classList.add('completed');
      this.step4.classList.add('completed');
    }
  }

  trackTask(taskId, filename) {
    this.show(filename);

    if (this.eventSource) {
      this.eventSource.close();
    }

    const streamUrl = `/api/tasks/${taskId}/stream`;
    this.eventSource = new EventSource(streamUrl);

    this.eventSource.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        this.renderState(data);

        if (data.status === 'completed') {
          this.eventSource.close();
          this.eventSource = null;
          setTimeout(() => {
            this.onComplete(data);
          }, 600);
        } else if (data.status === 'failed') {
          this.eventSource.close();
          this.eventSource = null;
          this.onError(data);
        }
      } catch (err) {
        console.error('SSE JSON parse error:', err);
      }
    });

    this.eventSource.onerror = (err) => {
      console.warn('SSE stream notice, checking status endpoint fallback...', err);
      // Fallback poll
      this.pollTaskStatus(taskId);
    };
  }

  renderState(data) {
    const pct = Math.max(2, Math.min(100, Math.round(data.progress || 0)));
    this.progressBar.style.width = `${pct}%`;
    this.progressPct.textContent = `${pct}%`;

    if (data.message) {
      this.progressStatusText.textContent = data.message;
    }

    this.updateSteps(data.status);
  }

  async pollTaskStatus(taskId) {
    try {
      const res = await fetch(`/api/tasks/${taskId}/status`);
      if (res.ok) {
        const data = await res.json();
        this.renderState(data);
        if (data.status === 'completed') {
          this.onComplete(data);
        } else if (data.status === 'failed') {
          this.onError(data);
        } else {
          // Poll again in 1 second if still in progress
          setTimeout(() => this.pollTaskStatus(taskId), 1000);
        }
      }
    } catch (e) {
      console.error('Polling error:', e);
    }
  }
}

window.ProgressTracker = ProgressTracker;
