/**
 * Feature generation panel — submit a description, get stories back.
 */

import { apiGet, apiPost } from './api.js';

export interface FeatureRequestOut {
  id: number;
  project: string;
  description: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  output_path: string | null;
  imported_count: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export async function fetchFeatureRequests(): Promise<FeatureRequestOut[]> {
  const resp = await apiGet<FeatureRequestOut[]>('/features');
  return resp.ok ? resp.data : [];
}

export async function submitFeature(
  project: string,
  description: string,
): Promise<FeatureRequestOut | null> {
  const resp = await apiPost<FeatureRequestOut>('/features/generate', { project, description });
  return resp.ok ? resp.data : null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  running: 'Running…',
  done: 'Done',
  failed: 'Failed',
};

const STATUS_CLASSES: Record<string, string> = {
  pending: 'feature-status--pending',
  running: 'feature-status--running',
  done: 'feature-status--done',
  failed: 'feature-status--failed',
};

export function renderFeaturePanel(
  container: HTMLElement,
  requests: FeatureRequestOut[],
  projects: string[],
  onSubmit: (project: string, description: string) => Promise<FeatureRequestOut | null>,
): void {
  const projectOptions = projects
    .map((p) => `<option value="${escapeAttr(p)}">${escapeHtml(p)}</option>`)
    .join('');

  container.innerHTML = `
    <div class="feature-form">
      <div class="settings-field">
        <label class="settings-label" for="feature-project">Project</label>
        <input class="settings-input" id="feature-project" list="feature-project-list"
               placeholder="e.g. my-project" />
        <datalist id="feature-project-list">${projectOptions}</datalist>
      </div>
      <div class="settings-field">
        <label class="settings-label" for="feature-desc">Feature description</label>
        <textarea class="prompt-textarea feature-desc-textarea" id="feature-desc"
                  rows="4" placeholder="Describe the feature or requirement…"></textarea>
      </div>
      <div class="settings-actions">
        <button class="dash-btn dash-btn-primary" id="feature-submit-btn">Generate Stories</button>
        <span class="settings-msg" id="feature-msg"></span>
      </div>
    </div>
    <div id="feature-list">
      ${_renderRequests(requests)}
    </div>
  `;

  const projectInput = container.querySelector<HTMLInputElement>('#feature-project')!;
  const descInput = container.querySelector<HTMLTextAreaElement>('#feature-desc')!;
  const btn = container.querySelector<HTMLButtonElement>('#feature-submit-btn')!;
  const msg = container.querySelector<HTMLElement>('#feature-msg')!;
  const list = container.querySelector<HTMLElement>('#feature-list')!;

  btn.addEventListener('click', async () => {
    const project = projectInput.value.trim();
    const description = descInput.value.trim();
    if (!project || !description) {
      msg.textContent = 'Project and description are required';
      msg.className = 'settings-msg settings-msg--error';
      return;
    }
    btn.disabled = true;
    msg.textContent = 'Submitting…';
    msg.className = 'settings-msg';

    const result = await onSubmit(project, description);
    btn.disabled = false;
    if (result) {
      msg.textContent = 'Submitted — agent is generating stories in the background';
      msg.className = 'settings-msg settings-msg--success';
      descInput.value = '';
      // Prepend new request to list
      const newItem = document.createElement('div');
      newItem.innerHTML = _renderRequests([result]);
      list.innerHTML = newItem.innerHTML + list.innerHTML;
    } else {
      msg.textContent = 'Failed to submit';
      msg.className = 'settings-msg settings-msg--error';
    }
  });
}

function _renderRequests(requests: FeatureRequestOut[]): string {
  if (requests.length === 0) {
    return '<p class="dash-empty">No feature generation requests yet</p>';
  }
  return `
    <table class="dash-table feature-table">
      <thead>
        <tr>
          <th>Project</th>
          <th>Description</th>
          <th>Status</th>
          <th>Stories</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        ${requests.map(_renderRow).join('')}
      </tbody>
    </table>
  `;
}

function _renderRow(r: FeatureRequestOut): string {
  const statusClass = STATUS_CLASSES[r.status] ?? '';
  const label = STATUS_LABELS[r.status] ?? r.status;
  const desc =
    r.description.length > 80 ? r.description.slice(0, 80) + '…' : r.description;
  const stories = r.imported_count != null ? String(r.imported_count) : '—';
  const created = new Date(r.created_at).toLocaleString();
  const errorTitle = r.error ? ` title="${escapeAttr(r.error)}"` : '';
  return `
    <tr>
      <td>${escapeHtml(r.project)}</td>
      <td class="feature-desc-cell">${escapeHtml(desc)}</td>
      <td><span class="feature-status ${statusClass}"${errorTitle}>${label}</span></td>
      <td>${stories}</td>
      <td>${created}</td>
    </tr>
  `;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeAttr(text: string): string {
  return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
