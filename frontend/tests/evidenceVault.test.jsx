import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Evidence from '../src/pages/Evidence';
import { authFetch } from '../src/services/auth';

vi.mock('../src/services/auth', () => ({ authFetch: vi.fn() }));

const item = {
  event_id: 'evt-12345678', camera_id: 'cam-border-01', stream_id: 'session-a',
  timestamp: '2026-09-25T13:18:01.643Z', event_type: 'LOITERING',
  detection_class: 'person', confidence: 0.9, scene_condition: 'CLEAR_DAY',
  camera_health_state: 'OK', decision_state: 'DETECTED', zone_id: 'zone-a',
  hash: 'a'.repeat(64), signature: 'b'.repeat(128), hash_valid: true,
  signature_valid: true, chain_valid: false, chain_status: 'PENDING',
  verified_ok: false, artifact_state: 'AVAILABLE',
  storage_provider: 'local', storage_status: 'AVAILABLE', content_size: 2048,
  schema_version: '1.0', crypto_version: '1.0', kid: 'kid-a',
  evidence_created_at: '2026-09-25T13:18:02Z', previous_hash: 'c'.repeat(64),
};

describe('Evidence Vault authoritative listing', () => {
  beforeEach(() => {
    global.ResizeObserver = class { observe() {} disconnect() {} };
    URL.createObjectURL = vi.fn(() => 'blob:evidence');
    URL.revokeObjectURL = vi.fn();
    authFetch.mockImplementation(async (url) => {
      if (url.includes('/evidence-image')) return { ok: true, status: 200, blob: async () => new Blob(['jpeg']) };
      if (url.startsWith('/events/evidence-vault?')) return { ok: true, json: async () => ({ items: [item], total: 120, limit: 50, offset: 0 }) };
      throw new Error(`Unexpected URL ${url}`);
    });
  });

  it('shows independent hash, signature, chain, storage and mock-anchor truth', async () => {
    render(<Evidence />);
    expect(await screen.findByText(/Evidence Vault · 120/)).toBeInTheDocument();
    expect(screen.getAllByText('CHAIN PENDING').length).toBeGreaterThan(0);
    expect(screen.getAllByText('HASH VALID').length).toBeGreaterThan(0);
    expect(screen.getAllByText('SIG VALID').length).toBeGreaterThan(0);
    expect(screen.getByText('UNAVAILABLE (MOCK)')).toBeInTheDocument();
    expect(screen.getByText(/PENDING — PREDECESSOR NOT YET RESOLVED/)).toBeInTheDocument();
    expect(screen.getByText(/local · AVAILABLE · 2.0 KB/)).toBeInTheDocument();
  });

  it('uses server-side search and deterministic pagination', async () => {
    render(<Evidence />);
    await screen.findByText(/Evidence Vault · 120/);
    fireEvent.change(screen.getByPlaceholderText('Search by ID or Hash...'), { target: { value: 'evt-1234' } });
    await waitFor(() => expect(authFetch.mock.calls.some(([url]) => url.includes('search=evt-1234'))).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'NEXT' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([url]) => url.includes('offset=50'))).toBe(true));
  });

  it('presents verified metadata-only evidence without requesting or retrying a binary', async () => {
    const metadataOnly = {
      ...item,
      event_id: '88a4057c-409d-4862-bc6f-624607eb5822',
      decision_state: 'ABSTAIN',
      decision_reason: 'clock_drift',
      artifact_state: 'METADATA_ONLY',
      storage_provider: 'local',
      storage_status: 'CREATED',
      content_size: null,
      content_hash: null,
      edge_device_id: 'cam-border-01',
      verified_ok: true,
      hash_valid: true,
      signature_valid: true,
      chain_valid: true,
      chain_status: 'VALID',
      score_d: null,
      score_t: null,
      score_s: null,
      score_h: null,
      score_r: null,
    };
    authFetch.mockImplementation(async (url) => {
      if (url.startsWith('/events/evidence-vault?')) {
        return { ok: true, json: async () => ({ items: [metadataOnly], total: 1, limit: 50, offset: 0 }) };
      }
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<Evidence />);

    expect(await screen.findByText('METADATA-ONLY EVIDENCE')).toBeInTheDocument();
    expect(screen.getAllByText(/NO BINARY ARTIFACT/).length).toBeGreaterThan(0);
    expect(screen.getByText('METADATA ONLY · NO BINARY ARTIFACT')).toBeInTheDocument();
    expect(screen.getByText('EVIDENCE VERIFIED')).toBeInTheDocument();
    expect(screen.getByText('EDGE PRODUCER')).toBeInTheDocument();
    expect(screen.getAllByText('cam-border-01').length).toBeGreaterThan(0);
    expect(screen.getByText('clock_drift')).toBeInTheDocument();
    expect(screen.getByText('UNAVAILABLE (MOCK)')).toBeInTheDocument();
    expect(screen.queryByText(/SYNCING EVIDENCE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CH-04/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\(Active\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.40 × D/)).not.toBeInTheDocument();
    expect(authFetch.mock.calls.some(([url]) => url.includes('/evidence-image'))).toBe(false);
  });

  it('keeps genuinely pending binary evidence in the bounded syncing flow', async () => {
    const pending = { ...item, artifact_state: 'SYNCING', storage_status: 'UPLOADING' };
    authFetch.mockImplementation(async (url) => {
      if (url.includes('/evidence-image')) return { ok: false, status: 425 };
      if (url.startsWith('/events/evidence-vault?')) {
        return { ok: true, json: async () => ({ items: [pending], total: 1, limit: 50, offset: 0 }) };
      }
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<Evidence />);
    expect(await screen.findByText('SYNCING EVIDENCE...')).toBeInTheDocument();
    expect(authFetch.mock.calls.filter(([url]) => url.includes('/evidence-image'))).toHaveLength(1);
  });

  it('keeps available binary preview and only recorded reliability factors', async () => {
    const available = {
      ...item,
      edge_device_id: 'cam-border-01',
      score_d: 0.9,
      score_t: null,
      score_s: 0.8,
      score_h: null,
      score_r: 0.85,
    };
    authFetch.mockImplementation(async (url) => {
      if (url.includes('/evidence-image')) {
        return { ok: true, status: 200, blob: async () => new Blob(['jpeg']) };
      }
      if (url.startsWith('/events/evidence-vault?')) {
        return { ok: true, json: async () => ({ items: [available], total: 1, limit: 50, offset: 0 }) };
      }
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<Evidence />);

    expect(await screen.findByAltText('Decrypted evidence frame')).toBeInTheDocument();
    expect(screen.getByText('local · AVAILABLE · 2.0 KB')).toBeInTheDocument();
    expect(screen.getByText('CAM-BORDER-01 · EVIDENCE PREVIEW')).toBeInTheDocument();
    expect(screen.getByText('D = 0.90 | S = 0.80 | R = 0.850')).toBeInTheDocument();
    expect(screen.queryByText(/T =/)).not.toBeInTheDocument();
    expect(screen.queryByText(/H =/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.40 × D/)).not.toBeInTheDocument();
  });
});
