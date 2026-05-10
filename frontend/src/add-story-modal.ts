/**
 * Add Story modal — drives spec-writer and story-writer agents step by step.
 */

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

type ModalPhase =
  | 'form'
  | 'writing-spec'
  | 'spec-ready'
  | 'amending'
  | 'converting'
  | 'done'
  | 'error';

export function openAddStoryModal(options: {
  defaultProject: string;
  projects: string[];
  onDone: () => void;
}): void {
  const { defaultProject, projects, onDone } = options;

  // Remove any existing modal
  document.querySelector('.add-story-overlay')?.remove();

  const overlay = document.createElement('div');
  overlay.className = 'add-story-overlay';
  document.body.appendChild(overlay);

  let currentSpec: SpecGenerationOut | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function close(): void {
    stopPolling();
    overlay.remove();
  }

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  function render(phase: ModalPhase): void {
    overlay.innerHTML = `
      <div class="add-story-modal">
        <div class="add-story-header">
          <h2 class="add-story-title">${titleFor(phase)}</h2>
          <button class="add-story-close" aria-label="Close">&times;</button>
        </div>
        <div class="add-story-body" id="add-story-body">
          ${bodyFor(phase)}
        </div>
      </div>
    `;

    overlay.querySelector('.add-story-close')!.addEventListener('click', close);
    wirePhase(phase);
  }

  function titleFor(phase: ModalPhase): string {
    switch (phase) {
      case 'form': return 'Add Story';
      case 'writing-spec': return 'Generating Specification';
      case 'spec-ready': return 'Review Specification';
      case 'amending': return 'Updating Specification';
      case 'converting': return 'Converting to Tasks';
      case 'done': return 'Tasks Created';
      case 'error': return 'Something Went Wrong';
    }
  }

  function bodyFor(phase: ModalPhase): string {
    switch (phase) {
      case 'form': return `
        <div class="add-story-form">
          <label class="add-story-label" for="as-project">Project</label>
          <input class="add-story-input" id="as-project" type="text" list="as-project-list"
            value="${escHtml(defaultProject)}" placeholder="Project name (required)"
            ${defaultProject ? 'readonly' : ''}>
          <datalist id="as-project-list">
            ${projects.map((p) => `<option value="${escHtml(p)}">`).join('')}
          </datalist>

          <label class="add-story-label" for="as-desc">Feature / Requirement</label>
          <textarea class="add-story-textarea" id="as-desc"
            placeholder="Describe the feature or requirement…" rows="6"></textarea>

          <p class="add-story-msg" id="as-msg"></p>

          <div class="add-story-actions">
            <button class="dash-btn dash-btn-primary" id="as-submit">Generate Specification</button>
            <button class="dash-btn" id="as-cancel">Cancel</button>
          </div>
        </div>
      `;

      case 'writing-spec':
      case 'amending':
      case 'converting': {
        const messages: Record<string, string> = {
          'writing-spec': 'Running spec-writer agent — this may take a minute…',
          'amending': 'Applying amendment — please wait…',
          'converting': 'Running story-writer agent — converting spec to tasks…',
        };
        return `
          <div class="add-story-spinner-wrap">
            <div class="add-story-spinner"></div>
            <p class="add-story-spinner-msg">${messages[phase]}</p>
          </div>
        `;
      }

      case 'spec-ready': {
        const content = escHtml(currentSpec?.spec_content ?? '');
        return `
          <div class="add-story-spec-wrap">
            <pre class="add-story-spec-pre">${content}</pre>

            <details class="add-story-amend-details">
              <summary class="add-story-amend-summary">Request Amendment</summary>
              <div class="add-story-amend-body">
                <textarea class="add-story-textarea" id="as-amendment"
                  placeholder="Describe what you'd like changed…" rows="4"></textarea>
                <button class="dash-btn dash-btn-secondary" id="as-amend-btn">Apply Amendment</button>
              </div>
            </details>

            <p class="add-story-msg" id="as-msg"></p>

            <div class="add-story-actions">
              <button class="dash-btn dash-btn-primary" id="as-convert-btn">Convert to Tasks</button>
              <button class="dash-btn" id="as-cancel-spec">Cancel</button>
            </div>
          </div>
        `;
      }

      case 'done':
        return `
          <div class="add-story-done">
            <p class="add-story-done-msg">
              ✓ ${currentSpec?.imported_count ?? 0} task${(currentSpec?.imported_count ?? 0) !== 1 ? 's' : ''} created successfully.
            </p>
            <div class="add-story-actions">
              <button class="dash-btn dash-btn-primary" id="as-done-btn">Close</button>
            </div>
          </div>
        `;

      case 'error': {
        const stepLabel = stepLabelFor(currentSpec?.step ?? null);
        const errText = escHtml(currentSpec?.error ?? 'Unknown error');
        return `
          <div class="add-story-error">
            <p class="add-story-error-step">Failed at: <strong>${stepLabel}</strong></p>
            <pre class="add-story-error-detail">${errText}</pre>
            <div class="add-story-actions">
              <button class="dash-btn" id="as-error-close">Close</button>
            </div>
          </div>
        `;
      }
    }
  }

  function stepLabelFor(step: string | null): string {
    switch (step) {
      case 'spec_writing': return 'Generating specification';
      case 'amending': return 'Applying amendment';
      case 'converting': return 'Converting to tasks';
      case 'importing': return 'Importing tasks';
      default: return step ?? 'Unknown step';
    }
  }

  function wirePhase(phase: ModalPhase): void {
    switch (phase) {
      case 'form':
        overlay.querySelector('#as-submit')!.addEventListener('click', handleSubmit);
        overlay.querySelector('#as-cancel')!.addEventListener('click', close);
        break;

      case 'spec-ready':
        overlay.querySelector('#as-convert-btn')!.addEventListener('click', handleConvert);
        overlay.querySelector('#as-cancel-spec')!.addEventListener('click', close);
        overlay.querySelector('#as-amend-btn')?.addEventListener('click', handleAmend);
        break;

      case 'done':
        overlay.querySelector('#as-done-btn')!.addEventListener('click', () => {
          close();
          onDone();
        });
        break;

      case 'error':
        overlay.querySelector('#as-error-close')!.addEventListener('click', close);
        break;

      default:
        break;
    }
  }

  async function handleSubmit(): Promise<void> {
    const project = (overlay.querySelector<HTMLInputElement>('#as-project')!).value.trim();
    const desc = (overlay.querySelector<HTMLTextAreaElement>('#as-desc')!).value.trim();
    const msg = overlay.querySelector<HTMLElement>('#as-msg')!;

    if (!project) {
      msg.textContent = 'Project is required.';
      msg.className = 'add-story-msg add-story-msg--error';
      return;
    }
    if (!desc) {
      msg.textContent = 'Feature description is required.';
      msg.className = 'add-story-msg add-story-msg--error';
      return;
    }

    render('writing-spec');

    const resp = await apiPost<SpecGenerationOut>('/specs', { project, description: desc });
    if (!resp.ok) {
      currentSpec = null;
      render('error');
      return;
    }
    currentSpec = resp.data;
    startPolling();
  }

  async function handleAmend(): Promise<void> {
    const amendment = (overlay.querySelector<HTMLTextAreaElement>('#as-amendment')!).value.trim();
    const msg = overlay.querySelector<HTMLElement>('#as-msg')!;
    if (!amendment) {
      msg.textContent = 'Please describe the amendment.';
      msg.className = 'add-story-msg add-story-msg--error';
      return;
    }
    if (!currentSpec) return;

    render('amending');
    const resp = await apiPut<SpecGenerationOut>(`/specs/${currentSpec.id}/amend`, { amendment });
    if (!resp.ok) {
      render('error');
      return;
    }
    currentSpec = resp.data;
    startPolling();
  }

  async function handleConvert(): Promise<void> {
    if (!currentSpec) return;
    render('converting');
    const resp = await apiPost<SpecGenerationOut>(`/specs/${currentSpec.id}/convert`, {});
    if (!resp.ok) {
      render('error');
      return;
    }
    currentSpec = resp.data;
    startPolling();
  }

  function startPolling(): void {
    stopPolling();
    pollTimer = setInterval(async () => {
      if (!currentSpec) { stopPolling(); return; }
      const resp = await apiGet<SpecGenerationOut>(`/specs/${currentSpec.id}`);
      if (!resp.ok) return;
      currentSpec = resp.data;

      if (currentSpec.status === 'failed') {
        stopPolling();
        render('error');
        return;
      }

      if (currentSpec.status === 'done') {
        stopPolling();
        // Determine what phase completed
        const step = currentSpec.step;
        if (step === 'importing' || currentSpec.imported_count !== null) {
          render('done');
        } else {
          render('spec-ready');
        }
      }
    }, 3000);
  }

  function escHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  render('form');
}
