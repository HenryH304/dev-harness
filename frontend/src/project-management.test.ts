// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderProjectManagement } from './project-management.js';
import type { ProjectInfo } from './project-management.js';

describe('renderProjectManagement', () => {
  let container: HTMLElement;
  let onImport: (projectName: string, prdPath: string) => Promise<boolean>;
  let onSetPriority: (projectName: string) => Promise<boolean>;
  let onImportMock: ReturnType<typeof vi.fn>;
  let onSetPriorityMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    container = document.createElement('div');
    onImportMock = vi.fn().mockResolvedValue(true);
    onSetPriorityMock = vi.fn().mockResolvedValue(true);
    onImport = onImportMock as (projectName: string, prdPath: string) => Promise<boolean>;
    onSetPriority = onSetPriorityMock as (projectName: string) => Promise<boolean>;
  });

  it('renders empty state when no projects', () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    expect(container.querySelector('.dash-empty')).not.toBeNull();
    expect(container.querySelector('.dash-empty')!.textContent).toContain('No projects');
  });

  it('renders project list with ticket counts', () => {
    const projects: ProjectInfo[] = [
      { name: 'alpha', ticket_count: 3 },
      { name: 'beta', ticket_count: 1 },
    ];
    renderProjectManagement(container, projects, '', onImport, onSetPriority);
    const items = container.querySelectorAll('.project-item');
    expect(items.length).toBe(2);
    expect(items[0].querySelector('.project-name')!.textContent).toBe('alpha');
    expect(items[0].querySelector('.project-count')!.textContent).toContain('3');
    expect(items[1].querySelector('.project-count')!.textContent).toContain('1 ticket');
  });

  it('highlights active priority project', () => {
    const projects: ProjectInfo[] = [
      { name: 'alpha', ticket_count: 3 },
      { name: 'beta', ticket_count: 1 },
    ];
    renderProjectManagement(container, projects, 'alpha', onImport, onSetPriority);
    const items = container.querySelectorAll('.project-item');
    expect(items[0].classList.contains('project-item--active')).toBe(true);
    expect(items[1].classList.contains('project-item--active')).toBe(false);
  });

  it('disables set priority button for active project', () => {
    const projects: ProjectInfo[] = [{ name: 'alpha', ticket_count: 3 }];
    renderProjectManagement(container, projects, 'alpha', onImport, onSetPriority);
    const btn = container.querySelector('.set-priority-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Active');
  });

  it('renders import form with inputs', () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    expect(container.querySelector('#import-project-name')).not.toBeNull();
    expect(container.querySelector('#import-prd-path')).not.toBeNull();
    expect(container.querySelector('#import-btn')).not.toBeNull();
  });

  it('calls onImport with form values', async () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    const nameInput = container.querySelector<HTMLInputElement>('#import-project-name')!;
    const pathInput = container.querySelector<HTMLInputElement>('#import-prd-path')!;
    nameInput.value = 'test-project';
    pathInput.value = '/tmp/prd.json';

    container.querySelector<HTMLButtonElement>('#import-btn')!.click();
    // Wait for promise
    await vi.waitFor(() => {
      expect(onImportMock).toHaveBeenCalledWith('test-project', '/tmp/prd.json');
    });
  });

  it('shows error when import fields are empty', () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    container.querySelector<HTMLButtonElement>('#import-btn')!.click();
    const msg = container.querySelector('.project-import-msg')!;
    expect(msg.textContent).toContain('required');
    expect(onImportMock).not.toHaveBeenCalled();
  });

  it('shows success message after import', async () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    const nameInput = container.querySelector<HTMLInputElement>('#import-project-name')!;
    const pathInput = container.querySelector<HTMLInputElement>('#import-prd-path')!;
    nameInput.value = 'proj';
    pathInput.value = '/tmp/prd.json';
    container.querySelector<HTMLButtonElement>('#import-btn')!.click();

    await vi.waitFor(() => {
      const msg = container.querySelector('.project-import-msg')!;
      expect(msg.textContent).toContain('successful');
    });
  });

  it('clears inputs after successful import', async () => {
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    const nameInput = container.querySelector<HTMLInputElement>('#import-project-name')!;
    const pathInput = container.querySelector<HTMLInputElement>('#import-prd-path')!;
    nameInput.value = 'proj';
    pathInput.value = '/tmp/prd.json';
    container.querySelector<HTMLButtonElement>('#import-btn')!.click();

    await vi.waitFor(() => {
      expect(nameInput.value).toBe('');
      expect(pathInput.value).toBe('');
    });
  });

  it('shows error message on failed import', async () => {
    onImportMock.mockResolvedValue(false);
    renderProjectManagement(container, [], '', onImport, onSetPriority);
    const nameInput = container.querySelector<HTMLInputElement>('#import-project-name')!;
    const pathInput = container.querySelector<HTMLInputElement>('#import-prd-path')!;
    nameInput.value = 'proj';
    pathInput.value = '/tmp/prd.json';
    container.querySelector<HTMLButtonElement>('#import-btn')!.click();

    await vi.waitFor(() => {
      const msg = container.querySelector('.project-import-msg')!;
      expect(msg.textContent).toContain('failed');
    });
  });

  it('calls onSetPriority when set priority button clicked', () => {
    const projects: ProjectInfo[] = [{ name: 'beta', ticket_count: 2 }];
    renderProjectManagement(container, projects, '', onImport, onSetPriority);
    const btn = container.querySelector('.set-priority-btn') as HTMLButtonElement;
    btn.click();
    expect(onSetPriorityMock).toHaveBeenCalledWith('beta');
  });
});
