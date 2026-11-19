import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { wyckoffApi } from '../wyckoff';

vi.mock('../index', () => ({
  default: { get: vi.fn() },
}));

describe('wyckoffApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads signals for the requested date and maps snake_case fields', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        date: '2026-01-28',
        latest_data_date: '2026-01-28',
        is_stale: false,
        total: 1,
        codes_scanned: 2,
        codes_without_data: 0,
        signals: [
          {
            code: '600519',
            trigger_date: '2026-01-28',
            sos_date: '2026-01-26',
            price: 12.3,
            ma20: 11.8,
            volume_ratio: 1.4,
            sos_high: 12.6,
            trigger_low: 11.5,
            features: {
              spring: {
                detected: true,
                break_date: '2026-01-21',
                recover_date: '2026-01-22',
                break_depth: 0.012,
                reason: null,
              },
              test: { detected: false, test_date: null, volume_ratio: null, reason: 'no_test' },
              trend: { ratio: 1.2, up_days: 6, down_days: 3, reason: null },
            },
          },
        ],
      },
    });

    const result = await wyckoffApi.getSignals({ date: '2026-01-28', limit: 50 });

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/wyckoff/signals', {
      params: { date: '2026-01-28', limit: 50 },
    });
    expect(result.latestDataDate).toBe('2026-01-28');
    expect(result.signals[0].triggerDate).toBe('2026-01-28');
    expect(result.signals[0].sosHigh).toBe(12.6);
    expect(result.signals[0].triggerLow).toBe(11.5);
    expect(result.signals[0].features.trend.upDays).toBe(6);
  });

  it('encodes the stock code and forwards the bar window', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { code: '600519', latest_data_date: '2026-01-28', bars: [], signals: [] },
    });

    await wyckoffApi.getDetail('600519', 180);

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/wyckoff/detail/600519', {
      params: { bars: 180 },
    });
  });
});
