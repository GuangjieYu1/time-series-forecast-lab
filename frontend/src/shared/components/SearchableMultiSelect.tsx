import { useEffect, useId, useMemo, useRef, useState } from "react";

export type SearchableMultiSelectOption = {
  value: string;
  label: string;
  description?: string;
  keywords?: string;
};

export function SearchableMultiSelect({
  options,
  value,
  onChange,
  placeholder = "搜索并选择",
  searchPlaceholder = "输入关键词搜索",
  emptyMessage = "没有匹配结果。",
  resultLimit = 20,
  variant = "default",
  disabled = false,
}: {
  options: SearchableMultiSelectOption[];
  value: string[];
  onChange: (nextValue: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  resultLimit?: number;
  variant?: "default" | "auth";
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  const optionMap = useMemo(() => new Map(options.map((option) => [option.value, option])), [options]);
  const selectedOptions = value.map((item) => optionMap.get(item) ?? { value: item, label: "已选成员" });
  const normalizedQuery = query.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!normalizedQuery) return [];
    return options.filter((option) =>
      `${option.label} ${option.description ?? ""} ${option.keywords ?? ""}`.toLowerCase().includes(normalizedQuery)
    );
  }, [normalizedQuery, options]);
  const visibleMatches = matches.slice(0, resultLimit);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const styles = variant === "auth"
    ? {
        box: "border-white/10 bg-slate-950/60",
        chip: "border-indigo-300/20 bg-indigo-300/10 text-indigo-100",
        chipRemove: "text-indigo-200 hover:bg-white/10 hover:text-white",
        trigger: "text-slate-300 hover:bg-white/[0.05]",
        panel: "border-white/10 bg-[#0b1020] shadow-black/40",
        input: "border-white/10 bg-slate-950 text-slate-100 placeholder:text-slate-500 focus:border-indigo-300 focus:ring-indigo-300/10",
        hint: "text-slate-400",
        option: "text-slate-200 hover:bg-white/[0.06]",
        optionSelected: "bg-indigo-300/10",
        description: "text-slate-400",
        check: "border-white/20",
        checkSelected: "border-indigo-300 bg-indigo-300 text-slate-950",
      }
    : {
        box: "border-slate-200 bg-white dark:border-white/10 dark:bg-[#0b1020]",
        chip: "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-300/20 dark:bg-indigo-300/10 dark:text-indigo-100",
        chipRemove: "text-indigo-500 hover:bg-indigo-100 hover:text-indigo-800 dark:text-indigo-200 dark:hover:bg-white/10 dark:hover:text-white",
        trigger: "text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/[0.05]",
        panel: "border-slate-200 bg-white shadow-slate-950/10 dark:border-white/10 dark:bg-[#0b1020] dark:shadow-black/40",
        input: "border-slate-200 bg-white text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:ring-indigo-500/10 dark:border-white/10 dark:bg-slate-950 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-indigo-300 dark:focus:ring-indigo-300/10",
        hint: "text-slate-500 dark:text-slate-400",
        option: "text-slate-800 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-white/[0.06]",
        optionSelected: "bg-indigo-50 dark:bg-indigo-300/10",
        description: "text-slate-500 dark:text-slate-400",
        check: "border-slate-300 dark:border-white/20",
        checkSelected: "border-indigo-600 bg-indigo-600 text-white dark:border-indigo-300 dark:bg-indigo-300 dark:text-slate-950",
      };

  const toggleValue = (item: string) => {
    onChange(value.includes(item) ? value.filter((current) => current !== item) : [...value, item]);
  };

  return (
    <div ref={rootRef} className="relative space-y-2">
      <div className={`rounded-xl border ${styles.box}`}>
        {selectedOptions.length ? (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {selectedOptions.map((option) => (
              <span key={option.value} className={`inline-flex max-w-full items-center gap-1 rounded-lg border py-1 pl-2.5 pr-1 text-xs font-medium ${styles.chip}`}>
                <span className="truncate">{option.label}</span>
                <button
                  type="button"
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md ${styles.chipRemove}`}
                  onClick={() => toggleValue(option.value)}
                  aria-label={`取消选择 ${option.label}`}
                  disabled={disabled}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <button
          type="button"
          className={`flex min-h-11 w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${styles.trigger}`}
          onClick={() => {
            setOpen((current) => !current);
            if (open) setQuery("");
          }}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listboxId}
          disabled={disabled}
        >
          <span>{value.length ? `${placeholder}（已选 ${value.length}）` : placeholder}</span>
          <span aria-hidden="true" className={`text-xs transition ${open ? "rotate-180" : ""}`}>▼</span>
        </button>
      </div>

      {open ? (
        <div className={`absolute left-0 right-0 top-full z-30 mt-2 rounded-2xl border p-3 shadow-2xl ${styles.panel}`}>
          <input
            ref={inputRef}
            className={`w-full rounded-xl border px-3.5 py-2.5 text-sm outline-none transition focus:ring-4 ${styles.input}`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
          />
          <div id={listboxId} role="listbox" aria-multiselectable="true" className="mt-2 max-h-64 overflow-y-auto">
            {!normalizedQuery ? (
              <div className={`px-2 py-3 text-sm ${styles.hint}`}>输入关键词后显示匹配项，最多 {resultLimit} 条。</div>
            ) : visibleMatches.length ? (
              visibleMatches.map((option) => {
                const selected = value.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition ${styles.option} ${selected ? styles.optionSelected : ""}`}
                    onClick={() => toggleValue(option.value)}
                  >
                    <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-xs font-bold ${selected ? styles.checkSelected : styles.check}`} aria-hidden="true">
                      {selected ? "✓" : ""}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{option.label}</span>
                      {option.description ? <span className={`mt-0.5 block truncate text-xs ${styles.description}`}>{option.description}</span> : null}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className={`px-2 py-3 text-sm ${styles.hint}`}>{emptyMessage}</div>
            )}
          </div>
          {matches.length > resultLimit ? <div className={`border-t px-2 pt-2 text-xs ${styles.hint}`}>还有 {matches.length - resultLimit} 条结果，请继续输入以缩小范围。</div> : null}
        </div>
      ) : null}
    </div>
  );
}
