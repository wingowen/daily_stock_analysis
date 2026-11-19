import type React from 'react';
import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import type { ECharts, EChartsCoreOption } from 'echarts/core';
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { WyckoffBar, WyckoffSignal } from '../../types/wyckoff';
import { cn } from '../../utils/cn';

echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  DataZoomComponent,
  MarkPointComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

// ECharts 需要具体颜色值，无法直接消费 CSS 变量；这组常量在明暗主题下都可用。
const UP_COLOR = '#ef5350'; // A 股习惯：上涨为红
const DOWN_COLOR = '#26a69a'; // 下跌为绿
const MA_COLOR = '#38bdf8';
const TRIGGER_COLOR = '#f59e0b';
const AXIS_TEXT = '#94a3b8';
const SPLIT_LINE = 'rgba(148,163,184,0.18)';

const DEFAULT_VISIBLE_BARS = 120;

export interface WyckoffChartLabels {
  trigger: string;
  sosHigh: string;
  triggerLow: string;
  ma20: string;
  volume: string;
}

interface WyckoffChartProps {
  bars: WyckoffBar[];
  /** 当前窗口内的触发点，用于打点 */
  signals: WyckoffSignal[];
  /** 当前选中的信号，用于绘制 SOS 高点 / LPS 低点参考线 */
  selectedSignal: WyckoffSignal | null;
  labels: WyckoffChartLabels;
  className?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function formatPrice(value: number | null | undefined): string {
  return value == null ? '--' : value.toFixed(2);
}

function formatVolume(value: number | null | undefined): string {
  if (value == null) return '--';
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(2)} 万`;
  return String(Math.round(value));
}

function buildTooltip(params: unknown, bars: WyckoffBar[]): string {
  const list = Array.isArray(params) ? params : [params];
  for (const item of list) {
    if (!isRecord(item) || typeof item.dataIndex !== 'number') continue;
    const bar = bars[item.dataIndex];
    if (!bar) continue;
    const lines = [
      bar.date,
      `开 ${formatPrice(bar.open)} · 收 ${formatPrice(bar.close)}`,
      `高 ${formatPrice(bar.high)} · 低 ${formatPrice(bar.low)}`,
      `量 ${formatVolume(bar.volume)} · MA20 ${formatPrice(bar.ma20)}`,
    ];
    if (bar.volumeRatio != null) {
      lines.push(`量比 ${bar.volumeRatio.toFixed(2)}`);
    }
    return lines.join('<br/>');
  }
  return '';
}

function buildOption(
  bars: WyckoffBar[],
  signals: WyckoffSignal[],
  selectedSignal: WyckoffSignal | null,
  labels: WyckoffChartLabels,
): EChartsCoreOption {
  const dates = bars.map((bar) => bar.date);
  const candleData = bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]);
  const ma20Data = bars.map((bar) => bar.ma20 ?? null);
  const volumeData = bars.map((bar) => ({
    value: bar.volume ?? null,
    itemStyle: {
      color: (bar.close ?? 0) >= (bar.open ?? 0) ? UP_COLOR : DOWN_COLOR,
      opacity: 0.55,
    },
  }));

  const indexByDate = new Map(dates.map((date, index) => [date, index]));
  const triggerPoints = signals.flatMap((signal) => {
    const index = indexByDate.get(signal.triggerDate);
    if (index === undefined) return [];
    const anchor = signal.triggerLow ?? signal.price ?? bars[index].low;
    if (anchor == null) return [];
    return [{
      name: labels.trigger,
      coord: [signal.triggerDate, anchor],
      value: labels.trigger,
    }];
  });

  const referenceLines: Array<Record<string, unknown>> = [];
  if (selectedSignal?.sosHigh != null) {
    referenceLines.push({
      name: labels.sosHigh,
      yAxis: selectedSignal.sosHigh,
      lineStyle: { color: UP_COLOR, type: 'dashed', width: 1 },
      label: {
        formatter: `${labels.sosHigh} ${formatPrice(selectedSignal.sosHigh)}`,
        position: 'insideEndTop',
        color: UP_COLOR,
        fontSize: 10,
      },
    });
  }
  if (selectedSignal?.triggerLow != null) {
    referenceLines.push({
      name: labels.triggerLow,
      yAxis: selectedSignal.triggerLow,
      lineStyle: { color: DOWN_COLOR, type: 'dashed', width: 1 },
      label: {
        formatter: `${labels.triggerLow} ${formatPrice(selectedSignal.triggerLow)}`,
        position: 'insideEndBottom',
        color: DOWN_COLOR,
        fontSize: 10,
      },
    });
  }

  const zoomStart = bars.length > DEFAULT_VISIBLE_BARS
    ? (100 * (bars.length - DEFAULT_VISIBLE_BARS)) / bars.length
    : 0;

  return {
    animation: false,
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: '#334155' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15,23,42,0.92)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 11 },
      formatter: (params: unknown) => buildTooltip(params, bars),
    },
    grid: [
      { left: 58, right: 18, top: 12, height: '56%' },
      { left: 58, right: 18, top: '70%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: SPLIT_LINE } },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: SPLIT_LINE } },
        axisTick: { show: false },
        axisLabel: { color: AXIS_TEXT, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: AXIS_TEXT, fontSize: 10 },
        splitLine: { lineStyle: { color: SPLIT_LINE } },
      },
      {
        gridIndex: 1,
        scale: true,
        splitNumber: 2,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: zoomStart, end: 100 },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 8,
        height: 18,
        start: zoomStart,
        end: 100,
        borderColor: 'transparent',
        backgroundColor: 'transparent',
        fillerColor: 'rgba(56,189,248,0.15)',
        handleStyle: { color: MA_COLOR },
        textStyle: { color: AXIS_TEXT, fontSize: 10 },
      },
    ],
    series: [
      {
        name: labels.trigger,
        type: 'candlestick',
        data: candleData,
        itemStyle: {
          color: UP_COLOR,
          color0: DOWN_COLOR,
          borderColor: UP_COLOR,
          borderColor0: DOWN_COLOR,
        },
        markPoint: {
          symbol: 'pin',
          symbolSize: 34,
          itemStyle: { color: TRIGGER_COLOR },
          label: { color: '#1f2937', fontSize: 10, fontWeight: 'bold' },
          data: triggerPoints,
        },
        markLine: {
          symbol: 'none',
          silent: true,
          animation: false,
          data: referenceLines,
        },
      },
      {
        name: labels.ma20,
        type: 'line',
        data: ma20Data,
        showSymbol: false,
        lineStyle: { width: 1.4, color: MA_COLOR },
        itemStyle: { color: MA_COLOR },
      },
      {
        name: labels.volume,
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barWidth: '60%',
        data: volumeData,
      },
    ],
  };
}

export const WyckoffChart: React.FC<WyckoffChartProps> = ({
  bars,
  signals,
  selectedSignal,
  labels,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ECharts | null>(null);

  const option = useMemo(
    () => buildOption(bars, signals, selectedSignal, labels),
    [bars, signals, selectedSignal, labels],
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return undefined;
    const chart = echarts.init(element);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={containerRef} className={cn('h-[420px] w-full', className)} />;
};
