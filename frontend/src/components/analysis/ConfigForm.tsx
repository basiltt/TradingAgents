import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "@tanstack/react-router";
import { apiClient, type StartAnalysisRequest } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TICKER_REGEX = /^[A-Z0-9.\-^]{1,15}$/;
const PROVIDERS = ["openai", "anthropic", "google", "deepseek", "xai", "qwen", "glm", "openrouter"] as const;

interface FormValues {
  ticker: string;
  analysis_date: string;
  provider: string;
}

export function ConfigForm() {
  const navigate = useNavigate();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: {
      ticker: "",
      analysis_date: "",
      provider: "openai",
    },
  });

  async function onSubmit(data: FormValues) {
    setSubmitError(null);
    try {
      const body: StartAnalysisRequest = {
        ticker: data.ticker.toUpperCase(),
        analysis_date: data.analysis_date,
        provider: data.provider || undefined,
      };
      const result = await apiClient.startAnalysis(body);
      navigate({ to: "/analysis/$runId", params: { runId: result.run_id } });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    }
  }

  return (
    <Card className="max-w-lg mx-auto">
      <CardHeader>
        <CardTitle>New Analysis</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ticker">Ticker</Label>
            <Input
              id="ticker"
              placeholder="SPY"
              aria-invalid={!!errors.ticker}
              aria-describedby={errors.ticker ? "ticker-error" : undefined}
              {...register("ticker", {
                required: "Ticker is required",
                pattern: {
                  value: TICKER_REGEX,
                  message: "Enter a valid ticker (1-15 chars: A-Z, 0-9, . - ^)",
                },
                onChange: (e) => {
                  setValue("ticker", e.target.value.toUpperCase(), { shouldValidate: false });
                },
              })}
            />
            {errors.ticker && (
              <p id="ticker-error" className="text-sm text-destructive">{errors.ticker.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="analysis_date">Analysis Date</Label>
            <Input
              id="analysis_date"
              type="date"
              max={new Date().toISOString().split("T")[0]}
              aria-invalid={!!errors.analysis_date}
              aria-describedby={errors.analysis_date ? "date-error" : undefined}
              {...register("analysis_date", {
                required: "Date is required",
                validate: (v) => v <= new Date().toISOString().split("T")[0] || "Date cannot be in the future",
              })}
            />
            {errors.analysis_date && (
              <p id="date-error" className="text-sm text-destructive">{errors.analysis_date.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider">Provider</Label>
            <Select
              defaultValue="openai"
              onValueChange={(v) => setValue("provider", v)}
            >
              <SelectTrigger id="provider">
                <SelectValue placeholder="Select provider" />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {submitError && (
            <p className="text-sm text-destructive" role="alert">{submitError}</p>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting} className="flex-1">
              {isSubmitting ? "Starting…" : "Start Analysis"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate({ to: "/" })}
            >
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
