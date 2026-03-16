// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  applyDependencyIcons,
  fetchUnresolvedDeps,
  removeDependencyIcons,
} from './dependency-icons.js';

describe('applyDependencyIcons', () => {
  let container: HTMLElement;

  beforeEach(() => {
    container = document.createElement('div');
  });

  it('adds lock icon to card with unresolved dependencies', () => {
    container.innerHTML = `
      <div class="card" data-ticket-id="3">
        <div class="card-title">Ticket C</div>
        <div class="card-meta"></div>
      </div>
    `;
    const depStatus = { '3': [1, 2] };
    applyDependencyIcons(container, depStatus);

    const icon = container.querySelector('.dep-lock-icon');
    expect(icon).not.toBeNull();
    expect(icon?.textContent).toContain('\u{1F512}');
  });

  it('does not add lock icon to card without dependencies', () => {
    container.innerHTML = `
      <div class="card" data-ticket-id="1">
        <div class="card-title">Ticket A</div>
        <div class="card-meta"></div>
      </div>
    `;
    const depStatus = { '3': [1] };
    applyDependencyIcons(container, depStatus);

    const icon = container.querySelector('.dep-lock-icon');
    expect(icon).toBeNull();
  });

  it('tooltip lists blocking ticket IDs', () => {
    container.innerHTML = `
      <div class="card" data-ticket-id="5">
        <div class="card-title">Ticket E</div>
        <div class="card-meta"></div>
      </div>
    `;
    const depStatus = { '5': [1, 2, 3] };
    applyDependencyIcons(container, depStatus);

    const icon = container.querySelector('.dep-lock-icon');
    expect(icon?.getAttribute('title')).toBe(
      'Blocked by: Ticket #1, Ticket #2, Ticket #3'
    );
  });

  it('handles multiple cards with different dependency states', () => {
    container.innerHTML = `
      <div class="card" data-ticket-id="1">
        <div class="card-title">Free</div>
        <div class="card-meta"></div>
      </div>
      <div class="card" data-ticket-id="2">
        <div class="card-title">Blocked</div>
        <div class="card-meta"></div>
      </div>
    `;
    const depStatus = { '2': [1] };
    applyDependencyIcons(container, depStatus);

    const icons = container.querySelectorAll('.dep-lock-icon');
    expect(icons).toHaveLength(1);
    const blockedCard = container.querySelector('[data-ticket-id="2"]');
    expect(blockedCard?.querySelector('.dep-lock-icon')).not.toBeNull();
  });

  it('does not duplicate icons on re-apply', () => {
    container.innerHTML = `
      <div class="card" data-ticket-id="3">
        <div class="card-title">Ticket</div>
        <div class="card-meta"></div>
      </div>
    `;
    const depStatus = { '3': [1] };
    applyDependencyIcons(container, depStatus);
    applyDependencyIcons(container, depStatus);

    const icons = container.querySelectorAll('.dep-lock-icon');
    expect(icons).toHaveLength(1);
  });
});

describe('removeDependencyIcons', () => {
  it('removes all lock icons from container', () => {
    const container = document.createElement('div');
    container.innerHTML = `
      <div class="card" data-ticket-id="1">
        <span class="dep-lock-icon">lock</span>
      </div>
      <div class="card" data-ticket-id="2">
        <span class="dep-lock-icon">lock</span>
      </div>
    `;
    removeDependencyIcons(container);
    expect(container.querySelectorAll('.dep-lock-icon')).toHaveLength(0);
  });
});

describe('fetchUnresolvedDeps', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns dependency status from API', async () => {
    const mockData = { '3': [1, 2] };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    } as Response);

    const result = await fetchUnresolvedDeps();
    expect(result).toEqual(mockData);
  });

  it('returns empty object on API failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'));

    const result = await fetchUnresolvedDeps();
    expect(result).toEqual({});
  });

  it('returns empty object on non-ok response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
    } as Response);

    const result = await fetchUnresolvedDeps();
    expect(result).toEqual({});
  });
});
