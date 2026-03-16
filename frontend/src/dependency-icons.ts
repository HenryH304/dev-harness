/**
 * Dependency visualisation on board — lock icons for tickets with unresolved dependencies.
 */

export type DepStatus = Record<string, number[]>;

export async function fetchUnresolvedDeps(): Promise<DepStatus> {
  try {
    const resp = await fetch('/api/dependencies/unresolved');
    if (!resp.ok) return {};
    return (await resp.json()) as DepStatus;
  } catch {
    return {};
  }
}

export function applyDependencyIcons(
  container: HTMLElement,
  depStatus: DepStatus
): void {
  const cards = container.querySelectorAll<HTMLElement>('.card[data-ticket-id]');
  for (const card of cards) {
    const ticketId = card.getAttribute('data-ticket-id');
    if (!ticketId) continue;

    // Remove existing icon to avoid duplicates
    card.querySelector('.dep-lock-icon')?.remove();

    const deps = depStatus[ticketId];
    if (deps && deps.length > 0) {
      const icon = document.createElement('span');
      icon.className = 'dep-lock-icon';
      icon.textContent = '\u{1F512}';
      icon.setAttribute(
        'title',
        `Blocked by: ${deps.map((id) => `Ticket #${id}`).join(', ')}`
      );
      // Insert before card-meta for visual placement
      const meta = card.querySelector('.card-meta');
      if (meta) {
        card.insertBefore(icon, meta);
      } else {
        card.appendChild(icon);
      }
    }
  }
}

export function removeDependencyIcons(container: HTMLElement): void {
  const icons = container.querySelectorAll('.dep-lock-icon');
  for (const icon of icons) {
    icon.remove();
  }
}
