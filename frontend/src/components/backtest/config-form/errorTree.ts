/**
 * Helpers for reading react-hook-form's nested `errors` object by dotted field
 * path. Extracted so the four places that previously hand-rolled this walk
 * (fieldError, tabErrorCount, the invalid-submit tab router, and the validation
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

/** Depth-first walk over every leaf (a node carrying a string `message`) under
 *  `node`, invoking `onLeaf(path, message)` for each. Skips RHF's `ref`/`types`
 *  metadata. Returns false from `onLeaf` to stop early. The single recursion shared
 *  by hasErrorAt and collectErrors so they can't diverge. */
function walkLeaves(
  node: ErrorNode,
  onLeaf: (path: string[], message: string) => boolean | void,
  path: string[] = [],
): boolean {
  if (!node || typeof node !== "object") return true;
  const record = node as Record<string, unknown>;
  if (typeof record.message === "string") {
    return onLeaf(path, record.message) !== false;
  }
  for (const [key, value] of Object.entries(record)) {
    if (key === "ref" || key === "types") continue;
    if (walkLeaves(value, onLeaf, [...path, key]) === false) return false;
  }
  return true;
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
  let found = false;
  walkLeaves(descend(root, path), () => {
    found = true;
    return false; // stop at the first leaf
  });
  return found;
}

/** Walk the whole error tree, returning every `{ path, message }` leaf. The caller
 *  formats/dedupes; this only flattens. */
export function collectErrors(root: ErrorNode): Array<{ path: string; message: string }> {
  const out: Array<{ path: string; message: string }> = [];
  walkLeaves(root, (path, message) => {
    out.push({ path: path.join("."), message });
  });
  return out;
}
