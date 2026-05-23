import { useState } from "react";
import { accountsApi } from "@/api/client";
import { useAppDispatch } from "@/store";
import { addAccount } from "@/store/accounts-slice";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface AddAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

export function AddAccountDialog({ open, onOpenChange, onCreated }: AddAccountDialogProps) {
  const dispatch = useAppDispatch();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [label, setLabel] = useState("");
  const [accountType, setAccountType] = useState<"demo" | "live">("demo");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string } | null>(null);

  const reset = () => {
    setStep(1);
    setLabel("");
    setAccountType("demo");
    setApiKey("");
    setApiSecret("");
    setShowSecret(false);
    setTesting(false);
    setTestResult(null);
  };

  const handleClose = (open: boolean) => {
    if (!open) reset();
    onOpenChange(open);
  };

  const handleTestAndSave = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const account = await accountsApi.create({ label, account_type: accountType, api_key: apiKey, api_secret: apiSecret });
      dispatch(addAccount(account));
      setTestResult({ success: true });
      setStep(3);
      onCreated();
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      setTestResult({ success: false, error: err.detail || err.message || "Connection failed" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add Trading Account</DialogTitle>
        </DialogHeader>

        {/* Step Indicator */}
        <div className="flex items-center justify-between px-2 mb-6">
          {[
            { num: 1, label: "Account Info" },
            { num: 2, label: "Credentials" },
            { num: 3, label: "Success" }
          ].map((s, idx) => (
            <div key={s.num} className="flex items-center flex-1 last:flex-initial">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center border font-bold text-xs transition-all duration-300 ${
                    step === s.num
                      ? "bg-primary border-primary text-primary-foreground shadow-lg shadow-primary/20 scale-105"
                      : step > s.num
                      ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
                      : "bg-muted/30 border-border/40 text-muted-foreground"
                  }`}
                >
                  {step > s.num ? (
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    s.num
                  )}
                </div>
                <span className={`text-[9px] font-black uppercase tracking-wider ${step === s.num ? "text-foreground" : "text-muted-foreground"}`}>
                  {s.label}
                </span>
              </div>
              {idx < 2 && (
                <div className={`h-[1.5px] flex-1 mx-3 rounded ${step > s.num ? "bg-emerald-500/30" : "bg-border/20"}`} />
              )}
            </div>
          ))}
        </div>

        {step === 1 && (
          <div className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="label" className="font-bold text-xs uppercase tracking-wider text-muted-foreground/80 block">Account Label</Label>
              <Input
                id="label"
                placeholder="e.g. Scalping — Demo"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={64}
                className="h-11 bg-muted/20 border-border/40 focus:border-primary/50 focus:ring-2 focus:ring-primary/10 rounded-xl px-4 text-sm font-semibold transition-all duration-200"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="font-bold text-xs uppercase tracking-wider text-muted-foreground/80 block">Account Type</Label>
              <div className="flex p-1.5 rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)]" role="radiogroup" aria-label="Account Type">
                {(["demo", "live"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="radio"
                    aria-checked={accountType === t}
                    className={`flex-1 py-2.5 rounded-[var(--neu-radius-sm)] text-xs font-black uppercase tracking-wider transition-all duration-200 cursor-pointer ${
                      accountType === t
                        ? "bg-[var(--neu-surface-raised)] text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-pill)]"
                        : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)]"
                    }`}
                    onClick={() => setAccountType(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <Button
              className="w-full h-11 rounded-xl font-bold uppercase tracking-wider text-xs cursor-pointer active:scale-95 transition-all mt-2 shadow-lg shadow-primary/15"
              disabled={!label.trim()}
              onClick={() => setStep(2)}
            >
              Next
            </Button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="api-key" className="font-bold text-xs uppercase tracking-wider text-muted-foreground/80 block">API Key</Label>
              <Input
                id="api-key"
                placeholder="Bybit API Key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoComplete="off"
                className="h-11 bg-muted/20 border-border/40 focus:border-primary/50 focus:ring-2 focus:ring-primary/10 rounded-xl px-4 text-sm font-semibold transition-all duration-200"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="api-secret" className="font-bold text-xs uppercase tracking-wider text-muted-foreground/80 block">API Secret</Label>
              <div className="relative">
                <Input
                  id="api-secret"
                  type={showSecret ? "text" : "password"}
                  placeholder="Bybit API Secret"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  autoComplete="off"
                  className="h-11 bg-muted/20 border-border/40 focus:border-primary/50 focus:ring-2 focus:ring-primary/10 rounded-xl pl-4 pr-11 text-sm font-semibold transition-all duration-200"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center justify-center w-8 h-8 rounded-lg hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground cursor-pointer"
                  onClick={() => setShowSecret(!showSecret)}
                  tabIndex={-1}
                >
                  {showSecret ? (
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            {testResult && !testResult.success && (
              <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-xs font-semibold text-destructive flex items-start gap-2.5 animate-pulse-slow">
                <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>{testResult.error}</div>
              </div>
            )}

            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => setStep(1)}
                className="h-11 px-5 rounded-xl font-bold uppercase tracking-wider text-xs border-border/50 hover:bg-muted/10 transition-all cursor-pointer active:scale-95"
              >
                Back
              </Button>
              <Button
                className="flex-1 h-11 rounded-xl font-bold uppercase tracking-wider text-xs cursor-pointer active:scale-95 transition-all shadow-lg shadow-primary/15 flex items-center justify-center gap-2"
                disabled={!apiKey.trim() || !apiSecret.trim() || testing}
                onClick={handleTestAndSave}
              >
                {testing ? (
                  <>
                    <svg className="w-4 h-4 animate-spin text-current" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Connecting...
                  </>
                ) : (
                  "Test & Save"
                )}
              </Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5 text-center py-4">
            <div className="w-16 h-16 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mx-auto glow-success animate-flash">
              <svg className="w-8 h-8 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h3 className="text-base font-bold text-foreground">Account connected successfully!</h3>
              <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                Your <span className="font-semibold text-foreground">{accountType}</span> account <span className="font-semibold text-foreground">"{label}"</span> is now active and ready to trade.
              </p>
            </div>
            <Button
              className="w-full h-11 rounded-xl font-bold uppercase tracking-wider text-xs cursor-pointer active:scale-95 transition-all shadow-lg shadow-primary/15"
              onClick={() => handleClose(false)}
            >
              Done
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
