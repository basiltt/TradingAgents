import { describe, expect, it } from "vitest";
import {
  neumorphismComponentChecklist,
  neumorphismComponentRegistry,
} from "../registry";
import { neumorphismRouteBlueprints } from "../route-blueprints";
import { neumorphismRouteLayoutModels } from "../route-models";

describe("neumorphism registry", () => {
  it("covers every required component name", () => {
    const registryNames = new Set(Object.keys(neumorphismComponentRegistry));

    for (const names of Object.values(neumorphismComponentChecklist)) {
      for (const name of names) {
        expect(registryNames.has(name)).toBe(true);
      }
    }
  });

  it("maps every audited trading route", () => {
    expect(neumorphismRouteBlueprints).toHaveLength(17);
    expect(neumorphismRouteBlueprints.map((entry) => entry.route)).toEqual([
      "/",
      "/analysis/new",
      "/analysis/$runId",
      "/history",
      "/scanner",
      "/scanner/history",
      "/scanner/schedules",
      "/scanner/$scanId",
      "/accounts",
      "/accounts/$accountId",
      "/analytics",
      "/strategies",
      "/cycles",
      "/cycles/$cycleId",
      "/config",
      "/memory",
      "/trades",
    ]);
  });

  it("keeps route layout models in sync with the audited route map", () => {
    expect(neumorphismRouteLayoutModels).toHaveLength(neumorphismRouteBlueprints.length);
    expect(neumorphismRouteLayoutModels.map((entry) => entry.route)).toEqual(
      neumorphismRouteBlueprints.map((entry) => entry.route),
    );
  });
});
