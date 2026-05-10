/**
 * Project management — import projects, list projects, set active priority.
 */

import { apiGet, apiPatch, apiPost } from './api.js';

export interface ProjectInfo {
  name: string;
  ticket_count: number;
  repo_path: string;
}

export interface ProjectListResponse {
  projects: ProjectInfo[];
  active_priority_project: string;
}

async function checkRepoPath(path: string): Promise<{ exists: boolean; expandedPath: string }> {
  try {
    const resp = await apiPost<{ exists: boolean; expanded_path: string }>('/projects/check-path', { path });
    if (resp.ok) return { exists: resp.data.exists, expandedPath: resp.data.expanded_path };
  } catch {
    // fall through
  }
  // On network error, assume exists — backend will validate
  return { exists: true, expandedPath: path };
}

export function renderProjectManagement(
  container: HTMLElement,
  projects: ProjectInfo[],
  activePriority: string,
  onImport: (projectName: string, prdPath: string, repoPath: string, createIfMissing: boolean) => Promise<boolean>,
  onSetPriority: (projectName: string) => Promise<boolean>,
): void {
  const projectRows = projects
    .map(
      (p) => `
    <div class="project-item${p.name === activePriority ? ' project-item--active' : ''}" data-project="${p.name}">
      <div class="project-info">
        <span class="project-name">${p.name}</span>
        <span class="project-count">${p.ticket_count} ticket${p.ticket_count !== 1 ? 's' : ''}</span>
      </div>
      <button class="dash-btn ${p.name === activePriority ? 'dash-btn-success' : 'dash-btn-primary'} set-priority-btn"
        ${p.name === activePriority ? 'disabled' : ''}>
        ${p.name === activePriority ? 'Active' : 'Set Priority'}
      </button>
    </div>`,
    )
    .join('');

  const emptyMsg =
    projects.length === 0
      ? '<p class="dash-empty">No projects imported yet</p>'
      : '';

  container.innerHTML = `
    <div class="project-mgmt">
      <div class="project-import">
        <h3 class="project-section-title">Import Project</h3>
        <div class="project-import-form">
          <div class="settings-field">
            <label class="settings-label" for="import-project-name">Project Name</label>
            <input class="settings-input" id="import-project-name" type="text" placeholder="my-project" />
          </div>
          <div class="settings-field">
            <label class="settings-label" for="import-prd-path">prd.json Path</label>
            <input class="settings-input" id="import-prd-path" type="text" placeholder="/path/to/prd.json" />
          </div>
          <div class="settings-field">
            <label class="settings-label" for="import-repo-path">Git Repo Path</label>
            <input class="settings-input" id="import-repo-path" type="text" placeholder="~/Projects/my-project" />
          </div>
          <div class="project-import-actions">
            <button class="dash-btn dash-btn-primary" id="import-btn">Import</button>
            <span class="project-import-msg"></span>
          </div>
        </div>
      </div>
      <div class="project-list">
        <h3 class="project-section-title">Projects</h3>
        ${emptyMsg}
        ${projectRows}
      </div>
    </div>
  `;

  const nameInput = container.querySelector<HTMLInputElement>('#import-project-name')!;
  const pathInput = container.querySelector<HTMLInputElement>('#import-prd-path')!;
  const repoInput = container.querySelector<HTMLInputElement>('#import-repo-path')!;
  const msgEl = container.querySelector<HTMLElement>('.project-import-msg')!;

  // Auto-fill repo path as ~/Projects/<project-name> when name is typed
  nameInput.addEventListener('input', () => {
    const name = nameInput.value.trim();
    repoInput.value = name ? `~/Projects/${name}` : '';
  });

  const importBtn = container.querySelector<HTMLButtonElement>('#import-btn')!;
  importBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const path = pathInput.value.trim();
    const repoPath = repoInput.value.trim();

    if (!name || !path || !repoPath) {
      msgEl.textContent = 'All fields are required';
      msgEl.className = 'project-import-msg project-import-msg--error';
      return;
    }

    msgEl.textContent = 'Checking path...';
    msgEl.className = 'project-import-msg';

    const { exists, expandedPath } = await checkRepoPath(repoPath);
    let createIfMissing = false;

    if (!exists) {
      const confirmed = window.confirm(
        `Path "${expandedPath}" does not exist. Create it?`,
      );
      if (!confirmed) {
        msgEl.textContent = '';
        return;
      }
      createIfMissing = true;
    }

    msgEl.textContent = 'Importing...';

    const ok = await onImport(name, path, repoPath, createIfMissing);
    if (ok) {
      msgEl.textContent = 'Import successful';
      msgEl.className = 'project-import-msg project-import-msg--success';
      nameInput.value = '';
      pathInput.value = '';
      repoInput.value = '';
    } else {
      msgEl.textContent = 'Import failed';
      msgEl.className = 'project-import-msg project-import-msg--error';
    }
  });

  // Set priority handlers
  container.querySelectorAll('.set-priority-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.project-item') as HTMLElement;
      const projectName = item.dataset.project ?? '';
      onSetPriority(projectName);
    });
  });
}

export async function fetchProjects(): Promise<ProjectListResponse> {
  try {
    const resp = await apiGet<ProjectListResponse>('/projects');
    if (resp.ok) return resp.data;
  } catch {
    // fall through
  }
  return { projects: [], active_priority_project: '' };
}

export async function importProject(
  projectName: string,
  prdPath: string,
  repoPath: string,
  createIfMissing: boolean,
): Promise<boolean> {
  try {
    const resp = await apiPost<{ imported_count: number }>(
      '/projects/import',
      {
        project_name: projectName,
        prd_path: prdPath,
        repo_path: repoPath,
        create_repo_if_missing: createIfMissing,
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

export async function setActivePriority(projectName: string): Promise<boolean> {
  try {
    const resp = await apiPatch<unknown>('/settings', {
      settings: { active_priority_project: projectName },
    });
    return resp.ok;
  } catch {
    return false;
  }
}
