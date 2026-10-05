// Empty base => same origin (the Vite dev proxy, or the API serving the built UI).
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, params, signal) {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  const query = url.searchParams.toString();
  const absolute = API_BASE + url.pathname + (query ? `?${query}` : "");
  const res = await fetch(absolute, {
    headers: { Accept: "application/json" },
    signal,
    cache: "no-store",
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  if (body === null || typeof body !== "object") {
    throw new ApiError("Invalid JSON response", res.status);
  }
  return body;
}

export function search(params, signal) {
  return request("/api/search", params, signal);
}

export function books(signal) {
  return request("/api/books", {}, signal);
}

export function health(signal) {
  return request("/api/health", {}, signal);
}
