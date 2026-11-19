import type { WyckoffDetailResponse, WyckoffSignalsResponse } from '../types/wyckoff';
import apiClient from './index';
import { toCamelCase } from './utils';

export interface WyckoffSignalsParams {
  /** 信号日期（YYYY-MM-DD）；缺省使用本地最新交易日 */
  date?: string;
  /** 只扫描指定股票，逗号分隔 */
  codes?: string;
  /** 最多扫描的股票数 */
  limit?: number;
}

export const wyckoffApi = {
  async getSignals(params: WyckoffSignalsParams = {}): Promise<WyckoffSignalsResponse> {
    const response = await apiClient.get('/api/v1/wyckoff/signals', { params });
    return toCamelCase<WyckoffSignalsResponse>(response.data);
  },

  async getDetail(code: string, bars = 120): Promise<WyckoffDetailResponse> {
    const response = await apiClient.get(`/api/v1/wyckoff/detail/${encodeURIComponent(code)}`, {
      params: { bars },
    });
    return toCamelCase<WyckoffDetailResponse>(response.data);
  },
};
