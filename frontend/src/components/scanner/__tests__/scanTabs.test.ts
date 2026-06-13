import { describe, it, expect } from "vitest";
import {
  SCANNER_CONFIG_TABS, SCANNER_RESULT_TABS, SCHEDULED_TABS,
  SCANNER_CONFIG_LABELS, SCANNER_RESULT_LABELS, SCHEDULED_LABELS,
} from "../form-tabs/scanTabs";

describe("scanTabs", () => {
  it("orders the scanner config tabs", () => {
    expect(SCANNER_CONFIG_TABS).toEqual(["scan", "analysis", "models"]);
  });
  it("orders the scanner result tabs", () => {
    expect(SCANNER_RESULT_TABS).toEqual(["results", "progress", "config"]);
  });
  it("orders the scheduled dialog tabs", () => {
    expect(SCHEDULED_TABS).toEqual(["schedule", "scan", "analysis", "models", "autotrade"]);
  });
  it("labels every id in every set (no missing/empty labels)", () => {
    for (const id of SCANNER_CONFIG_TABS) expect(SCANNER_CONFIG_LABELS[id]).toBeTruthy();
    for (const id of SCANNER_RESULT_TABS) expect(SCANNER_RESULT_LABELS[id]).toBeTruthy();
    for (const id of SCHEDULED_TABS) expect(SCHEDULED_LABELS[id]).toBeTruthy();
  });
  it("uses the same 'Models & Connection' label in both config forms", () => {
    expect(SCANNER_CONFIG_LABELS.models).toBe("Models & Connection");
    expect(SCHEDULED_LABELS.models).toBe("Models & Connection");
  });
  it("uses identical Scan/Analysis labels across both forms (family consistency)", () => {
    expect(SCHEDULED_LABELS.scan).toBe(SCANNER_CONFIG_LABELS.scan);
    expect(SCHEDULED_LABELS.analysis).toBe(SCANNER_CONFIG_LABELS.analysis);
  });
});
