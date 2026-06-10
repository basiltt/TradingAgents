import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { accountsApi, backtestApi, scheduledScansApi } from "@/api/client";
import type { BacktestCreateRequest } from "./types";
import { BacktestConfigForm, type ScheduleOption } from "./BacktestConfigForm";

export interface BacktestNewFormProps {
  seed?: Partial<BacktestCreateRequest>;
  onCreated: (runId: string) => void;
}

/**
 * Glue between the pure BacktestConfigForm and the create-mutation + navigation.
 * Kept separate so the form stays presentational and testable in isolation.
 * Also supplies the schedule picker options for the "Specific schedule" signal
 * source mode, and the accounts list for the "Replay" mode picker.
 */
export function BacktestNewForm({ seed, onCreated }: BacktestNewFormProps) {
  const schedulesQuery = useQuery({
    queryKey: ["scheduled-scans", "options"],
    queryFn: ({ signal }) => scheduledScansApi.list(signal),
    staleTime: 60_000,
  });

  const schedules: ScheduleOption[] = (schedulesQuery.data?.schedules ?? []).map((s) => ({
    value: s.id,
    label: s.name,
  }));

  // Accounts for the Replay source picker (DashboardCard carries ai_manager_state,
  // which drives the AI-Manager note in the form).
  const accountsQuery = useQuery({
    queryKey: ["accounts", "dashboard"],
    queryFn: ({ signal }) => accountsApi.getDashboard(undefined, signal),
    staleTime: 60_000,
  });
  const accounts = accountsQuery.data ?? [];

  const createMutation = useMutation({
    mutationFn: (body: BacktestCreateRequest) => backtestApi.create(body),
    onSuccess: (res) => {
      toast.success("Backtest started");
      onCreated(res.run_id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to start backtest");
    },
  });

  return (
    <BacktestConfigForm
      seed={seed}
      schedules={schedules}
      accounts={accounts}
      isSubmitting={createMutation.isPending}
      onSubmit={(request) => createMutation.mutate(request)}
    />
  );
}
