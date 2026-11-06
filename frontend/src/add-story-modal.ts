/**
 * Add Story modal — form only. Submits a spec and hands off tracking to the board panel.
 * openSpecReviewModal handles the review / amend / convert flow for a completed spec.
 */

import { marked } from 'marked';
import { apiGet, apiPost, apiPut } from './api.js';

interface SpecGenerationOut {
  id: number;
  project: string;
  description: string;
  spec_path: string | null;
  spec_content: string | null;
  status: string;
  step: string | null;
  imported_count: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

function escHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function makeOverlay(): HTMLElement {
  document.querySelector('.add-story-overlay')?.remove();
  const overlay = document.createElement('div');
  overlay.className = 'add-story-overlay';
  document.body.appendChild(overlay);
  return overlay;
}

// --- Form modal (submit → close, let panel track progress) ---

export function openAddStoryModal(options: {
  defaultProject: string;
  projects: string[];
  onSpecSubmitted?: () => void;
}): void {
  const { defaultProject, projects, onSpecSubmitted } = options;
  const overlay = makeOverlay();

  function close(): void {
    overlay.remove();
  }

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  overlay.innerHTML = `
    <div class="add-story-modal">
      <div class="add-story-header">
        <h2 class="add-story-title">Add Story</h2>
        <button class="add-story-close" aria-label="Close">&times;</button>
      </div>
      <div class="add-story-body">
        <div class="add-story-form">
          <label class="add-story-label" for="as-project">Project</label>
          <input class="add-story-input" id="as-project" type="text" list="as-project-list"
            value="${escHtml(defaultProject)}" placeholder="Project name (required)"
            ${defaultProject ? 'readonly' : ''}>
          <datalist id="as-project-list">
            ${projects.map((p) => `<option value="${escHtml(p)}">`).join('')}
          </datalist>

          <div class="add-story-mode-toggle">
            <button class="as-mode-btn as-mode-btn--active" id="as-mode-describe">Describe Feature</button>
            <button class="as-mode-btn" id="as-mode-prd">Use Existing PRD</button>
          </div>

          <div id="as-describe-section">
            <label class="add-story-label" for="as-desc">Feature / Requirement</label>
            <textarea class="add-story-textarea" id="as-desc"
              placeholder="Describe the feature or requirement…" rows="6"></textarea>
          </div>

          <div id="as-prd-section" hidden>
            <label class="add-story-label" for="as-prd-path">Spec File Path</label>
            <input class="add-story-input" id="as-prd-path" type="text"
              placeholder="~/Projects/my-project/tasks/spec.md" />
          </div>

          <p class="add-story-msg" id="as-msg"></p>

          <div class="add-story-actions">
            <button class="dash-btn dash-btn-primary" id="as-submit">Generate Specification</button>
            <button class="dash-btn" id="as-cancel">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  `;

  overlay.querySelector('.add-story-close')!.addEventListener('click', close);
  overlay.querySelector('#as-cancel')!.addEventListener('click', close);

  // Mode toggle
  let prdMode = false;
  const describeBtn = overlay.querySelector<HTMLButtonElement>('#as-mode-describe')!;
  const prdBtn = overlay.querySelector<HTMLButtonElement>('#as-mode-prd')!;
  const describeSection = overlay.querySelector<HTMLElement>('#as-describe-section')!;
  const prdSection = overlay.querySelector<HTMLElement>('#as-prd-section')!;
  const submitBtn = overlay.querySelector<HTMLButtonElement>('#as-submit')!;

  describeBtn.addEventListener('click', () => {
    prdMode = false;
    describeBtn.classList.add('as-mode-btn--active');
    prdBtn.classList.remove('as-mode-btn--active');
    describeSection.hidden = false;
    prdSection.hidden = true;
    submitBtn.textContent = 'Generate Specification';
  });

  prdBtn.addEventListener('click', () => {
    prdMode = true;
    prdBtn.classList.add('as-mode-btn--active');
    describeBtn.classList.remove('as-mode-btn--active');
    prdSection.hidden = false;
    describeSection.hidden = true;
    submitBtn.textContent = 'Load Specification';
  });

  submitBtn.addEventListener('click', async () => {
    const project = (overlay.querySelector<HTMLInputElement>('#as-project')!).value.trim();
    const msg = overlay.querySelector<HTMLElement>('#as-msg')!;

    if (!project) {
      msg.textContent = 'Project is required.';
      msg.className = 'add-story-msg add-story-msg--error';
      return;
    }

    let body: Record<string, string>;

    if (prdMode) {
      const prdPath = (overlay.querySelector<HTMLInputElement>('#as-prd-path')!).value.trim();
      if (!prdPath) {
        msg.textContent = 'PRD path is required.';
        msg.className = 'add-story-msg add-story-msg--error';
        return;
      }
      body = { project, prd_path: prdPath };
    } else {
      const desc = (overlay.querySelector<HTMLTextAreaElement>('#as-desc')!).value.trim();
      if (!desc) {
        msg.textContent = 'Feature description is required.';
        msg.className = 'add-story-msg add-story-msg--error';
        return;
      }
      body = { project, description: desc };
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting…';

    const resp = await apiPost<SpecGenerationOut>('/specs', body);
    if (!resp.ok) {
      const detail = (resp.data as { detail?: string }).detail;
      msg.textContent = detail ?? 'Failed to submit. Please try again.';
      msg.className = 'add-story-msg add-story-msg--error';
      submitBtn.disabled = false;
      submitBtn.textContent = prdMode ? 'Load Specification' : 'Generate Specification';
      return;
    }

    close();
    onSpecSubmitted?.();
  });
}

// --- Review modal (opened from the board panel when spec is ready) ---

export function openSpecReviewModal(options: {
  specId: number;
  projects: string[];
  onClose?: () => void;
}): void {
  const { specId, onClose } = options;
  const overlay = makeOverlay();

  function close(): void {
    overlay.remove();
    onClose?.();
  }

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  function renderShell(title: string, body: string): void {
    overlay.innerHTML = `
      <div class="add-story-modal">
        <div class="add-story-header">
          <h2 class="add-story-title">${title}</h2>
          <button class="add-story-close" aria-label="Close">&times;</button>
        </div>
        <div class="add-story-body" id="review-body">
          ${body}
        </div>
      </div>
    `;
    overlay.querySelector('.add-story-close')!.addEventListener('click', close);
  }

  function showLoading(): void {
    renderShell('Review Specification', `
      <div class="add-story-spinner-wrap">
        <div class="add-story-spinner"></div>
        <p class="add-story-spinner-msg">Loading specification…</p>
      </div>
    `);
  }

  function showError(message: string): void {
    renderShell('Something Went Wrong', `
      <div class="add-story-error">
        <pre class="add-story-error-detail">${escHtml(message)}</pre>
        <div class="add-story-actions">
          <button class="dash-btn" id="rv-close">Close</button>
        </div>
      </div>
    `);
    overlay.querySelector('#rv-close')!.addEventListener('click', close);
  }

  function showSpec(spec: SpecGenerationOut): void {
    const rendered = marked.parse(spec.spec_content ?? '') as string;
    renderShell('Review Specification', `
      <div class="add-story-spec-wrap">
        <div class="add-story-spec-body">${rendered}</div>

        <details class="add-story-amend-details">
          <summary class="add-story-amend-summary">Request Amendment</summary>
          <div class="add-story-amend-body">
            <textarea class="add-story-textarea" id="rv-amendment"
              placeholder="Describe what you'd like changed…" rows="4"></textarea>
            <button class="dash-btn dash-btn-secondary" id="rv-amend-btn">Apply Amendment</button>
          </div>
        </details>

        <p class="add-story-msg" id="rv-msg"></p>

        <div class="add-story-actions">
          <button class="dash-btn dash-btn-primary" id="rv-convert-btn">Convert to Tasks</button>
          <button class="dash-btn" id="rv-cancel">Cancel</button>
        </div>
      </div>
    `);

    overlay.querySelector('#rv-cancel')!.addEventListener('click', close);

    overlay.querySelector('#rv-amend-btn')!.addEventListener('click', async () => {
      const amendment = (overlay.querySelector<HTMLTextAreaElement>('#rv-amendment')!).value.trim();
      const msg = overlay.querySelector<HTMLElement>('#rv-msg')!;
      if (!amendment) {
        msg.textContent = 'Please describe the amendment.';
        msg.className = 'add-story-msg add-story-msg--error';
        return;
      }

      const btn = overlay.querySelector<HTMLButtonElement>('#rv-amend-btn')!;
      btn.disabled = true;
      btn.textContent = 'Submitting…';

      const resp = await apiPut<SpecGenerationOut>(`/specs/${specId}/amend`, { amendment });
      if (!resp.ok) {
        msg.textContent = 'Failed to submit amendment. Please try again.';
        msg.className = 'add-story-msg add-story-msg--error';
        btn.disabled = false;
        btn.textContent = 'Apply Amendment';
        return;
      }
      close();
    });

    overlay.querySelector('#rv-convert-btn')!.addEventListener('click', async () => {
      const btn = overlay.querySelector<HTMLButtonElement>('#rv-convert-btn')!;
      btn.disabled = true;
      btn.textContent = 'Submitting…';

      const resp = await apiPost<SpecGenerationOut>(`/specs/${specId}/convert`, {});
      if (!resp.ok) {
        const msg = overlay.querySelector<HTMLElement>('#rv-msg')!;
        msg.textContent = 'Failed to start conversion. Please try again.';
        msg.className = 'add-story-msg add-story-msg--error';
        btn.disabled = false;
        btn.textContent = 'Convert to Tasks';
        return;
      }
      close();
    });
  }

  showLoading();

  apiGet<SpecGenerationOut>(`/specs/${specId}`).then(resp => {
    if (!resp.ok || !resp.data.spec_content) {
      showError('Could not load specification content.');
      return;
    }
    showSpec(resp.data);
  }).catch(() => showError('Network error loading specification.'));
}
