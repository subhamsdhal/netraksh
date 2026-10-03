import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ authFetch: vi.fn() }));

vi.mock('../src/services/auth', () => ({
  authFetch: (...args) => mocks.authFetch(...args),
}));

vi.mock('recharts', () => {
  const Component = ({ children }) => <div>{children}</div>;
  return {
    BarChart: Component,
    Bar: Component,
    XAxis: Component,
    YAxis: Component,
    CartesianGrid: Component,
    Tooltip: Component,
    ResponsiveContainer: Component,
    PieChart: Component,
    Pie: Component,
    Cell: Component,
    Legend: Component,
  };
});

import Analytics from '../src/pages/Analytics';
import { buildAnalyticsCsv } from '../src/utils/analyticsCsv';

const summary = {
  window: { since: '2026-10-02T03:31:00', until: '2026-10-03T03:31:00' },
  events: {
    raw_total: 9,
    detected: 7,
    abstain: 2,
    watchlist_matches: 0,
    anpr: 0,
    intrusion: 6,
    vehicle: 0,
    person: 7,
    verified_packages: 9,
    detection_rate_pct: 77.78,
    reliability: { average: 0.800827 },
    confidence: { average: 0.894845 },
  },
  alerts: { total: 0, acknowledged: 0, unresolved: 0, closed: 0 },
  cameras: { with_events: 1 },
  uptime_not_available: true,
};

const timeseries = {
  series: [{ bucket: '2026-10-02 14:00:00', total: 7, watchlist: 0, intrusion: 6, vehicle: 0, person: 7 }],
};
const byType = { by_type: [{ event_type: 'LOITERING', count: 6 }, { event_type: 'VIRTUAL_FENCE_CROSSING', count: 1 }] };
const byCamera = { by_camera: [{ camera_id: 'cam-border-01', camera_name: 'Border 01', count: 7 }] };
const bySeverity = { by_severity: [{ severity: 'MEDIUM', count: 7 }] };

function response(payload) {
  return Promise.resolve({ ok: true, json: async () => payload });
}

function card(label) {
  return screen.getByText(label).closest('.stat-card');
}

describe('Analytics event-scope truth', () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.authFetch.mockImplementation((path) => {
      if (path.startsWith('/analytics/summary')) return response(summary);
      if (path.startsWith('/analytics/timeseries')) return response(timeseries);
      if (path.startsWith('/analytics/by-type')) return response(byType);
      if (path.startsWith('/analytics/by-camera')) return response(byCamera);
      if (path.startsWith('/analytics/by-severity')) return response(bySeverity);
      if (path === '/analytics/options') return response({ streams: [], cameras: [], event_types: [] });
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it('renders raw, detected, and ABSTAIN totals as distinct backend-driven metrics', async () => {
    render(<Analytics />);

    expect(await screen.findByText('Total Event Records')).toBeInTheDocument();
    expect(card('Total Event Records')).toHaveTextContent('9');
    expect(card('Detected')).toHaveTextContent('7');
    expect(card('ABSTAIN')).toHaveTextContent('2');
    expect(card('Intrusions')).toHaveTextContent('6');
    expect(card('Detection Rate')).toHaveTextContent('77.78%');
    expect(card('Cameras With Events')).toHaveTextContent('1');
    expect(screen.queryByText('Active Cameras')).not.toBeInTheDocument();
    expect(screen.queryByText('Total Events')).not.toBeInTheDocument();
    expect(screen.getByText('Metrics below use the selected time window and filters.')).toBeInTheDocument();
  });

  it('labels detected-only charts without inventing ABSTAIN event classes or severity', async () => {
    render(<Analytics />);

    expect(await screen.findByText('Detected Events By Type')).toBeInTheDocument();
    expect(screen.getByText('Detected Severity Distribution')).toBeInTheDocument();
    expect(screen.getByText('Temporal Detected Incident Frequency')).toBeInTheDocument();
    expect(screen.queryByText('UNKNOWN')).not.toBeInTheDocument();
    expect(screen.queryByText('NONE')).not.toBeInTheDocument();
  });

  it('exports corrected event-scope labels and values', () => {
    const csv = buildAnalyticsCsv(summary, timeseries, byType, byCamera, bySeverity);

    expect(csv).toContain('Total Event Records,9');
    expect(csv).toContain('Detected,7');
    expect(csv).toContain('ABSTAIN,2');
    expect(csv).toContain('Detection Rate,77.78');
    expect(csv).toContain('Verified Event Packages,9');
    expect(csv).toContain('Cameras With Events,1');
    expect(csv).not.toContain('Total Events,7');
    expect(csv).not.toContain('Active Cameras');
  });
});
