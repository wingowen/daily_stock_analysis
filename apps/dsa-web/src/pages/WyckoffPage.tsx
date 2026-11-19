import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CandlestickChart, RefreshCw, Search } from 'lucide-react';
import { wyckoffApi } from '../api/wyckoff';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  InlineAlert,
  Loading,
  PageHeader,
} from '../components/common';
import { WyckoffChart, type WyckoffChartLabels } from '../components/wyckoff/WyckoffChart';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type {
  WyckoffBar,
  WyckoffDetailResponse,
  WyckoffSignal,
  WyckoffSignalsResponse,
} from '../types/wyckoff';
import { cn } from '../utils/cn';

const DETAIL_BARS = 180;

type Selection = { code: string; triggerDate: string };

const DATE_INPUT_CLASS =
  'input-surface input-focus-glow h-9 rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none';

function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null ? '--' : value.toFixed(digits);
}

const StatTile: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-xl border border-border/70 bg-surface/60 px-3 py-2">
    <div className="text-[11px] text-muted-text">{label}</div>
    <div className="mt-1 font-mono text-sm text-foreground">{value}</div>
  </div>
);

interface SignalRowProps {
  signal: WyckoffSignal;
  active: boolean;
  onSelect: () => void;
  triggerLabel: string;
  priceLabel: string;
  volumeRatioLabel: string;
}

const SignalRow: React.FC<SignalRowProps> = ({
  signal,
  active,
  onSelect,
  triggerLabel,
  priceLabel,
  volumeRatioLabel,
}) => (
  <button
    type="button"
    onClick={onSelect}
    className={cn(
      'w-full rounded-xl border px-3 py-2.5 text-left transition',
      active
        ? 'border-cyan/50 bg-cyan/10'
        : 'border-border/70 bg-surface/40 hover:bg-hover'
    )}
  >
    <div className="flex items-center justify-between gap-2">
      <span className="font-mono text-sm font-semibold text-foreground">{signal.code}</span>
      <div className="flex items-center gap-1">
        {signal.features.spring.detected ? <Badge variant="info" size="sm">Spring</Badge> : null}
        {signal.features.test.detected ? <Badge variant="success" size="sm">Test</Badge> : null}
      </div>
    </div>
    <div className="mt-1 text-xs text-secondary-text">
      {triggerLabel} {signal.triggerDate} · SOS {signal.sosDate}
    </div>
    <div className="mt-0.5 text-xs text-muted-text">
      {priceLabel} {formatNumber(signal.price)} · {volumeRatioLabel} {formatNumber(signal.volumeRatio)}
    </div>
  </button>
);

