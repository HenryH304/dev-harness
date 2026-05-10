// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import { renderPromptsPanel } from './prompts-panel.js';
import type { PromptInfo } from './prompts-panel.js';

const SAMPLE_PROMPTS: PromptInfo[] = [
  { agent_type: 'developer', content: '# Developer\nDo TDD.' },
  { agent_type: 'reviewer', content: '# Reviewer\nCheck code.' },
  { agent_type: 'tester', content: '# Tester\nRun tests.' },
  { agent_type: 'merger', content: '# Merger\nMerge it.' },
];

describe('renderPromptsPanel', () => {
  let container: HTMLElement;
  let onSave: Mock<(agentType: string, content: string) => Promise<boolean>>;

  beforeEach(() => {
    container = document.createElement('div');
    onSave = vi.fn().mockResolvedValue(true);
  });

  it('renders a tab for each agent type', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const tabs = container.querySelectorAll('.prompts-tab');
    expect(tabs).toHaveLength(4);
    const labels = Array.from(tabs).map((t) => t.textContent?.trim());
    expect(labels).toContain('Developer');
    expect(labels).toContain('Reviewer');
    expect(labels).toContain('Tester');
    expect(labels).toContain('Merger');
  });

  it('developer tab is active by default', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const activeTab = container.querySelector('.prompts-tab--active');
    expect(activeTab?.textContent?.trim()).toBe('Developer');
  });

  it('developer editor is visible by default', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const editors = container.querySelectorAll<HTMLElement>('.prompt-editor');
    const devEditor = Array.from(editors).find((e) => e.dataset.agent === 'developer');
    expect(devEditor?.classList.contains('prompt-editor--hidden')).toBe(false);
  });

  it('non-developer editors are hidden by default', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const editors = container.querySelectorAll<HTMLElement>('.prompt-editor');
    const hidden = Array.from(editors).filter(
      (e) => e.dataset.agent !== 'developer' && e.classList.contains('prompt-editor--hidden'),
    );
    expect(hidden).toHaveLength(3);
  });

  it('textarea contains the prompt content', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const devEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="developer"]')!;
    const textarea = devEditor.querySelector<HTMLTextAreaElement>('.prompt-textarea')!;
    expect(textarea.value).toContain('Do TDD');
  });

  it('clicking a tab makes it active and shows its editor', () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const reviewerTab = Array.from(container.querySelectorAll<HTMLButtonElement>('.prompts-tab')).find(
      (t) => t.dataset.agent === 'reviewer',
    )!;
    reviewerTab.click();

    expect(reviewerTab.classList.contains('prompts-tab--active')).toBe(true);
    const reviewerEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="reviewer"]')!;
    expect(reviewerEditor.classList.contains('prompt-editor--hidden')).toBe(false);
    const devEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="developer"]')!;
    expect(devEditor.classList.contains('prompt-editor--hidden')).toBe(true);
  });

  it('save button calls onSave with agent type and current textarea value', async () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const devEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="developer"]')!;
    const textarea = devEditor.querySelector<HTMLTextAreaElement>('.prompt-textarea')!;
    textarea.value = '# Updated\nNew content.';
    devEditor.querySelector<HTMLButtonElement>('.prompt-save-btn')!.click();
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith('developer', '# Updated\nNew content.'));
  });

  it('shows success message after successful save', async () => {
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const devEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="developer"]')!;
    devEditor.querySelector<HTMLButtonElement>('.prompt-save-btn')!.click();
    await vi.waitFor(() => {
      const msg = devEditor.querySelector<HTMLElement>('.settings-msg')!;
      expect(msg.textContent).toBe('Saved');
      expect(msg.classList.contains('settings-msg--success')).toBe(true);
    });
  });

  it('shows error message when save fails', async () => {
    onSave.mockResolvedValue(false);
    renderPromptsPanel(container, SAMPLE_PROMPTS, onSave);
    const devEditor = container.querySelector<HTMLElement>('.prompt-editor[data-agent="developer"]')!;
    devEditor.querySelector<HTMLButtonElement>('.prompt-save-btn')!.click();
    await vi.waitFor(() => {
      const msg = devEditor.querySelector<HTMLElement>('.settings-msg')!;
      expect(msg.textContent).toBe('Failed to save');
      expect(msg.classList.contains('settings-msg--error')).toBe(true);
    });
  });

  it('renders correctly with a subset of prompts', () => {
    const partial = SAMPLE_PROMPTS.slice(0, 2);
    renderPromptsPanel(container, partial, onSave);
    expect(container.querySelectorAll('.prompts-tab')).toHaveLength(2);
  });
});
