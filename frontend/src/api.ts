const BASE_URL = '/api';

export interface ApiResponse<T> {
  data: T;
  ok: boolean;
  status: number;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  const data = (await response.json()) as T;
  return { data, ok: response.ok, status: response.status };
}

export async function apiGet<T>(path: string): Promise<ApiResponse<T>> {
  return apiFetch<T>(path, { method: 'GET' });
}

export async function apiPost<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  return apiFetch<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  return apiFetch<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
}

export async function apiPut<T>(path: string, body: unknown): Promise<ApiResponse<T>> {
  return apiFetch<T>(path, { method: 'PUT', body: JSON.stringify(body) });
}

export async function apiDelete<T>(path: string): Promise<ApiResponse<T>> {
  return apiFetch<T>(path, { method: 'DELETE' });
}
