import { invoke } from "@tauri-apps/api/core";

export class ApiError extends Error {
  constructor(message, status = 500) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function cleanParams(params = {}) {
  const out = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      out[key] = value;
    }
  }
  return out;
}

export async function search(params, _signal) {
  try {
    return await invoke("search", { req: cleanParams(params) });
  } catch (err) {
    throw new ApiError(String(err), 500);
  }
}

export async function books() {
  try {
    return await invoke("books");
  } catch (err) {
    throw new ApiError(String(err), 500);
  }
}

export async function health() {
  try {
    return await invoke("health");
  } catch (err) {
    return { status: "degraded", verses: null, db: String(err) };
  }
}
