import { apiPost } from './api.js';

export interface CreateProjectOptions {
  onDone: () => void;
}

export function openCreateProjectModal(options: CreateProjectOptions): void {
  const overlay = document.createElement('div');
  overlay.className = 'add-story-overlay';
  overlay.innerHTML = `
    <div class="add-story-modal create-project-modal">
      <div class="add-story-header">
        <h2 class="add-story-title">New Project</h2>
        <button class="add-story-close" aria-label="Close">&times;</button>
      </div>
      <div class="create-project-body">
        <div class="settings-field">
          <label class="settings-label" for="cp-name">Project Name</label>
          <input class="settings-input" id="cp-name" type="text" placeholder="my-project" autocomplete="off" />
        </div>
        <p class="create-project-hint">Project will be created at <code>~/Projects/&lt;name&gt;</code></p>
        <div class="create-project-actions">
          <button class="dash-btn dash-btn-primary" id="cp-submit">Create Project</button>
          <span class="create-project-msg"></span>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const nameInput = overlay.querySelector<HTMLInputElement>('#cp-name')!;
  const submitBtn = overlay.querySelector<HTMLButtonElement>('#cp-submit')!;
  const msgEl = overlay.querySelector<HTMLElement>('.create-project-msg')!;

  nameInput.focus();

  function close(): void {
    overlay.remove();
  }

  overlay.querySelector('.add-story-close')!.addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  submitBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();

    if (!name) {
      msgEl.textContent = 'Project name is required';
      msgEl.className = 'create-project-msg create-project-msg--error';
      return;
    }

    submitBtn.disabled = true;
    msgEl.textContent = 'Creating...';
    msgEl.className = 'create-project-msg';

    try {
      const resp = await apiPost<{ name: string; repo_path: string; git_initialized: boolean }>('/projects', {
        name,
        repo_path: `~/Projects/${name}`,
        create_if_missing: true,
      });

      if (resp.ok) {
        if (resp.data.git_initialized) {
          msgEl.textContent = 'Project created and git repository initialised.';
          msgEl.className = 'create-project-msg create-project-msg--success';
          await new Promise((r) => setTimeout(r, 1200));
        }
        close();
        options.onDone();
      } else {
        const detail = (resp as { data?: { detail?: string } }).data?.detail ?? 'Failed to create project';
        msgEl.textContent = detail;
        msgEl.className = 'create-project-msg create-project-msg--error';
        submitBtn.disabled = false;
      }
    } catch {
      msgEl.textContent = 'Network error — please try again';
      msgEl.className = 'create-project-msg create-project-msg--error';
      submitBtn.disabled = false;
    }
  });
}
