// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  renderSettingsPanel,
  saveSettings,
} from './settings-panel.js';
import type { SettingsData } from './settings-panel.js';

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// --- renderSettingsPanel ---

describe('renderSettingsPanel', () => {
  it('renders all editable settings fields', () => {
    const el = document.createElement('div');
    const settings: SettingsData = {
      agent_timeout_developer: '1200',
      agent_timeout_reviewer: '600',
      agent_timeout_tester: '600',
      agent_timeout_merger: '300',
      max_agents_system: '10',
      review_rejection_threshold: '3',
      active_priority_project: 'my-project',
    };
    renderSettingsPanel(el, settings, vi.fn());

    expect(el.querySelector<HTMLInputElement>('[data-key="agent_timeout_developer"]')?.value).toBe('1200');
    expect(el.querySelector<HTMLInputElement>('[data-key="agent_timeout_reviewer"]')?.value).toBe('600');
    expect(el.querySelector<HTMLInputElement>('[data-key="agent_timeout_tester"]')?.value).toBe('600');
    expect(el.querySelector<HTMLInputElement>('[data-key="agent_timeout_merger"]')?.value).toBe('300');
    expect(el.querySelector<HTMLInputElement>('[data-key="max_agents_system"]')?.value).toBe('10');
    expect(el.querySelector<HTMLInputElement>('[data-key="review_rejection_threshold"]')?.value).toBe('3');
    expect(el.querySelector<HTMLInputElement>('[data-key="active_priority_project"]')?.value).toBe('my-project');
  });

  it('renders with empty settings using defaults', () => {
    const el = document.createElement('div');
    renderSettingsPanel(el, {}, vi.fn());

    // Should render all fields with empty values
    const inputs = el.querySelectorAll('input');
    expect(inputs.length).toBeGreaterThanOrEqual(7);
  });

  it('renders a save button', () => {
    const el = document.createElement('div');
    renderSettingsPanel(el, {}, vi.fn());
    const btn = el.querySelector('#settings-save-btn');
    expect(btn).not.toBeNull();
    expect(btn?.textContent).toContain('Save');
  });

  it('calls onSave with updated values when save button clicked', () => {
    const el = document.createElement('div');
    const onSave = vi.fn().mockResolvedValue(true);
    const settings: SettingsData = {
      max_agents_system: '10',
    };
    renderSettingsPanel(el, settings, onSave);

    // Modify a value
    const input = el.querySelector<HTMLInputElement>('[data-key="max_agents_system"]')!;
    input.value = '20';

    // Click save
    const btn = el.querySelector<HTMLButtonElement>('#settings-save-btn')!;
    btn.click();

    expect(onSave).toHaveBeenCalledTimes(1);
    const savedSettings = onSave.mock.calls[0][0] as Record<string, string>;
    expect(savedSettings['max_agents_system']).toBe('20');
  });

  it('shows success message after save callback resolves', async () => {
    const el = document.createElement('div');
    const onSave = vi.fn().mockResolvedValue(true);
    renderSettingsPanel(el, {}, onSave);

    const btn = el.querySelector<HTMLButtonElement>('#settings-save-btn')!;
    btn.click();

    // Wait for async save
    await vi.waitFor(() => {
      const msg = el.querySelector('.settings-msg');
      expect(msg).not.toBeNull();
      expect(msg?.textContent).toContain('saved');
    });
  });

  it('shows error message after save callback rejects', async () => {
    const el = document.createElement('div');
    const onSave = vi.fn().mockResolvedValue(false);
    renderSettingsPanel(el, {}, onSave);

    const btn = el.querySelector<HTMLButtonElement>('#settings-save-btn')!;
    btn.click();

    await vi.waitFor(() => {
      const msg = el.querySelector('.settings-msg');
      expect(msg).not.toBeNull();
      expect(msg?.textContent).toContain('Failed');
    });
  });
});

// --- saveSettings ---

describe('saveSettings', () => {
  it('calls PATCH /api/settings with collected values', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ updated_count: 2 }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const result = await saveSettings({ max_agents_system: '20', review_rejection_threshold: '5' });
    expect(result).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe('/api/settings');
    expect(opts.method).toBe('PATCH');
    const body = JSON.parse(opts.body);
    expect(body.settings.max_agents_system).toBe('20');
    expect(body.settings.review_rejection_threshold).toBe('5');
  });

  it('returns false on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    const result = await saveSettings({ max_agents_system: '20' });
    expect(result).toBe(false);
  });
});
