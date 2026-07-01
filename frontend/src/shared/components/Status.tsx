export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center dark:border-slate-700 dark:bg-slate-950">
      <div className="text-sm font-semibold text-slate-900 dark:text-white">{title}</div>
      {detail ? <div className="mt-2 text-sm text-slate-500 dark:text-slate-400">{detail}</div> : null}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{message}</div>;
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-accent" />
      {label}
    </div>
  );
}
