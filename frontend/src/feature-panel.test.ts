// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import { renderFeaturePanel } from './feature-panel.js';
import type { FeatureRequestOut } from './feature-panel.js';

function makeRequest(overrides: Partial<FeatureRequestOut> = {}): FeatureRequestOut {
  return {
    id: 1,
    project: 'test-proj',
    description: 'Add login feature',
    status: 'done',
    output_path: '/tmp/test-prd.json',
    imported_count: 3,
    error: null,
    created_at: '2026-01-01T00:00:00',
    completed_at: '2026-01-01T00:01:00',
    ...overrides,
  };
}

describe('renderFeaturePanel', () => {
  let container: HTMLElement;
  let onSubmit: Mock<(project: string, description: string) => Promise<FeatureRequestOut | null>>;

  beforeEach(() => {
    container = document.createElement('div');
    onSubmit = vi.fn().mockResolvedValue(makeRequest({ id: 99 }));
  });

  it('renders a project input', () => {
    renderFeaturePanel(container, [], [], onSubmit);
    expect(container.querySelector('#feature-project')).not.toBeNull();
  });

  it('renders a description textarea', () => {
    renderFeaturePanel(container, [], [], onSubmit);
    expect(container.querySelector('#feature-desc')).not.toBeNull();
  });

  it('renders a submit button', () => {
    renderFeaturePanel(container, [], [], onSubmit);
    expect(container.querySelector('#feature-submit-btn')).not.toBeNull();
  });

  it('shows empty state when no requests', () => {
    renderFeaturePanel(container, [], [], onSubmit);
    expect(container.textContent).toContain('No feature generation requests yet');
  });

  it('renders existing requests in a table', () => {
    const requests = [makeRequest(), makeRequest({ id: 2, status: 'running', imported_count: null })];
    renderFeaturePanel(container, requests, [], onSubmit);
    const rows = container.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(2);
  });

  it('shows imported_count for done requests', () => {
    renderFeaturePanel(container, [makeRequest({ imported_count: 5 })], [], onSubmit);
    expect(container.textContent).toContain('5');
  });

  it('shows — for requests without imported_count', () => {
    renderFeaturePanel(container, [makeRequest({ imported_count: null, status: 'running' })], [], onSubmit);
    expect(container.textContent).toContain('—');
  });

  it('calls onSubmit with project and description when form is submitted', async () => {
    renderFeaturePanel(container, [], ['my-proj'], onSubmit);
    container.querySelector<HTMLInputElement>('#feature-project')!.value = 'my-proj';
    container.querySelector<HTMLTextAreaElement>('#feature-desc')!.value = 'A new feature';
    container.querySelector<HTMLButtonElement>('#feature-submit-btn')!.click();
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledWith('my-proj', 'A new feature'));
  });

  it('shows error when project or description is empty', async () => {
    renderFeaturePanel(container, [], [], onSubmit);
    container.querySelector<HTMLButtonElement>('#feature-submit-btn')!.click();
    await vi.waitFor(() => {
      const msg = container.querySelector<HTMLElement>('#feature-msg')!;
      expect(msg.textContent).toContain('required');
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows success message after successful submission', async () => {
    renderFeaturePanel(container, [], [], onSubmit);
    container.querySelector<HTMLInputElement>('#feature-project')!.value = 'p';
    container.querySelector<HTMLTextAreaElement>('#feature-desc')!.value = 'd';
    container.querySelector<HTMLButtonElement>('#feature-submit-btn')!.click();
    await vi.waitFor(() => {
      const msg = container.querySelector<HTMLElement>('#feature-msg')!;
      expect(msg.className).toContain('success');
    });
  });

  it('renders project options in datalist', () => {
    renderFeaturePanel(container, [], ['proj-a', 'proj-b'], onSubmit);
    const options = container.querySelectorAll('#feature-project-list option');
    expect(options).toHaveLength(2);
    const values = Array.from(options).map((o) => (o as HTMLOptionElement).value);
    expect(values).toContain('proj-a');
    expect(values).toContain('proj-b');
  });
});
