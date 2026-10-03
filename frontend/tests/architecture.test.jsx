import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Architecture from '../src/pages/Architecture';
import { authFetch } from '../src/services/auth';

vi.mock('../src/services/auth', () => ({
  authFetch: vi.fn(),
}));

const capabilities = {
  evidence: { durable_storage: true, storage_provider: 's3' },
  blockchain: { mode: 'mock', simulated: true },
};

function response(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('Architecture production truth', () => {
  beforeEach(() => {
    authFetch.mockReset();
    authFetch.mockResolvedValue(response(capabilities));
  });

  it('separates implemented capability wording from selected deployment configuration', async () => {
    render(<Architecture />);
    await settle();

    expect(screen.getByText('Architecture overview showing implemented capabilities and selected current configuration.')).toBeInTheDocument();
    expect(screen.queryByText(/Runtime-aware architecture view/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Camera health evaluation during active frame processing/)).toBeInTheDocument();
    expect(screen.queryByText(/Continuous camera health monitoring/i)).not.toBeInTheDocument();

    expect(screen.getByText('CURRENT RUNTIME')).toBeInTheDocument();
    expect(screen.getByText('CPU / ONNX')).toBeInTheDocument();
    expect(screen.queryByText(/CPU Only \(No GPU\)/i)).not.toBeInTheDocument();
    expect(screen.getByText('SEE EDGE PERFORMANCE')).toBeInTheDocument();
    expect(screen.queryByText(/LIVE · SEE EDGE PERFORMANCE/i)).not.toBeInTheDocument();
  });

  it('preserves the real formula and explains scored, fallback, abstain, and rejected candidates', async () => {
    render(<Architecture />);
    await settle();

    expect(screen.getByText('R = 0.40D + 0.20T + 0.20S + 0.20H')).toBeInTheDocument();
    expect(screen.getByText(/Scored event, R ≥ 0.75/)).toBeInTheDocument();
    expect(screen.getByText('Low-score / fallback event')).toBeInTheDocument();
    expect(screen.getByText('Failed-health override; no R')).toBeInTheDocument();
    expect(screen.getByText('Candidates may also be rejected without emitting an event.')).toBeInTheDocument();
  });

  it('qualifies the outbox and renders accurate package, content-hash, and tamper semantics', async () => {
    render(<Architecture />);
    await settle();

    expect(screen.getByText(/retries temporary connectivity failures/)).toHaveTextContent('Persistence is limited to the current edge filesystem.');
    expect(screen.getByText(/Signed package hash:/).parentElement).toHaveTextContent('canonical event metadata and previous-hash linkage');
    expect(screen.getByText(/Evidence content hash:/).parentElement).toHaveTextContent('stored encrypted evidence bytes when binary evidence is present');
    expect(screen.getByText(/Ed25519 signatures and hash-chain linkage/)).toHaveTextContent('tamper detection and evidence integrity verification');
    expect(screen.queryByText(/bounding boxes, imagery, JSON/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/immutable/i)).not.toBeInTheDocument();
    expect(screen.getByText('Local Chain')).toBeInTheDocument();
    expect(screen.getByText('Durable object storage: CONFIGURED')).toBeInTheDocument();
  });

  it('uses factual mock-ledger language without developer-host or severity claims', async () => {
    render(<Architecture />);
    await settle();

    expect(screen.getByText('MOCK MODE')).toBeInTheDocument();
    expect(screen.getByText('Simulated Blockchain Mode')).toBeInTheDocument();
    expect(screen.getByText('Fabric integration is inactive in the current deployment.')).toBeInTheDocument();
    expect(screen.getByText('MOCK / SIMULATED mode. No production blockchain confirmation is implied.')).toBeInTheDocument();
    expect(screen.queryByText(/HIGH SEVERITY/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/WSL2|Docker required/i)).not.toBeInTheDocument();
  });

  it('does not synthesize storage or ledger state when capabilities are unavailable', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });
    render(<Architecture />);
    await settle();

    expect(screen.getByText('Durable object storage: RUNTIME STATUS UNAVAILABLE')).toBeInTheDocument();
    expect(screen.getByText('STATUS UNAVAILABLE')).toBeInTheDocument();
    expect(screen.getByText('Ledger Mode Unavailable')).toBeInTheDocument();
    expect(screen.queryByText('MOCK MODE')).not.toBeInTheDocument();
  });

  it('keeps four ordered stages with only adjacent connectors and a coherent narrow-flow rule', async () => {
    const { container } = render(<Architecture />);
    await settle();

    const flow = screen.getByTestId('architecture-stage-flow');
    expect(screen.getAllByTestId('architecture-stage-card')).toHaveLength(4);
    expect(screen.getAllByTestId('architecture-stage-connector')).toHaveLength(3);
    expect(flow.textContent.indexOf('STAGE 01')).toBeLessThan(flow.textContent.indexOf('STAGE 02'));
    expect(flow.textContent.indexOf('STAGE 02')).toBeLessThan(flow.textContent.indexOf('STAGE 03'));
    expect(flow.textContent.indexOf('STAGE 03')).toBeLessThan(flow.textContent.indexOf('STAGE 04'));

    const responsiveCss = container.querySelector('style').textContent;
    expect(responsiveCss).toContain('@media (max-width: 980px)');
    expect(responsiveCss).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(responsiveCss).toContain('transform: rotate(90deg)');
  });
});
