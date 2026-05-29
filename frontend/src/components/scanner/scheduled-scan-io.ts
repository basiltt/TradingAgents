import type { ScheduledScan, CreateScheduledScanRequest } from "@/api/client";

export interface ExportedScanFile {
  version: 1;
  exported_at: string;
  scans: ExportedScan[];
}

interface ExportedScan {
  name: string;
  schedule_type: ScheduledScan["schedule_type"];
  schedule_config: ScheduledScan["schedule_config"];
  scan_config: Record<string, unknown>;
  status: ScheduledScan["status"];
  timezone: string;
}

function stripToExportable(s: ScheduledScan): ExportedScan {
  const scanConfig = { ...s.scan_config };
  delete scanConfig["llm_api_key"];
  return {
    name: s.name,
    schedule_type: s.schedule_type,
    schedule_config: s.schedule_config,
    scan_config: scanConfig,
    status: s.status,
    timezone: s.timezone,
  };
}

export function buildExportPayload(scans: ScheduledScan[]): ExportedScanFile {
  return {
    version: 1,
    exported_at: new Date().toISOString(),
    scans: scans.map(stripToExportable),
  };
}

export function downloadJson(data: ExportedScanFile, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function slugify(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return slug || "untitled";
}

export function exportSingle(scan: ScheduledScan) {
  const payload = buildExportPayload([scan]);
  downloadJson(payload, `scheduled-scan-${slugify(scan.name)}.json`);
}

export function exportAll(scans: ScheduledScan[]) {
  const payload = buildExportPayload(scans);
  downloadJson(payload, "scheduled-scans-export.json");
}

export type ImportableScan = CreateScheduledScanRequest & { _originalStatus?: string };

export interface ImportResult {
  total: number;
  toImport: ImportableScan[];
  errors: string[];
}

export function parseImportFile(text: string): ImportResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { total: 0, toImport: [], errors: ["Invalid JSON file"] };
  }

  if (typeof parsed !== "object" || parsed === null || !("version" in parsed) || !("scans" in parsed)) {
    return { total: 0, toImport: [], errors: ["Missing required fields: version, scans"] };
  }

  const file = parsed as { version: number; scans: unknown[] };
  if (file.version !== 1) {
    return { total: 0, toImport: [], errors: [`Unsupported version: ${file.version}`] };
  }

  if (!Array.isArray(file.scans)) {
    return { total: 0, toImport: [], errors: ["'scans' must be an array"] };
  }

  const toImport: ImportableScan[] = [];
  const errors: string[] = [];

  for (let i = 0; i < file.scans.length; i++) {
    const s = file.scans[i];
    if (!s || typeof s !== "object") {
      errors.push(`Scan ${i + 1}: not an object`);
      continue;
    }
    const scan = s as Record<string, unknown>;
    if (!scan.name || !scan.schedule_type || !scan.schedule_config || !scan.scan_config) {
      errors.push(`Scan ${i + 1} ("${scan.name || "unnamed"}"): missing required fields`);
      continue;
    }
    toImport.push({
      name: scan.name as string,
      schedule_type: scan.schedule_type as CreateScheduledScanRequest["schedule_type"],
      schedule_config: scan.schedule_config as CreateScheduledScanRequest["schedule_config"],
      scan_config: scan.scan_config as Record<string, unknown>,
      timezone: (scan.timezone as string) || Intl.DateTimeFormat().resolvedOptions().timeZone,
      _originalStatus: (scan.status as string) || undefined,
    });
  }

  return { total: file.scans.length, toImport, errors };
}
