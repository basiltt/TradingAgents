import { createSelector } from "@reduxjs/toolkit";
import type { RootState } from "@/store";

export const makeSelectLLMCalls = (accountId: string) =>
  createSelector(
    (s: RootState) => s.aiManager.llmCallsByAccount[accountId],
    (calls) => calls || []
  );

export const makeSelectInFlightCalls = (accountId: string) =>
  createSelector(
    (s: RootState) => s.aiManager.inFlightCalls[accountId],
    (calls) => calls || []
  );

export const makeSelectCapabilities = (accountId: string) =>
  createSelector(
    (s: RootState) => s.aiManager.capabilitiesByAccount[accountId],
    (caps) => caps || []
  );

export const makeSelectInsights = (accountId: string) =>
  createSelector(
    (s: RootState) => s.aiManager.insightsByAccount[accountId],
    (insight) => insight || null
  );

export const makeSelectAttention = (accountId: string) =>
  createSelector(
    (s: RootState) => s.aiManager.attentionByAccount[accountId],
    (items) => (items || []).filter(i => !i.dismissed)
  );
