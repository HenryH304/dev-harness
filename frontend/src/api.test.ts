import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiFetch, apiGet, apiPost, apiPatch, apiDelete } from './api.ts';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

function mockResponse(data: unknown, status = 200): void {
  mockFetch.mockResolvedValue({
    json: () => Promise.resolve(data),
    ok: status >= 200 && status < 300,
    status,
  });
}

describe('apiFetch', () => {
  it('prepends /api to the path', async () => {
    mockResponse({ status: 'ok' });
    await apiFetch('/health');
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) })
    );
  });

  it('returns data, ok, and status', async () => {
    mockResponse({ items: [1, 2] }, 200);
    const result = await apiFetch('/items');
    expect(result.data).toEqual({ items: [1, 2] });
    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
  });

  it('returns ok=false for error responses', async () => {
    mockResponse({ error: 'not found' }, 404);
    const result = await apiFetch('/missing');
    expect(result.ok).toBe(false);
    expect(result.status).toBe(404);
  });
});

describe('apiGet', () => {
  it('uses GET method', async () => {
    mockResponse({});
    await apiGet('/tickets');
    expect(mockFetch).toHaveBeenCalledWith('/api/tickets', expect.objectContaining({ method: 'GET' }));
  });
});

describe('apiPost', () => {
  it('uses POST method with JSON body', async () => {
    mockResponse({ id: 1 }, 201);
    await apiPost('/tickets', { title: 'Test' });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/tickets',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ title: 'Test' }),
      })
    );
  });
});

describe('apiPatch', () => {
  it('uses PATCH method with JSON body', async () => {
    mockResponse({ id: 1 });
    await apiPatch('/tickets/1', { title: 'Updated' });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/tickets/1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ title: 'Updated' }),
      })
    );
  });
});

describe('apiDelete', () => {
  it('uses DELETE method', async () => {
    mockResponse({});
    await apiDelete('/tickets/1');
    expect(mockFetch).toHaveBeenCalledWith('/api/tickets/1', expect.objectContaining({ method: 'DELETE' }));
  });
});
