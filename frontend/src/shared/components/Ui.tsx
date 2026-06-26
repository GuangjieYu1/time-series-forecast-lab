import type React from "react";
import { controls, surface } from "../theme/design";

export function PageHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <section className={`${surface.workbench} overflow-hidden p-6`}>
      <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
        <div>
          {eyebrow ? <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">{eyebrow}</div> : null}
          <h1 className={`text-2xl font-semibold tracking-tight md:text-3xl ${surface.strongText}`}>{title}</h1>
          {description ? <p className={`mt-2 max-w-3xl text-sm leading-6 ${surface.mutedText}`}>{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </section>
  );
}

export function SectionCard({
  title,
  description,
  children,
  action,
  className = ""
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`${surface.panel} p-5 ${className}`}>
      {title ? (
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className={`text-base font-semibold ${surface.strongText}`}>{title}</h2>
            {description ? <p className={`mt-1 text-sm leading-6 ${surface.mutedText}`}>{description}</p> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function StatCard({ label, value, hint, tone = "neutral" }: { label: string; value: string | number; hint?: string; tone?: "neutral" | "good" | "warn" | "bad" | "info" }) {
  const accent = {
    neutral: "from-slate-500/12 to-transparent text-slate-600 dark:text-slate-300",
    good: "from-emerald-500/16 to-transparent text-emerald-600 dark:text-emerald-300",
    warn: "from-amber-500/16 to-transparent text-amber-600 dark:text-amber-300",
    bad: "from-red-500/16 to-transparent text-red-600 dark:text-red-300",
    info: "from-cyan-500/16 to-transparent text-cyan-600 dark:text-cyan-300"
  }[tone];
  return (
    <div className={`${surface.softPanel} overflow-hidden p-4`}>
      <div className={`-m-4 mb-3 bg-gradient-to-br ${accent} p-4`}>
        <div className={`text-xs font-medium ${surface.mutedText}`}>{label}</div>
        <div className={`mt-2 text-2xl font-semibold tracking-tight ${surface.strongText}`}>{value}</div>
      </div>
      {hint ? <div className={`text-xs leading-5 ${surface.mutedText}`}>{hint}</div> : null}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" | "info" }) {
  const toneClass = {
    neutral: controls.badge,
    good: "inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200",
    warn: "inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200",
    bad: "inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200",
    info: "inline-flex items-center rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 dark:border-cyan-400/20 dark:bg-cyan-400/10 dark:text-cyan-200"
  }[tone];
  return <span className={toneClass}>{children}</span>;
}

export function Stepper({ steps, activeIndex = 0 }: { steps: string[]; activeIndex?: number }) {
  return (
    <div className="grid gap-2 md:grid-cols-5">
      {steps.map((step, index) => {
        const active = index <= activeIndex;
        return (
          <div
            key={step}
            className={`rounded-2xl border p-3 text-sm transition ${
              active
                ? "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-400/30 dark:bg-indigo-400/10 dark:text-indigo-200"
                : "border-slate-200 bg-white text-slate-500 dark:border-white/10 dark:bg-[#111827] dark:text-slate-400"
            }`}
          >
            <div className="text-xs font-semibold">Step {index + 1}</div>
            <div className="mt-1 font-medium">{step}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  items
}: {
  value: T;
  onChange: (value: T) => void;
  items: { id: T; label: string }[];
}) {
  return (
    <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-1 dark:border-white/10 dark:bg-[#111827]">
      {items.map((item) => (
        <button key={item.id} className={controls.tab} data-active={value === item.id} onClick={() => onChange(item.id)}>
          {item.label}
        </button>
      ))}
    </div>
  );
}

export { controls, surface };
