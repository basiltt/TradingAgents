/**
 * Helpers for reading react-hook-form's nested `errors` object by dotted field
 * path. Extracted so the four places that previously hand-rolled this walk
 * (fieldError, fieldHasError, the invalid-submit tab router, and the validation
 * summary) share one implementation and cannot drift.
 *
 * The `errors` tree is a plain nested object: leaf fields carry a `{ message }`,
 * intermediate nodes nest further. RHF also attaches `ref`/`types` metadata keys
 * we must skip when recursing.
 */

type ErrorNode = unknown;

/** Descend `root` by the dotted `path` (e.g. "scan_source.mode"). Returns the node
 *  at that path, or undefined if any segment is missing. */
function descend(root: ErrorNode, path: string): ErrorNode {
  let node: ErrorNode = root;
  for (const part of path.split(".")) {
    if (node && typeof node === "object" && part in node) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return node;
}

/** The validation message at exactly `path` (leaf only), or undefined. */
export function errorMessageAt(root: ErrorNode, path: string): string | undefined {
  const node = descend(root, path);
  if (node && typeof node === "object" && "message" in node) {
    return String((node as { message?: unknown }).message ?? "");
  }
  return undefined;
}

/** True if `path` OR any nested descendant under it carries a message. Handles both
 *  leaf fields and subtrees (e.g. "scan_source" → "scan_source.mode"). */
export function hasErrorAt(root: ErrorNode, path: string): boolean {
  const start = descend(root, path);
  if (!start || typeof start !== "object") return false;
  let found = false;
  const visit = (n: ErrorNode) => {
    if (found || !n || typeof n !== "object") return;
    if (typeof (n as { message?: unknown }).message === "string") {
      found = true;
      return;
    }
    for (const [k, v] of Object.entries(n as Record<string, unknown>)) {
      if (k === "ref" || k === "types") continue;
      visit(v);
    }
  };
  visit(start);
  return found;
}

/** Walk the whole error tree, returning every `[dottedPath, message]` leaf. The
 *  caller formats/dedupes; this only flattens. */
export function collectErrors(root: ErrorNode): Array<{ path: string; message: string }> {
  const out: Array<{ path: string; message: string }> = [];
  const visit = (node: ErrorNode, path: string[]) => {
    if (!node || typeof node !== "object") return;
    const record = node as Record<string, unknown>;
    if (typeof record.message === "string") {
      out.push({ path: path.join("."), message: record.message });
      return;
    }
    for (const [key, value] of Object.entries(record)) {
      if (key === "ref" || key === "types") continue;
      visit(value, [...path, key]);
    }
  };
  visit(root, []);
  return out;
}
