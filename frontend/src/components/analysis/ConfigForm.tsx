import { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { useNavigate } from "@tanstack/react-router";
import { apiClient, type StartAnalysisRequest } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TICKER_REGEX = /^[A-Z0-9.\-^]{1,15}$/;
const PROVIDERS = ["openai", "anthropic", "google", "deepseek", "xai", "qwen", "glm", "openrouter", "azure", "ollama"] as const;

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
    control,
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
    <div className="max-w-lg mx-auto">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold">New Analysis</h1>
        <p className="text-muted-foreground mt-1">
          Configure and start a new multi-agent trading analysis.
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-base flex items-center gap-2">
            <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            Analysis Configuration
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label htmlFor="ticker" className="font-medium">
                Ticker Symbol
              </Label>
              <Input
                id="ticker"
                placeholder="e.g. AAPL, SPY, TSLA"
                className="font-mono text-base tracking-wide"
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
              {errors.ticker ? (
                <p id="ticker-error" className="text-sm text-destructive flex items-center gap-1">
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {errors.ticker.message}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Enter the stock ticker symbol to analyze</p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="analysis_date" className="font-medium">
                Analysis Date
              </Label>
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
              {errors.analysis_date ? (
                <p id="date-error" className="text-sm text-destructive flex items-center gap-1">
                  <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {errors.analysis_date.message}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Historical date for the analysis</p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="provider" className="font-medium">
                LLM Provider
              </Label>
              <Controller
                name="provider"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="provider">
                      <SelectValue placeholder="Select provider" />
                    </SelectTrigger>
                    <SelectContent>
                      {PROVIDERS.map((p) => (
                        <SelectItem key={p} value={p} className="capitalize">
                          {p}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              <p className="text-xs text-muted-foreground">AI provider for agent reasoning</p>
            </div>

            {submitError && (
              <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive flex items-start gap-2" role="alert">
                <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {submitError}
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <Button type="submit" disabled={isSubmitting} className="flex-1 font-medium">
                {isSubmitting ? (
                  <>
                    <svg className="w-4 h-4 mr-2 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Starting...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Start Analysis
                  </>
                )}
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
    </div>
  );
}
