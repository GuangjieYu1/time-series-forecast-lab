export const surface = {
  page: "min-h-screen bg-[#f8fafc] text-slate-950 antialiased dark:bg-[#080b14] dark:text-slate-100",
  shell: "min-h-screen bg-[radial-gradient(circle_at_top_left,rgba(129,140,248,0.22),transparent_34%),radial-gradient(circle_at_top_right,rgba(34,211,238,0.14),transparent_28%),linear-gradient(180deg,#080b14_0%,#0b1020_48%,#080b14_100%)] text-slate-100",
  workbench: "rounded-[28px] border border-slate-200/80 bg-white/92 shadow-[0_24px_90px_rgba(15,23,42,0.08)] dark:border-white/10 dark:bg-[#111827]/82 dark:shadow-[0_24px_100px_rgba(0,0,0,0.36)]",
  panel: "rounded-2xl border border-slate-200/80 bg-white shadow-sm shadow-slate-200/50 dark:border-white/10 dark:bg-[#111827] dark:shadow-none",
  softPanel: "rounded-2xl border border-slate-200/70 bg-slate-50/80 dark:border-white/10 dark:bg-[#151b2e]",
  glass: "rounded-2xl border border-white/18 bg-white/10 shadow-[0_20px_70px_rgba(0,0,0,0.28)] backdrop-blur-2xl",
  chartPanel: "rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-[#111827]",
  mutedText: "text-slate-500 dark:text-slate-400",
  strongText: "text-slate-950 dark:text-white"
};

export const controls = {
  primaryButton:
    "inline-flex min-h-10 items-center justify-center rounded-xl bg-[#4f46e5] px-4 py-2 text-sm font-semibold text-white shadow-sm shadow-indigo-500/20 transition hover:bg-[#4338ca] disabled:cursor-not-allowed disabled:bg-slate-300 dark:bg-[#818cf8] dark:text-[#080b14] dark:hover:bg-[#a5b4fc]",
  secondaryButton:
    "inline-flex min-h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10",
  ghostButton:
    "inline-flex min-h-10 items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-white/10 dark:hover:text-white",
  dangerButton:
    "inline-flex min-h-10 items-center justify-center rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-200",
  input:
    "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-white/10 dark:bg-[#0b1020] dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-indigo-300 dark:focus:ring-indigo-300/10",
  badge: "inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300",
  tab:
    "rounded-xl px-3.5 py-2 text-sm font-semibold transition data-[active=true]:bg-slate-950 data-[active=true]:text-white dark:data-[active=true]:bg-white dark:data-[active=true]:text-[#080b14] text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-white/10 dark:hover:text-white"
};

export const tones = {
  indigo: "#4F46E5",
  cyan: "#06B6D4",
  success: "#10B981",
  warning: "#F59E0B",
  danger: "#EF4444"
};
