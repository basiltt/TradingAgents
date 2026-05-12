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

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <Label htmlFor="label">Account Label</Label>
              <Input
                id="label"
                placeholder="e.g. Scalping — Demo"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={64}
              />
            </div>
            <div>
              <Label>Account Type</Label>
              <div className="flex gap-2 mt-1">
                {(["demo", "live"] as const).map((t) => (
                  <Button
                    key={t}
                    variant={accountType === t ? "default" : "outline"}
                    size="sm"
                    onClick={() => setAccountType(t)}
                  >
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </Button>
                ))}
              </div>
            </div>
            <Button
              className="w-full"
              disabled={!label.trim()}
              onClick={() => setStep(2)}
            >
              Next
            </Button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div>
              <Label htmlFor="api-key">API Key</Label>
              <Input
                id="api-key"
                placeholder="Bybit API Key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div>
              <Label htmlFor="api-secret">API Secret</Label>
              <div className="relative">
                <Input
                  id="api-secret"
                  type={showSecret ? "text" : "password"}
                  placeholder="Bybit API Secret"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground"
                  onClick={() => setShowSecret(!showSecret)}
                >
                  {showSecret ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {testResult && !testResult.success && (
              <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {testResult.error}
              </div>
            )}

            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
              <Button
                className="flex-1"
                disabled={!apiKey.trim() || !apiSecret.trim() || testing}
                onClick={handleTestAndSave}
              >
                {testing ? "Testing connection..." : "Test & Save"}
              </Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4 text-center">
            <div className="text-green-600 text-lg font-semibold">Account connected successfully!</div>
            <p className="text-sm text-muted-foreground">
              Your {accountType} account "{label}" is now active.
            </p>
            <Button className="w-full" onClick={() => handleClose(false)}>Done</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
