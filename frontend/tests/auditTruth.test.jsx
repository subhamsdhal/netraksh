import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ authFetch: vi.fn() }));

vi.mock('../src/services/auth', () => ({
  authFetch: (...args) => mocks.authFetch(...args),
}));

import Audit, { AUDIT_COLUMNS, formatAuditTimestampUtc } from '../src/pages/Audit';

const firstPage = {
  total: 42,
  skip: 0,
  limit: 25,
  has_newer: false,
  has_older: true,
  logs: [
    {
      id: 'log-user', timestamp: '2026-10-03T03:56:43Z', action: 'LOGIN_SUCCESS',
      user_id: '5f31704a-5aaf-4e94-8232-91fe891b9174', actor_type: 'USER', username: 'admin',
      attempted_username: null, resource_type: null, resource_id: null,
      ip_address: '10.31.245.18', success: true,
    },
    {
      id: 'log-event', timestamp: '2026-10-02T19:31:37Z', action: 'EVIDENCE_URL_GENERATED',
      user_id: '5f31704a-5aaf-4e94-8232-91fe891b9174', actor_type: 'USER', username: 'admin',
      attempted_username: null, resource_type: 'Event', resource_id: '494ed683-6eb4-44e8-bc4f-78be427e2646',
      ip_address: '10.25.136.6', success: true,
    },
    {
      id: 'log-system', timestamp: '2026-10-02T14:14:53Z', action: 'EDGE_KEY_BOOTSTRAPPED',
      user_id: null, actor_type: 'SYSTEM', username: null, attempted_username: null,
      resource_type: 'Camera', resource_id: 'cam-border-01', ip_address: '10.29.222.90', success: true,
    },
    {
      id: 'log-failed', timestamp: '2026-10-01T01:00:15Z', action: 'LOGIN_FAILED',
      user_id: null, actor_type: 'UNAUTHENTICATED', username: null, attempted_username: 'admin',
      resource_type: null, resource_id: null, ip_address: '10.29.222.90', success: false,
    },
  ],
};

const secondPage = {
  total: 42,
  skip: 25,
  limit: 25,
  has_newer: true,
  has_older: false,
  logs: [{
    id: 'old-log', timestamp: '2026-09-29T16:54:05Z', action: 'EDGE_KEY_BOOTSTRAPPED',
    user_id: null, actor_type: 'SYSTEM', username: null, attempted_username: null,
    resource_type: 'Camera', resource_id: 'cam-border-01', ip_address: '10.25.136.6', success: true,
  }],
};

function response(payload) {
  return Promise.resolve({ ok: true, json: async () => payload });
}

describe('Audit Trail truth and completeness', () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.authFetch.mockImplementation((path) => response(path.includes('skip=25') ? secondPage : firstPage));
  });

  it('uses truthful wording, UTC timestamps, and peer-IP provenance', async () => {
    render(<Audit />);

    expect(await screen.findByText('Audit Log')).toBeInTheDocument();
    expect(screen.getByText('System action log · Recorded operator and system activity')).toBeInTheDocument();
    expect(screen.queryByText(/Append-Only/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/All operator sessions recorded/i)).not.toBeInTheDocument();
    expect(screen.getByText('Timestamp (UTC)')).toBeInTheDocument();
    expect(screen.getByText('Request Peer IP')).toHaveAttribute('title', 'Network peer observed by the backend');
    expect(screen.getByText('03/10/2026, 03:56:43')).toBeInTheDocument();
    expect(formatAuditTimestampUtc('2026-10-03T03:56:43')).toBe('03/10/2026, 03:56:43');
  });

  it('shows human, system, and unauthenticated actors truthfully', async () => {
    render(<Audit />);

    expect(await screen.findAllByText('admin')).not.toHaveLength(0);
    expect(screen.getAllByText('id: 5f31704a…').length).toBeGreaterThan(0);
    expect(screen.getByText('SYSTEM')).toBeInTheDocument();
    expect(screen.getByText('UNAUTHENTICATED')).toBeInTheDocument();
    expect(screen.getByText('attempt: admin')).toBeInTheDocument();
    expect(screen.getByText('Failed', { selector: '.badge-danger' })).toBeInTheDocument();
    expect(screen.getAllByText(/Success/i).length).toBeGreaterThan(0);
  });

  it('uses one shared grid definition and exposes the full resource identity', async () => {
    render(<Audit />);

    const rows = await screen.findAllByTestId('audit-row');
    const header = screen.getByTestId('audit-header');
    expect(header.style.gridTemplateColumns).toBe('var(--audit-columns)');
    expect(rows.every(row => row.style.gridTemplateColumns === 'var(--audit-columns)')).toBe(true);
    expect(header.parentElement.style.getPropertyValue('--audit-columns')).toBe(AUDIT_COLUMNS);
    expect(screen.getByTitle('Event: 494ed683-6eb4-44e8-bc4f-78be427e2646')).toBeInTheDocument();
  });

  it('paginates older history without a silent fixed 100-row terminal view', async () => {
    render(<Audit />);

    expect(await screen.findByText('Showing 1–4 of 42 audit records')).toBeInTheDocument();
    expect(mocks.authFetch).toHaveBeenCalledWith('/api/audit?skip=0&limit=25');
    fireEvent.click(screen.getByRole('button', { name: 'Older' }));

    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledWith('/api/audit?skip=25&limit=25'));
    expect(await screen.findByText('Showing 26–26 of 42 audit records')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Newer' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled();
  });
});