const WyckoffPage: React.FC = () => {
  const { t } = useUiLanguage();

  const [signalsResponse, setSignalsResponse] = useState<WyckoffSignalsResponse | null>(null);
  const [signalsLoading, setSignalsLoading] = useState(true);
  const [signalsError, setSignalsError] = useState<ParsedApiError | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [dateInput, setDateInput] = useState('');
  const [queryDate, setQueryDate] = useState('');

  const [selection, setSelection] = useState<Selection | null>(null);
  const [detail, setDetail] = useState<WyckoffDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<ParsedApiError | null>(null);
  const [detailEmpty, setDetailEmpty] = useState(false);

  const signalsRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  useEffect(() => {
    document.title = `${t('wyckoff.title')} - DSA`;
  }, [t]);

  const loadSignals = useCallback(async () => {
    const generation = ++signalsRequestRef.current;
    setSignalsLoading(true);
    setSignalsError(null);
    try {
      const response = await wyckoffApi.getSignals(queryDate ? { date: queryDate } : {});
      if (generation !== signalsRequestRef.current) return;
      setDisabled(false);
      setSignalsResponse(response);
      setSelection((current) => {
        if (current && response.signals.some(
          (item) => item.code === current.code && item.triggerDate === current.triggerDate
        )) {
          return current;
        }
        const first = response.signals[0];
        return first ? { code: first.code, triggerDate: first.triggerDate } : null;
      });
    } catch (error) {
      if (generation !== signalsRequestRef.current) return;
      const parsed = getParsedApiError(error);
      // 该接口的 403 只来自 WYCKOFF_ENABLED 关闭，直接按未启用处理。
      if (parsed.status === 403) {
        setDisabled(true);
        setSignalsResponse(null);
      } else {
        setSignalsError(parsed);
      }
    } finally {
      if (generation === signalsRequestRef.current) {
        setSignalsLoading(false);
      }
    }
  }, [queryDate]);

  const loadDetail = useCallback(async (code: string) => {
    const generation = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setDetailEmpty(false);
    try {
      const response = await wyckoffApi.getDetail(code, DETAIL_BARS);
      if (generation !== detailRequestRef.current) return;
      setDetail(response);
    } catch (error) {
      if (generation !== detailRequestRef.current) return;
      const parsed = getParsedApiError(error);
      setDetail(null);
      // wyckoff_no_data 以 404 返回，按空数据展示而不是错误。
      if (parsed.status === 404) {
        setDetailEmpty(true);
      } else {
        setDetailError(parsed);
      }
    } finally {
      if (generation === detailRequestRef.current) {
        setDetailLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadSignals();
    return () => {
      signalsRequestRef.current += 1;
    };
  }, [loadSignals]);

  useEffect(() => {
    if (!selection) {
      detailRequestRef.current += 1;
      setDetail(null);
      setDetailEmpty(false);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    void loadDetail(selection.code);
  }, [selection, loadDetail]);

  const activeSignal = useMemo<WyckoffSignal | null>(() => {
    if (!selection) return null;
    const fromDetail = detail?.signals.find((item) => item.triggerDate === selection.triggerDate);
    if (fromDetail) return fromDetail;
    return signalsResponse?.signals.find(
      (item) => item.code === selection.code && item.triggerDate === selection.triggerDate
    ) ?? null;
  }, [detail, selection, signalsResponse]);

  const chartBars = useMemo<WyckoffBar[]>(() => detail?.bars ?? [], [detail]);

  const chartLabels = useMemo<WyckoffChartLabels>(() => ({
    trigger: 'LPS',
    sosHigh: t('wyckoff.sosHigh'),
    triggerLow: t('wyckoff.triggerLow'),
    ma20: 'MA20',
    volume: t('wyckoff.volume'),
  }), [t]);

  const summary = signalsResponse;

  const renderFeatureBadge = (label: string, detected: boolean) => (
    <Badge variant={detected ? 'success' : 'default'} size="sm">
      {label} · {detected ? t('wyckoff.detected') : t('wyckoff.notDetected')}
    </Badge>
  );

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="Wyckoff"
        title={t('wyckoff.title')}
        description={t('wyckoff.description')}
        actions={(
          <Button
            size="sm"
            variant="secondary"
            isLoading={signalsLoading}
            loadingText={t('wyckoff.refreshing')}
            onClick={() => void loadSignals()}
          >
            <RefreshCw className="h-4 w-4" />
            {t('wyckoff.refresh')}
          </Button>
        )}
      />

      {disabled ? (
        <EmptyState
          icon={<CandlestickChart className="h-6 w-6" />}
          title={t('wyckoff.disabledTitle')}
          description={t('wyckoff.disabledDescription')}
        />
      ) : (
        <>
          <Card variant="bordered" padding="md">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs text-muted-text">
                  <span className="mb-1 block">{t('wyckoff.queryDate')}</span>
                  <input
                    type="date"
                    value={dateInput}
                    aria-label={t('wyckoff.queryDate')}
                    onChange={(event) => setDateInput(event.target.value)}
                    className={DATE_INPUT_CLASS}
                  />
                </label>
                <Button size="sm" variant="secondary" onClick={() => setQueryDate(dateInput)}>
                  <Search className="h-4 w-4" />
                  {t('wyckoff.query')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setDateInput('');
                    setQueryDate('');
                  }}
                >
                  {t('wyckoff.latest')}
                </Button>
              </div>
              {summary ? (
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-text">
                  <span>{t('wyckoff.signalDate')}: <span className="font-mono text-foreground">{summary.date}</span></span>
                  <span>{t('wyckoff.latestDataDate')}: <span className="font-mono text-foreground">{summary.latestDataDate ?? '--'}</span></span>
                  <span>{t('wyckoff.codesScanned')}: <span className="font-mono text-foreground">{summary.codesScanned}</span></span>
                  <span>{t('wyckoff.codesWithoutData')}: <span className="font-mono text-foreground">{summary.codesWithoutData}</span></span>
                </div>
              ) : null}
            </div>
          </Card>

          {summary?.isStale ? (
            <InlineAlert
              variant="warning"
              title={t('wyckoff.staleTitle')}
              message={t('wyckoff.staleMessage', { date: summary.latestDataDate ?? '--' })}
            />
          ) : null}

          {signalsError ? (
            <ApiErrorAlert
              error={signalsError}
              actionLabel={t('common.retry')}
              onAction={() => void loadSignals()}
              onDismiss={() => setSignalsError(null)}
            />
          ) : null}

          {signalsLoading && !summary ? <Loading label={t('wyckoff.loadingSignals')} /> : null}

          {!signalsLoading && !signalsError && summary && summary.signals.length === 0 ? (
            <EmptyState
              icon={<CandlestickChart className="h-6 w-6" />}
              title={t('wyckoff.emptyTitle')}
              description={t('wyckoff.emptyDescription')}
            />
          ) : null}

          {summary && summary.signals.length > 0 ? (
            <div className="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
              <Card title={t('wyckoff.signalsTitle')} subtitle={`${summary.total}`} variant="bordered" padding="md">
                <div className="max-h-[720px] space-y-2 overflow-y-auto pr-1">
                  {summary.signals.map((signal) => {
                    const active = selection?.code === signal.code
                      && selection.triggerDate === signal.triggerDate;
                    return (
                      <SignalRow
                        key={`${signal.code}-${signal.triggerDate}`}
                        signal={signal}
                        active={active}
                        triggerLabel={t('wyckoff.triggerDate')}
                        priceLabel={t('wyckoff.price')}
                        volumeRatioLabel={t('wyckoff.volumeRatio')}
                        onSelect={() => setSelection({ code: signal.code, triggerDate: signal.triggerDate })}
                      />
                    );
                  })}
                </div>
              </Card>

              <Card variant="bordered" padding="md">
                {detailError ? (
                  <ApiErrorAlert
                    error={detailError}
                    actionLabel={t('common.retry')}
                    onAction={() => {
                      if (selection) void loadDetail(selection.code);
                    }}
                    onDismiss={() => setDetailError(null)}
                  />
                ) : null}

                {detailEmpty ? (
                  <EmptyState
                    icon={<CandlestickChart className="h-6 w-6" />}
                    title={t('wyckoff.detailEmptyTitle')}
                    description={t('wyckoff.detailEmptyDescription')}
                  />
                ) : null}

                {!detailEmpty ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="font-mono text-lg font-semibold text-foreground">
                          {selection?.code ?? '--'}
                        </div>
                        <div className="mt-0.5 text-xs text-muted-text">
                          {t('wyckoff.triggerDate')} {activeSignal?.triggerDate ?? '--'}
                          {' · '}
                          {t('wyckoff.sosDate')} {activeSignal?.sosDate ?? '--'}
                        </div>
                      </div>
                      {activeSignal ? (
                        <div className="flex flex-wrap items-center gap-1.5">
                          {renderFeatureBadge('Spring', activeSignal.features.spring.detected)}
                          {renderFeatureBadge('Test', activeSignal.features.test.detected)}
                        </div>
                      ) : null}
                    </div>

                    {activeSignal ? (
                      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
                        <StatTile label={t('wyckoff.price')} value={formatNumber(activeSignal.price)} />
                        <StatTile label={t('wyckoff.ma20')} value={formatNumber(activeSignal.ma20)} />
                        <StatTile label={t('wyckoff.volumeRatio')} value={formatNumber(activeSignal.volumeRatio)} />
                        <StatTile label={t('wyckoff.sosHigh')} value={formatNumber(activeSignal.sosHigh)} />
                        <StatTile label={t('wyckoff.triggerLow')} value={formatNumber(activeSignal.triggerLow)} />
                      </div>
                    ) : null}

                    <p className="mt-2 text-xs text-muted-text">{t('wyckoff.structureHint')}</p>

                    <div className="mt-3">
                      {detailLoading && chartBars.length === 0 ? (
                        <Loading label={t('wyckoff.loadingDetail')} />
                      ) : chartBars.length > 0 ? (
                        <WyckoffChart
                          bars={chartBars}
                          signals={detail?.signals ?? []}
                          selectedSignal={activeSignal}
                          labels={chartLabels}
                        />
                      ) : (
                        <EmptyState
                          icon={<CandlestickChart className="h-6 w-6" />}
                          title={t('wyckoff.detailEmptyTitle')}
                          description={t('wyckoff.detailEmptyDescription')}
                        />
                      )}
                    </div>

                    {activeSignal ? (
                      <div className="mt-3 grid gap-2 text-xs text-secondary-text md:grid-cols-3">
                        <div className="rounded-xl border border-border/70 bg-surface/50 px-3 py-2">
                          <div className="text-muted-text">{t('wyckoff.spring')}</div>
                          <div className="mt-1">
                            {activeSignal.features.spring.detected
                              ? `${t('wyckoff.breakDepth')} ${formatNumber(activeSignal.features.spring.breakDepth, 3)}`
                              : activeSignal.features.spring.reason ?? t('wyckoff.notDetected')}
                          </div>
                        </div>
                        <div className="rounded-xl border border-border/70 bg-surface/50 px-3 py-2">
                          <div className="text-muted-text">{t('wyckoff.test')}</div>
                          <div className="mt-1">
                            {activeSignal.features.test.detected
                              ? `${t('wyckoff.testVolumeRatio')} ${formatNumber(activeSignal.features.test.volumeRatio)}`
                              : activeSignal.features.test.reason ?? t('wyckoff.notDetected')}
                          </div>
                        </div>
                        <div className="rounded-xl border border-border/70 bg-surface/50 px-3 py-2">
                          <div className="text-muted-text">{t('wyckoff.trend')}</div>
                          <div className="mt-1">
                            {activeSignal.features.trend.ratio != null
                              ? `${t('wyckoff.trendRatio')} ${formatNumber(activeSignal.features.trend.ratio)} · ${t('wyckoff.upDownDays', {
                                up: activeSignal.features.trend.upDays,
                                down: activeSignal.features.trend.downDays,
                              })}`
                              : activeSignal.features.trend.reason ?? '--'}
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </>
                ) : null}
              </Card>
            </div>
          ) : null}
        </>
      )}
    </AppPage>
  );
};

export default WyckoffPage;
