/** @typedef {Record<string, unknown>} Json */

import { meta, runFromBody } from "./cascade/api.js";

/**
 * @returns {Promise<Json>}
 */
export async function fetchMeta() {
  return meta();
}

/**
 * @param {Json} body
 * @param {AbortSignal} [signal]
 * @returns {Promise<Json>}
 */
export async function runCascade(body, signal) {
  if (signal?.aborted) {
    const err = new Error("Aborted");
    err.name = "AbortError";
    throw err;
  }
  return runFromBody(/** @type {Record<string, any>} */ (body));
}

/**
 * @param {Record<string, string | number | null | undefined>} step
 */
export function cleanStep(step) {
  /** @type {Record<string, string | number>} */
  const out = { media: String(step.media || "X") };
  for (const [k, v] of Object.entries(step)) {
    if (k === "media" || k === "id") continue;
    if (v === "" || v === null || v === undefined) continue;
    const n = Number(v);
    if (!Number.isNaN(n)) out[k] = n;
  }
  return out;
}
