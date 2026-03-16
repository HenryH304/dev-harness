/**
 * Settings panel — editable system settings in the admin dashboard.
 */

export type SettingsData = Record<string, string>;

interface SettingsField {
  key: string;
  label: string;
  type: 'number' | 'text';
}

const SETTINGS_FIELDS: SettingsField[] = [
  { key: 'agent_timeout_developer', label: 'Developer Timeout (s)', type: 'number' },
  { key: 'agent_timeout_reviewer', label: 'Reviewer Timeout (s)', type: 'number' },
  { key: 'agent_timeout_tester', label: 'Tester Timeout (s)', type: 'number' },
  { key: 'agent_timeout_merger', label: 'Merger Timeout (s)', type: 'number' },
  { key: 'max_agents_system', label: 'Max Agents (System)', type: 'number' },
  { key: 'review_rejection_threshold', label: 'Review Rejection Threshold', type: 'number' },
  { key: 'active_priority_project', label: 'Active Priority Project', type: 'text' },
];

export function renderSettingsPanel(
  container: HTMLElement,
  settings: SettingsData,
  onSave: (updated: SettingsData) => Promise<boolean>,
): void {
  const rows = SETTINGS_FIELDS.map((f) => {
    const value = settings[f.key] ?? '';
    return `
      <div class="settings-field">
        <label class="settings-label" for="setting-${f.key}">${f.label}</label>
        <input
          class="settings-input"
          id="setting-${f.key}"
          data-key="${f.key}"
          type="${f.type}"
          value="${value}"
        />
      </div>`;
  }).join('');

  container.innerHTML = `
    <div class="settings-form">
      ${rows}
      <div class="settings-actions">
        <button class="dash-btn dash-btn-primary" id="settings-save-btn">Save Settings</button>
        <span class="settings-msg"></span>
      </div>
    </div>
  `;

  const btn = container.querySelector<HTMLButtonElement>('#settings-save-btn')!;
  btn.addEventListener('click', () => {
    const updated: SettingsData = {};
    container.querySelectorAll<HTMLInputElement>('.settings-input').forEach((input) => {
      const key = input.dataset.key;
      if (key) {
        updated[key] = input.value;
      }
    });

    const msgEl = container.querySelector<HTMLElement>('.settings-msg')!;
    msgEl.textContent = 'Saving...';

    onSave(updated).then((ok) => {
      if (ok) {
        msgEl.textContent = 'Settings saved';
        msgEl.className = 'settings-msg settings-msg--success';
      } else {
        msgEl.textContent = 'Failed to save';
        msgEl.className = 'settings-msg settings-msg--error';
      }
    });
  });
}

export async function saveSettings(settings: SettingsData): Promise<boolean> {
  try {
    const resp = await fetch('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}
