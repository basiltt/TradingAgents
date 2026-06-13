import type { Control } from "react-hook-form";
import type { BacktestConfigFormValues } from "../configSchema";

/** A schedule option for the scan-source picker. Moved here so the tab components
 *  and the shell share one definition. */
export interface ScheduleOption {
  value: string;
  label: string;
}

/** Base props every tab component receives. The shell owns the RHF instance and
 *  passes `control` + the `fieldError` accessor down; tabs are presentational. */
export interface TabProps {
  control: Control<BacktestConfigFormValues>;
  fieldError: (path: string) => string | undefined;
}
