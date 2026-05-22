import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";
import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "neu-input-base neu-focus-ring h-11 w-full min-w-0 rounded-[var(--neu-radius-md)] px-4 py-2 text-sm text-[var(--neu-text-strong)] outline-none placeholder:text-[color:var(--neu-text-soft)] file:border-0 file:bg-transparent file:text-xs file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
