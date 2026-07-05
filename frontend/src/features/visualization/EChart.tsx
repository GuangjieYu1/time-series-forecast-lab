import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption, EChartsType } from "echarts";

export type EChartEventHandlers = Record<string, (params: unknown, chart: EChartsType) => void>;

export async function renderChartOptionToDataUrl(
  option: EChartsOption,
  {
    width = 1280,
    height = 720,
    pixelRatio = 2,
    backgroundColor = "#0f172a"
  }: {
    width?: number;
    height?: number;
    pixelRatio?: number;
    backgroundColor?: string;
  } = {}
) {
  if (typeof document === "undefined") {
    throw new Error("Chart image export is only available in the browser.");
  }
  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-10000px";
  container.style.top = "0";
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
  document.body.appendChild(container);
  const chart = echarts.init(container, undefined, { renderer: "canvas", width, height });
  try {
    chart.setOption({ ...option, animation: false, toolbox: undefined }, true);
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return chart.getDataURL({
      type: "png",
      pixelRatio,
      backgroundColor,
      excludeComponents: ["toolbox"]
    });
  } finally {
    chart.dispose();
    container.remove();
  }
}

export function EChart({
  option,
  height = 360,
  events
}: {
  option: EChartsOption;
  height?: number;
  events?: EChartEventHandlers;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const listeners = Object.entries(events ?? {}).map(([eventName, handler]) => {
      const listener = (params: unknown) => handler(params, chart);
      chart.on(eventName, listener);
      return [eventName, listener] as const;
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      listeners.forEach(([eventName, listener]) => chart.off(eventName, listener));
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [events, option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}