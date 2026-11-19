import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import WyckoffPage from '../WyckoffPage';

const { getSignals, getDetail } = vi.hoisted(() => ({
  getSignals: vi.fn(),
  getDetail: vi.fn(),
}));

vi.mock('../../api/wyckoff', () => ({
  wyckoffApi: {
    getSignals: (...args: unknown[]) => getSignals(...args),
    getDetail: (...args: unknown[]) => getDetail(...args),
  },
}));

vi.mock('../../components/wyckoff/WyckoffChart', () => ({
  WyckoffChart: () => <div data-testid="wyckoff-chart" />,
}));

const signal = {
  code: '600519',
  triggerDate: '2026-01-28',
  sosDate: '2026-01-26',
  price: 12.3,
  ma20: 11.8,
  volumeRatio: 1.4,
  sosHigh: 12.6,
  triggerLow: 11.5,
  features: {
    spring: { detected: true, breakDate: '2026-01-21', recoverDate: '2026-01-22', breakDepth: 0.012, reason: null },
    test: { detected: false, testDate: null, volumeRatio: null, reason: 'no_test' },
    trend: { ratio: 1.2, upDays: 6, downDays: 3, reason: null },
  },
};

const signalsResponse = {
  date: '2026-01-28',
  latestDataDate: '2026-01-28',
  isStale: false,
  total: 1,
  codesScanned: 2,
  codesWithoutData: 0,
  signals: [signal],
};

const detailResponse = {
  code: '600519',
  latestDataDate: '2026-01-28',
  bars: [
    { date: '2026-01-27', open: 11.9, high: 12.2, low: 11.8, close: 12.1, volume: 1000, ma20: 11.7, volumeRatio: 1.1 },
    { date: '2026-01-28', open: 12.1, high: 12.4, low: 12.0, close: 12.3, volume: 1200, ma20: 11.8, volumeRatio: 1.4 },
  ],
  signals: [signal],
};

const renderPage = () => render(
  <UiLanguageProvider>
    <WyckoffPage />
  </UiLanguageProvider>
);

describe('WyckoffPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    getSignals.mockReset();
    getDetail.mockReset();
  });

  it('loads signals, selects the first trigger and renders its chart', async () => {
    getSignals.mockResolvedValue(signalsResponse);
    getDetail.mockResolvedValue(detailResponse);

    renderPage();

    expect(await screen.findByText('触发信号')).toBeInTheDocument();
    expect((await screen.findAllByText('600519')).length).toBeGreaterThan(0);
    expect(getDetail).toHaveBeenCalledWith('600519', 180);
    expect(await screen.findByTestId('wyckoff-chart')).toBeInTheDocument();
  });

  it('shows the disabled state when the backend rejects with 403', async () => {
    getSignals.mockRejectedValue({
      response: { status: 403, data: { detail: { error: 'wyckoff_disabled', message: 'WYCKOFF_ENABLED is false.' } } },
    });

    renderPage();

    expect(await screen.findByText('威科夫功能未启用')).toBeInTheDocument();
    expect(screen.queryByTestId('wyckoff-chart')).not.toBeInTheDocument();
    expect(getDetail).not.toHaveBeenCalled();
  });

  it('shows the stale hint and empty state when no trigger matches', async () => {
    getSignals.mockResolvedValue({
      ...signalsResponse,
      isStale: true,
      total: 0,
      latestDataDate: '2026-01-27',
      signals: [],
    });

    renderPage();

    expect(await screen.findByText('本地日线可能落后')).toBeInTheDocument();
    expect(await screen.findByText('当日无触发信号')).toBeInTheDocument();
    expect(getDetail).not.toHaveBeenCalled();
  });
});
