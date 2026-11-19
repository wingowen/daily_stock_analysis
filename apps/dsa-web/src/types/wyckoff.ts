/**
 * Wyckoff 只读接口的前端类型（对应 api/v1/schemas/wyckoff.py）。
 * API 响应为 snake_case，经 toCamelCase 转换后使用这里的 camelCase 字段。
 */

export interface WyckoffSpringFeature {
  detected: boolean;
  breakDate?: string | null;
  recoverDate?: string | null;
  breakDepth?: number | null;
  reason?: string | null;
}

export interface WyckoffTestFeature {
  detected: boolean;
  testDate?: string | null;
  volumeRatio?: number | null;
  reason?: string | null;
}

export interface WyckoffTrendFeature {
  ratio?: number | null;
  upDays: number;
  downDays: number;
  reason?: string | null;
}

export interface WyckoffFeatures {
  spring: WyckoffSpringFeature;
  test: WyckoffTestFeature;
  trend: WyckoffTrendFeature;
}

export interface WyckoffSignal {
  code: string;
  triggerDate: string;
  sosDate: string;
  price?: number | null;
  ma20?: number | null;
  volumeRatio?: number | null;
  sosHigh?: number | null;
  triggerLow?: number | null;
  features: WyckoffFeatures;
}

export interface WyckoffSignalsResponse {
  date: string;
  latestDataDate?: string | null;
  isStale: boolean;
  total: number;
  codesScanned: number;
  codesWithoutData: number;
  signals: WyckoffSignal[];
}

export interface WyckoffBar {
  date: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
  ma20?: number | null;
  volumeRatio?: number | null;
}

export interface WyckoffDetailResponse {
  code: string;
  latestDataDate?: string | null;
  bars: WyckoffBar[];
  signals: WyckoffSignal[];
}
