import {
  cloneElement,
  isValidElement,
  useMemo,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cva } from "class-variance-authority";
import {
  CalendarDays,
  Check,
  CheckCheck,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import { Combobox } from "@/components/ui/combobox";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { NeuDivider, NeuSurface, NeuWell } from "./foundation";
import type { NeuOption, NeuTone } from "./types";

function slotButton({
  asChild,
  children,
  className,
  style,
  props,
}: {
  asChild?: boolean;
  children: ReactNode;
  className: string;
  style?: CSSProperties;
  props: ButtonHTMLAttributes<HTMLButtonElement>;
}) {
  if (asChild && isValidElement(children)) {
    const child = children as ReactElement<{ className?: string; style?: CSSProperties }>;
    return cloneElement(child, {
      ...props,
      className: cn(child.props.className, className),
      style: { ...style, ...child.props.style },
    });
  }

  return (
    <button {...props} className={className} style={style}>
      {children}
    </button>
  );
}

const buttonVariants = cva(
  "neu-focus-ring inline-flex items-center justify-center gap-2 font-semibold tracking-[-0.01em] transition duration-150 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "neu-surface-base neu-button-primary neu-interactive",
        secondary: "neu-surface-base neu-button-secondary neu-interactive",
        ghost:
          "neu-surface-base neu-button-ghost neu-interactive hover:text-[var(--neu-text-strong)]",
        danger: "neu-surface-base neu-button-danger neu-interactive",
        "soft-tonal": "neu-surface-base neu-button-tonal neu-interactive",
      },
      size: {
        sm: "h-10 rounded-[var(--neu-radius-sm)] px-3.5 text-sm sm:h-9",
        md: "h-12 rounded-[var(--neu-radius-md)] px-4.5 text-sm sm:h-11",
        lg: "h-14 rounded-[var(--neu-radius-md)] px-5 text-base sm:h-12",
        icon: "size-12 rounded-[var(--neu-radius-md)] p-0 sm:size-11",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

function fieldToneStyle(error?: string, success?: boolean): CSSProperties | undefined {
  if (error) {
    return {
      borderColor: "color-mix(in oklch, var(--neu-danger) 38%, var(--neu-stroke-soft))",
    };
  }

  if (success) {
    return {
      borderColor: "color-mix(in oklch, var(--neu-success) 38%, var(--neu-stroke-soft))",
    };
  }

  return undefined;
}

function FieldFrame({
  label,
  helperText,
  error,
  required,
  children,
}: {
  label?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="space-y-3">
      {label ? (
        <div className="flex items-center justify-between gap-3">
          <label className="text-sm font-semibold tracking-[0.01em]" style={{ color: "var(--neu-text-strong)" }}>
            {label}
            {required ? (
              <span className="ml-1 text-xs uppercase tracking-[0.18em]" style={{ color: "var(--neu-danger)" }}>
                req
              </span>
            ) : null}
          </label>
          {error ? (
            <span className="text-xs font-semibold" style={{ color: "var(--neu-danger)" }}>
              {error}
            </span>
          ) : null}
        </div>
      ) : null}
      {children}
      {!error && helperText ? (
        <p className="text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
          {helperText}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs leading-5" style={{ color: "var(--neu-danger)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function NeuButton({
  variant = "secondary",
  size = "md",
  icon,
  iconPosition = "start",
  loading = false,
  pressed = false,
  asChild,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "soft-tonal";
  size?: "sm" | "md" | "lg" | "icon";
  icon?: ReactNode;
  iconPosition?: "start" | "end";
  loading?: boolean;
  pressed?: boolean;
  asChild?: boolean;
}) {
  const content = (
    <>
      {loading ? <LoaderCircle className="size-4 animate-spin" /> : iconPosition === "start" ? icon : null}
      {children}
      {!loading && iconPosition === "end" ? icon : null}
    </>
  );

  return slotButton({
    asChild,
    props,
    className: cn(buttonVariants({ variant, size }), pressed && "neu-pressed", className),
    children: content,
  });
}

export function NeuIconButton({
  icon,
  label,
  tone = "neutral",
  disabled,
  className,
  ...props
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  icon: ReactNode;
  label: string;
  tone?: NeuTone;
}) {
  return (
    <NeuButton
      aria-label={label}
      size="icon"
      variant={tone === "danger" ? "danger" : tone === "accent" ? "primary" : "secondary"}
      disabled={disabled}
      className={className}
      {...props}
    >
      {icon}
    </NeuButton>
  );
}

export function NeuInput({
  label,
  leadingIcon,
  trailing,
  helperText,
  error,
  required,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label?: ReactNode;
  leadingIcon?: ReactNode;
  trailing?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
}) {
  return (
    <FieldFrame label={label} helperText={helperText} error={error} required={required}>
        <div
          className={cn(
          "neu-input-base neu-focus-ring flex min-h-12 items-center gap-2 rounded-[var(--neu-radius-md)] px-4 py-0.5 sm:min-h-11",
          className,
        )}
        style={fieldToneStyle(typeof error === "string" ? error : undefined)}
      >
        {leadingIcon ? <span className="inline-flex items-center justify-center" style={{ color: "var(--neu-text-muted)" }}>{leadingIcon}</span> : null}
        <input
          {...props}
          required={required}
          className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[color:var(--neu-text-soft)]"
          style={{ color: "var(--neu-text-strong)" }}
        />
        {trailing ? <span style={{ color: "var(--neu-text-muted)" }}>{trailing}</span> : null}
      </div>
    </FieldFrame>
  );
}

export function NeuTextArea({
  label,
  helperText,
  error,
  className,
  rows = 4,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
}) {
  return (
    <FieldFrame label={label} helperText={helperText} error={error}>
      <textarea
        {...props}
        rows={rows}
        className={cn(
          "neu-input-base neu-focus-ring neu-scrollbar min-h-28 w-full resize-y rounded-[var(--neu-radius-md)] px-4 py-3.5 text-sm outline-none placeholder:text-[color:var(--neu-text-soft)]",
          className,
        )}
        style={{ ...fieldToneStyle(typeof error === "string" ? error : undefined), color: "var(--neu-text-strong)" }}
      />
    </FieldFrame>
  );
}

function groupOptions(options: NeuOption[]) {
  return options.reduce<Record<string, NeuOption[]>>((groups, option) => {
    const key = option.group ?? "";
    groups[key] = [...(groups[key] ?? []), option];
    return groups;
  }, {});
}

export function NeuSelect({
  label,
  options,
  value,
  onChange,
  placeholder = "Select an option",
  searchable = false,
  renderOption,
  helperText,
  error,
  disabled,
}: {
  label?: ReactNode;
  options: NeuOption[];
  value?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  searchable?: boolean;
  renderOption?: (option: NeuOption) => ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    if (!searchable || !query.trim()) return options;

    const normalized = query.toLowerCase();
    return options.filter((option) =>
      [option.label, option.description, ...(option.searchKeywords ?? [])]
        .filter(Boolean)
        .some((candidate) => String(candidate).toLowerCase().includes(normalized)),
    );
  }, [options, query, searchable]);

  const grouped = groupOptions(filtered);

  return (
    <FieldFrame label={label} helperText={helperText} error={error}>
      <Select value={value} onValueChange={(next) => next && onChange(next)} disabled={disabled}>
        <SelectTrigger
          className="neu-input-base neu-focus-ring h-12 w-full rounded-[var(--neu-radius-md)] px-4 sm:h-11"
          style={fieldToneStyle(typeof error === "string" ? error : undefined)}
        >
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent className="neu-surface-base neu-surface-raised w-[min(24rem,var(--anchor-width))] rounded-[var(--neu-radius-lg)] border-0 p-2 shadow-none">
          {searchable ? (
            <div className="pb-2">
              <div className="neu-input-base flex items-center gap-2 rounded-[var(--neu-radius-sm)] px-3.5">
                <Search className="size-4" style={{ color: "var(--neu-text-muted)" }} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Filter options"
                  className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[color:var(--neu-text-soft)]"
                />
              </div>
            </div>
          ) : null}

          {Object.entries(grouped).map(([group, groupOptions]) => (
            <SelectGroup key={group || "ungrouped"}>
              {group ? <SelectLabel>{group}</SelectLabel> : null}
              {groupOptions.map((option) => (
                <SelectItem
                  key={option.value}
                  value={option.value}
                  className="rounded-[var(--neu-radius-sm)] px-3 py-2.5 data-highlighted:bg-[color-mix(in_oklch,var(--neu-highlight)_10%,var(--neu-surface-raised))] data-highlighted:text-[var(--neu-text-strong)] data-highlighted:shadow-[var(--neu-shadow-pill)]"
                >
                  {renderOption ? renderOption(option) : option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
}

export function NeuMultiSelect({
  label,
  options,
  value,
  onChange,
  maxVisibleTags = 3,
  helperText,
}: {
  label?: ReactNode;
  options: NeuOption[];
  value: string[];
  onChange: (next: string[]) => void;
  maxVisibleTags?: number;
  helperText?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    if (!query.trim()) return options;
    const normalized = query.toLowerCase();
    return options.filter((option) =>
      [option.label, option.description, ...(option.searchKeywords ?? [])]
        .filter(Boolean)
        .some((candidate) => String(candidate).toLowerCase().includes(normalized)),
    );
  }, [options, query]);

  const selected = options.filter((option) => value.includes(option.value));

  return (
    <FieldFrame label={label} helperText={helperText}>
      <NeuSurface depth="raised" radius="md" padding="sm" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {selected.slice(0, maxVisibleTags).map((option) => (
            <span
              key={option.value}
              className="neu-surface-base neu-surface-raised neu-pill-soft inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] px-3 py-1.5 text-xs font-semibold"
              style={{
                color: "var(--neu-accent-ink)",
                background: "color-mix(in oklch, var(--neu-accent-muted) 84%, var(--neu-surface-raised))",
                borderColor: "color-mix(in oklch, var(--neu-accent) 22%, var(--neu-stroke-soft))",
              }}
            >
              {option.label}
              <button
                type="button"
                className="neu-focus-ring rounded-full"
                onClick={() => onChange(value.filter((entry) => entry !== option.value))}
                aria-label={`Remove ${option.label}`}
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          {selected.length > maxVisibleTags ? (
            <span className="text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
              +{selected.length - maxVisibleTags} more
            </span>
          ) : null}
        </div>

        <NeuInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter options"
          leadingIcon={<Search className="size-4" />}
        />

        <NeuWell padding="sm" className="max-h-48 space-y-2 overflow-auto">
          {filtered.map((option) => {
            const active = value.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                onClick={() =>
                  onChange(
                    active
                      ? value.filter((entry) => entry !== option.value)
                      : [...value, option.value],
                  )
                }
                className={cn(
                  "neu-focus-ring flex w-full items-start gap-3 rounded-[var(--neu-radius-sm)] border px-3 py-2.5 text-left transition",
                  active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-raised neu-interactive",
                )}
              >
                <span
                  className={cn(
                    "neu-surface-base mt-0.5 inline-flex size-5 items-center justify-center rounded-full",
                    active ? "neu-surface-accent text-[var(--neu-accent-ink)]" : "neu-surface-inset bg-transparent",
                  )}
                  style={{ borderColor: "var(--neu-stroke-soft)" }}
                >
                  {active ? <Check className="size-3" /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{option.label}</span>
                  {option.description ? (
                    <span className="mt-1 block text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
                      {option.description}
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
        </NeuWell>
      </NeuSurface>
    </FieldFrame>
  );
}

export function NeuCombobox({
  label,
  options,
  value,
  onChange,
  loading,
  disabled,
  allowCustom,
  helperText,
}: {
  label?: ReactNode;
  options: string[];
  value: string;
  onChange: (value: string) => void;
  loading?: boolean;
  disabled?: boolean;
  allowCustom?: boolean;
  helperText?: ReactNode;
}) {
  return (
    <FieldFrame label={label} helperText={helperText}>
      <div className="neu-input-base rounded-[var(--neu-radius-md)] p-1.5">
        <Combobox
          options={options}
          value={value}
          onChange={onChange}
          loading={loading}
          disabled={disabled}
          placeholder={allowCustom ? "Search or type a custom value" : "Search values"}
          className="[&_input]:border-0 [&_input]:bg-transparent [&_input]:shadow-none"
        />
      </div>
    </FieldFrame>
  );
}

export function NeuToggleGroup({
  label,
  options,
  value,
  onChange,
  size = "md",
}: {
  label?: ReactNode;
  options: Array<{ value: string; label: ReactNode; icon?: ReactNode }>;
  value: string | string[];
  onChange: (next: string | string[]) => void;
  size?: "sm" | "md";
}) {
  const isMulti = Array.isArray(value);

  return (
    <FieldFrame label={label}>
      <div className="neu-surface-base neu-surface-inset flex flex-wrap gap-2 rounded-[var(--neu-radius-md)] p-2.5">
        {options.map((option) => {
          const active = isMulti ? value.includes(option.value) : value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                if (isMulti) {
                  const next = active
                    ? value.filter((entry) => entry !== option.value)
                    : [...value, option.value];
                  onChange(next);
                } else {
                  onChange(option.value);
                }
              }}
              className={cn(
                "neu-focus-ring inline-flex items-center gap-2 font-semibold transition",
                active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-raised neu-interactive",
                size === "sm"
                  ? "h-10 rounded-[var(--neu-radius-sm)] px-3.5 text-xs sm:h-9"
                  : "h-11 rounded-[var(--neu-radius-md)] px-4.5 text-sm sm:h-10",
              )}
            >
              {option.icon}
              {option.label}
            </button>
          );
        })}
      </div>
    </FieldFrame>
  );
}

export function NeuTabs({
  value,
  onValueChange,
  items,
  orientation = "horizontal",
  variant = "pill",
}: {
  value: string;
  onValueChange: (value: string) => void;
  items: Array<{ value: string; label: ReactNode; icon?: ReactNode; content: ReactNode }>;
  orientation?: "horizontal" | "vertical";
  variant?: "pill" | "line" | "inset";
}) {
  const mappedVariant = variant === "line" ? "line" : "default";

  return (
    <Tabs value={value} onValueChange={onValueChange} orientation={orientation}>
      <TabsList
        variant={mappedVariant}
        className={cn(
          variant === "inset" && "neu-surface-base neu-surface-inset rounded-[var(--neu-radius-md)] p-2.5",
          variant === "pill" && "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] p-1.5",
        )}
      >
        {items.map((item) => (
          <TabsTrigger
            key={item.value}
            value={item.value}
            className="rounded-[var(--neu-radius-sm)] px-3.5 py-2 data-[active]:border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))] data-[active]:bg-[linear-gradient(145deg,color-mix(in_oklch,var(--neu-highlight)_30%,var(--neu-accent-muted)),color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))_48%,color-mix(in_oklch,var(--neu-accent-muted)_86%,var(--neu-surface-raised)))] data-[active]:text-[var(--neu-accent-ink)] data-[active]:shadow-[var(--neu-shadow-pill)]"
          >
            {item.icon}
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>

      {items.map((item) => (
        <TabsContent key={item.value} value={item.value} className="mt-4">
          {item.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}

export function NeuCheckbox({
  label,
  checked,
  onCheckedChange,
  description,
  disabled,
  accent = "accent",
}: {
  label: ReactNode;
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean | "indeterminate") => void;
  description?: ReactNode;
  disabled?: boolean;
  accent?: "accent" | "success" | "warning";
}) {
  const isChecked = checked === true;
  const isIndeterminate = checked === "indeterminate";

  const accentTrackColor = {
    accent: "bg-[var(--neu-accent)] border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))]",
    success: "bg-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_22%,var(--neu-stroke-soft))]",
    warning: "bg-[var(--neu-warning)] border-[color:color-mix(in_oklch,var(--neu-warning)_22%,var(--neu-stroke-soft))]",
  }[accent];

  const accentTextColor = {
    accent: "text-[var(--neu-accent)]",
    success: "text-[var(--neu-success)]",
    warning: "text-[var(--neu-warning)]",
  }[accent];

  return (
    <div className={cn("flex items-start gap-3 p-1", disabled && "opacity-50 pointer-events-none")}>
      <button
        type="button"
        role="checkbox"
        aria-checked={checked === "indeterminate" ? "mixed" : checked}
        disabled={disabled}
        onClick={() => onCheckedChange(checked === "indeterminate" ? true : !checked)}
        className={cn(
          "mt-0.5 flex size-5.5 shrink-0 items-center justify-center rounded-[6px] border transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--neu-accent)] shadow-[var(--neu-shadow-inset)]",
          isChecked || isIndeterminate
            ? accentTrackColor
            : "bg-[var(--neu-surface-deep)] border-[color:var(--neu-stroke-soft)]"
        )}
      >
        {(isChecked || isIndeterminate) && (
          <span className={cn("flex size-4 items-center justify-center rounded-[4px] bg-white shadow-[var(--neu-shadow-pill)] transition-transform duration-200", accentTextColor)}>
            {isChecked ? (
              <Check className="size-3.5 stroke-[3px]" />
            ) : (
              <span className="h-0.5 w-2 bg-current rounded-full" />
            )}
          </span>
        )}
      </button>
      {(label || description) && (
        <div className="flex flex-col gap-0.5">
          {label && <span className="text-sm font-semibold tracking-[0.01em]" style={{ color: "var(--neu-text-strong)" }}>{label}</span>}
          {description && <span className="text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>{description}</span>}
        </div>
      )}
    </div>
  );
}

export function NeuRadioGroup({
  label,
  options,
  value,
  onChange,
  orientation = "vertical",
  accent = "accent",
}: {
  label?: ReactNode;
  options: Array<{ value: string; label: ReactNode; description?: ReactNode }>;
  value: string;
  onChange: (value: string) => void;
  orientation?: "horizontal" | "vertical";
  accent?: "accent" | "success" | "warning";
}) {
  return (
    <FieldFrame label={label}>
      <div className={cn("grid gap-2", orientation === "horizontal" ? "sm:grid-cols-2" : "grid-cols-1")}>
        {options.map((option) => {
          const active = option.value === value;
          const accentTrackColor = {
            accent: "bg-[var(--neu-accent)] border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))]",
            success: "bg-[var(--neu-success)] border-[color:color-mix(in_oklch,var(--neu-success)_22%,var(--neu-stroke-soft))]",
            warning: "bg-[var(--neu-warning)] border-[color:color-mix(in_oklch,var(--neu-warning)_22%,var(--neu-stroke-soft))]",
          }[accent];

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={cn(
                "neu-focus-ring flex min-h-14 items-start gap-3 rounded-[var(--neu-radius-md)] border px-3.5 py-3 text-left transition",
                active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-raised neu-interactive",
              )}
            >
              <span
                className={cn(
                  "mt-1 flex size-5.5 shrink-0 items-center justify-center rounded-full border transition-colors duration-200 shadow-[var(--neu-shadow-inset)]",
                  active
                    ? accentTrackColor
                    : "bg-[var(--neu-surface-deep)] border-[color:var(--neu-stroke-soft)]"
                )}
              >
                {active && (
                  <span className="size-2.5 rounded-full bg-white shadow-[var(--neu-shadow-pill)]" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">{option.label}</span>
                {option.description ? (
                  <span className="mt-1 block text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
                    {option.description}
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    </FieldFrame>
  );
}

export function NeuSlider({
  label,
  value,
  min,
  max,
  step = 1,
  onValueChange,
  marks,
  accent = "accent",
}: {
  label?: ReactNode;
  value: number | [number, number];
  min: number;
  max: number;
  step?: number;
  onValueChange: (value: number | [number, number]) => void;
  marks?: number[];
  accent?: "accent" | "success" | "warning";
}) {
  const isRange = Array.isArray(value);
  const values = isRange ? value : [value];

  return (
    <FieldFrame label={label}>
      <NeuSurface depth="inset" radius="md" padding="sm" className="space-y-3">
        {values.map((entry, index) => {
          const pct = ((entry - min) / (max - min)) * 100;
          const accentVar = {
            accent: "var(--neu-accent)",
            success: "var(--neu-success)",
            warning: "var(--neu-warning)",
          }[accent];
          const trackBg = `linear-gradient(to right, ${accentVar} 0%, ${accentVar} ${pct}%, var(--neu-surface-deep) ${pct}%, var(--neu-surface-deep) 100%)`;

          return (
            <div key={index} className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold">
                <span style={{ color: "var(--neu-text-muted)" }}>{isRange ? (index === 0 ? "Minimum" : "Maximum") : "Value"}</span>
                <span>{entry}</span>
              </div>
              <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={entry}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (!isRange) {
                    onValueChange(next);
                    return;
                  }

                  const current: [number, number] = [...value] as [number, number];
                  current[index] = next;
                  onValueChange(current[0] <= current[1] ? current : [current[1], current[0]]);
                }}
                className="neu-slider h-5 w-full cursor-pointer bg-transparent"
                style={
                  {
                    "--slider-track-bg": trackBg,
                    accentColor: accentVar,
                  } as CSSProperties
                }
              />
            </div>
          );
        })}
        {marks?.length ? (
          <div className="flex items-center justify-between gap-2 text-[11px] font-medium" style={{ color: "var(--neu-text-soft)" }}>
            {marks.map((mark) => (
              <span key={mark}>{mark}</span>
            ))}
          </div>
        ) : null}
      </NeuSurface>
    </FieldFrame>
  );
}

export function NeuDateField({
  label,
  value,
  onChange,
  min,
  max,
  error,
}: {
  label?: ReactNode;
  value?: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  error?: ReactNode;
}) {
  return (
    <NeuInput
      type="date"
      label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      min={min}
      max={max}
      error={error}
      leadingIcon={<CalendarDays className="size-4" />}
    />
  );
}

export function NeuModelPicker({
  label,
  provider,
  options,
  value,
  onChange,
  remote = false,
  loading = false,
  error,
  recents = [],
}: {
  label?: ReactNode;
  provider: string;
  options: NeuOption[];
  value?: string;
  onChange: (value: string) => void;
  remote?: boolean;
  loading?: boolean;
  error?: ReactNode;
  recents?: string[];
}) {
  return (
    <NeuSurface depth="raised" radius="md" padding="sm" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {label ? <span className="text-sm font-semibold">{label}</span> : null}
        <span className="neu-surface-base neu-surface-raised neu-pill-soft rounded-[var(--neu-radius-pill)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]">
          {provider}
        </span>
        <span
          className={cn(
            "neu-surface-base neu-pill-soft rounded-[var(--neu-radius-pill)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]",
            remote ? "neu-surface-accent" : "neu-surface-raised",
          )}
          style={{
            color: remote ? "var(--neu-accent-ink)" : "var(--neu-text-muted)",
          }}
        >
          {remote ? "remote" : "local"}
        </span>
        {loading ? <LoaderCircle className="size-4 animate-spin" /> : null}
      </div>

      <NeuSelect
        options={options}
        value={value}
        onChange={onChange}
        placeholder="Select a model"
        searchable
        error={error}
      />

      {recents.length ? (
        <>
          <NeuDivider />
          <div className="flex flex-wrap gap-2">
            {recents.map((recent) => (
              <NeuButton key={recent} variant="soft-tonal" size="sm" onClick={() => onChange(recent)}>
                <CheckCheck className="size-3.5" />
                {recent}
              </NeuButton>
            ))}
          </div>
        </>
      ) : null}
    </NeuSurface>
  );
}

export interface NeuAccountPickerOption {
  id: string;
  label: string;
  subtitle?: string;
  included?: boolean;
  meta?: ReactNode;
}

export function NeuAccountPicker({
  accounts,
  selectedAccount,
  onSelect,
  onToggleInclusion,
  searchable = true,
}: {
  accounts: NeuAccountPickerOption[];
  selectedAccount?: string;
  onSelect: (accountId: string) => void;
  onToggleInclusion?: (accountId: string) => void;
  searchable?: boolean;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    if (!searchable || !query.trim()) return accounts;
    const normalized = query.toLowerCase();
    return accounts.filter((account) =>
      [account.label, account.subtitle]
        .filter(Boolean)
        .some((candidate) => String(candidate).toLowerCase().includes(normalized)),
    );
  }, [accounts, query, searchable]);

  return (
    <NeuSurface depth="raised" radius="md" padding="sm" className="space-y-3">
      {searchable ? (
        <NeuInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search accounts"
          leadingIcon={<Search className="size-4" />}
        />
      ) : null}

      <NeuWell padding="sm" className="max-h-60 space-y-2 overflow-auto">
        {filtered.map((account) => {
          const active = account.id === selectedAccount;
          return (
            <div
              key={account.id}
              className={cn(
                "grid gap-2 rounded-[var(--neu-radius-md)] border p-3 md:grid-cols-[minmax(0,1fr)_auto]",
                active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-raised neu-interactive",
              )}
            >
              <button type="button" className="text-left" onClick={() => onSelect(account.id)}>
                <p className="text-sm font-semibold">{account.label}</p>
                {account.subtitle ? (
                  <p className="mt-1 text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
                    {account.subtitle}
                  </p>
                ) : null}
              </button>
              <div className="flex items-center gap-2 md:justify-end">
                {account.meta}
                {onToggleInclusion ? (
                  <NeuButton
                    variant={account.included === false ? "secondary" : "soft-tonal"}
                    size="sm"
                    onClick={() => onToggleInclusion(account.id)}
                  >
                    {account.included === false ? "Excluded" : "Included"}
                  </NeuButton>
                ) : null}
              </div>
            </div>
          );
        })}
      </NeuWell>
    </NeuSurface>
  );
}

export function NeuSwitch({
  checked,
  onChange,
  label,
  description,
  disabled,
  accent = "accent",
  className,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  accent?: "accent" | "success" | "warning";
  className?: string;
}) {
  const accentColorClass = {
    accent: "bg-[var(--neu-accent)] text-[var(--neu-accent-ink)] border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))]",
    success: "bg-[var(--neu-success)] text-white border-[color:color-mix(in_oklch,var(--neu-success)_22%,var(--neu-stroke-soft))]",
    warning: "bg-[var(--neu-warning)] text-[var(--neu-accent-ink)] border-[color:color-mix(in_oklch,var(--neu-warning)_22%,var(--neu-stroke-soft))]",
  }[accent];

  return (
    <div className={cn("flex items-start gap-4 p-1", disabled && "opacity-50 pointer-events-none", className)}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-8 w-14 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--neu-accent)] border-none shadow-[var(--neu-shadow-inset)]",
          checked ? accentColorClass : "bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)]"
        )}
      >
        <span
          className={cn(
            "pointer-events-none block size-6 rounded-full bg-[var(--neu-surface-raised)] shadow-[var(--neu-shadow-pill)] ring-0 transition duration-200 ease-in-out transform",
            checked ? "translate-x-[26px] translate-y-[3px]" : "translate-x-[4px] translate-y-[3px]"
          )}
        />
      </button>
      {(label || description) && (
        <div className="flex flex-col gap-0.5">
          {label && <span className="text-sm font-semibold tracking-[0.01em]" style={{ color: "var(--neu-text-strong)" }}>{label}</span>}
          {description && <span className="text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>{description}</span>}
        </div>
      )}
    </div>
  );
}
