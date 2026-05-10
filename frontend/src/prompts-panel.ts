/**
 * Prompts panel — view and edit per-agent system prompts from the dashboard.
 */

import { apiGet, apiPut } from './api.js';

export interface PromptInfo {
  agent_type: string;
  content: string;
}

const AGENT_LABELS: Record<string, string> = {
  developer: 'Developer',
  reviewer: 'Reviewer',
  tester: 'Tester',
  merger: 'Merger',
};

export async function fetchPrompts(): Promise<PromptInfo[]> {
  const resp = await apiGet<PromptInfo[]>('/prompts');
  return resp.ok ? resp.data : [];
}

export async function savePrompt(agentType: string, content: string): Promise<boolean> {
  const resp = await apiPut<PromptInfo>(`/prompts/${agentType}`, { content });
  return resp.ok;
}

export function renderPromptsPanel(
  container: HTMLElement,
  prompts: PromptInfo[],
  onSave: (agentType: string, content: string) => Promise<boolean>,
): void {
  const order = ['developer', 'reviewer', 'tester', 'merger'];
  const sorted = order
    .map((t) => prompts.find((p) => p.agent_type === t))
    .filter((p): p is PromptInfo => p !== undefined);

  container.innerHTML = `
    <div class="prompts-tabs">
      ${sorted.map((p, i) => `
        <button class="prompts-tab${i === 0 ? ' prompts-tab--active' : ''}"
                data-agent="${p.agent_type}">
          ${AGENT_LABELS[p.agent_type] ?? p.agent_type}
        </button>
      `).join('')}
    </div>
    <div class="prompts-editors">
      ${sorted.map((p, i) => `
        <div class="prompt-editor${i === 0 ? '' : ' prompt-editor--hidden'}"
             data-agent="${p.agent_type}">
          <textarea class="prompt-textarea" spellcheck="false">${escapeHtml(p.content)}</textarea>
          <div class="prompt-actions">
            <button class="dash-btn dash-btn-primary prompt-save-btn">Save</button>
            <span class="settings-msg"></span>
          </div>
        </div>
      `).join('')}
    </div>
  `;

  // Tab switching
  container.querySelectorAll<HTMLButtonElement>('.prompts-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.prompts-tab').forEach((t) => t.classList.remove('prompts-tab--active'));
      tab.classList.add('prompts-tab--active');
      const agent = tab.dataset.agent!;
      container.querySelectorAll<HTMLElement>('.prompt-editor').forEach((ed) => {
        ed.classList.toggle('prompt-editor--hidden', ed.dataset.agent !== agent);
      });
    });
  });

  // Save buttons
  container.querySelectorAll<HTMLElement>('.prompt-editor').forEach((editor) => {
    const agentType = editor.dataset.agent!;
    const btn = editor.querySelector<HTMLButtonElement>('.prompt-save-btn')!;
    const msg = editor.querySelector<HTMLElement>('.settings-msg')!;
    const textarea = editor.querySelector<HTMLTextAreaElement>('.prompt-textarea')!;

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      msg.textContent = 'Saving…';
      msg.className = 'settings-msg';
      const ok = await onSave(agentType, textarea.value);
      btn.disabled = false;
      if (ok) {
        msg.textContent = 'Saved';
        msg.className = 'settings-msg settings-msg--success';
      } else {
        msg.textContent = 'Failed to save';
        msg.className = 'settings-msg settings-msg--error';
      }
    });
  });
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
