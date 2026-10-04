import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CameraManagement, { validateRegistrationCoordinates } from '../src/pages/CameraManagement';

let currentRole = 'ADMIN';
let cameraRows = [];
const authFetchMock = vi.fn();

vi.mock('../src/hooks/useAuth', () => ({
  default: () => ({ role: currentRole, username: 'camera-admin', isAuthenticated: true }),
}));

vi.mock('../src/services/auth', () => ({
  authFetch: (...args) => authFetchMock(...args),
}));

const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const staleCamera = {
  camera_id: 'cam-real-test-01',
  name: 'Real Test Camera',
  location: 'Sector Test',
  latitude: null,
  longitude: null,
  health_state: 'DEGRADED',
  health_reason: 'fps_degraded',
  last_health_check: '2020-01-02T03:04:05',
};

describe('Camera Management truth and safety', () => {
  beforeEach(() => {
    currentRole = 'ADMIN';
    cameraRows = [staleCamera];
    authFetchMock.mockImplementation(async (path, options) => {
      if (path === '/cameras' && !options) return response(cameraRows);
      if (path === '/cameras' && options?.method === 'POST') return response({ camera_id: 'generated-id' }, 201);
      return response({});
    });
  });

  it('labels persisted health as last observed and visibly stale without replacing it with EDGE READY', async () => {
    render(<CameraManagement />);

    expect(await screen.findByRole('columnheader', { name: 'Last Camera Health' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Edge Health' })).not.toBeInTheDocument();
    expect(screen.getByText('DEGRADED · STALE')).toBeInTheDocument();
    expect(screen.getByText('fps_degraded')).toBeInTheDocument();
    expect(screen.getByText('Last observed 2020-01-02 03:04:05 UTC')).toBeInTheDocument();
    expect(screen.queryByText(/READY/)).not.toBeInTheDocument();
    expect(screen.getByText('cam-real-test-01')).toBeInTheDocument();
  });

  it('uses truthful registration and authorization wording', async () => {
    render(<CameraManagement />);
    await screen.findByText('Real Test Camera');

    expect(screen.getByText('Register Camera', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('Create camera record')).toBeInTheDocument();
    expect(screen.getByText('Camera Display Name')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Register Camera' })).toBeInTheDocument();
    expect(screen.getByText(/edge worker and stream setup are separate/i)).toBeInTheDocument();
    expect(screen.getByText('View registered cameras and map coordinates. Configuration changes require ADMIN.')).toBeInTheDocument();

    expect(screen.queryByText('Register Node')).not.toBeInTheDocument();
    expect(screen.queryByText('Provision new camera')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Provision Node' })).not.toBeInTheDocument();
    expect(screen.queryByText('Node Identifier')).not.toBeInTheDocument();
    expect(screen.queryByText(/ADMIN role only/i)).not.toBeInTheDocument();
  });

  it('renders partial backend coordinates safely', async () => {
    cameraRows = [{ ...staleCamera, latitude: 12.5, longitude: null }];
    render(<CameraManagement />);
    expect(await screen.findByText('— incomplete coordinates —')).toBeInTheDocument();
  });

  it('accepts both blank coordinates and omits them from the request', async () => {
    const user = userEvent.setup();
    render(<CameraManagement />);
    await screen.findByText('Real Test Camera');
    await user.type(screen.getByPlaceholderText('e.g. Border Post Gamma'), 'Camera Gamma');
    await user.type(screen.getByPlaceholderText('e.g. Sector 9'), 'Sector 9');
    await user.click(screen.getByRole('button', { name: 'Register Camera' }));

    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith('/cameras', expect.objectContaining({ method: 'POST' })));
    const post = authFetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(JSON.parse(post[1].body)).toEqual({ name: 'Camera Gamma', location: 'Sector 9' });
  });

  it('accepts zero coordinates and sends both values', async () => {
    const user = userEvent.setup();
    render(<CameraManagement />);
    await screen.findByText('Real Test Camera');
    await user.type(screen.getByPlaceholderText('e.g. Border Post Gamma'), 'Zero Camera');
    await user.type(screen.getByPlaceholderText('e.g. Sector 9'), 'Zero Point');
    await user.type(screen.getByPlaceholderText('Lat'), '0');
    await user.type(screen.getByPlaceholderText('Lon'), '0.0');
    await user.click(screen.getByRole('button', { name: 'Register Camera' }));

    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith('/cameras', expect.objectContaining({ method: 'POST' })));
    const post = authFetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(JSON.parse(post[1].body)).toEqual({
      name: 'Zero Camera', location: 'Zero Point', latitude: 0, longitude: 0,
    });
  });

  it.each([
    ['10', '', 'both be supplied'],
    ['', '20', 'both be supplied'],
    ['not-a-number', '20', 'finite numbers'],
    ['91', '20', 'between -90 and 90'],
    ['10', '181', 'between -180 and 180'],
  ])('rejects invalid coordinate pair (%s, %s)', async (latitude, longitude, message) => {
    const user = userEvent.setup();
    render(<CameraManagement />);
    await screen.findByText('Real Test Camera');
    await user.type(screen.getByPlaceholderText('e.g. Border Post Gamma'), 'Invalid Camera');
    await user.type(screen.getByPlaceholderText('e.g. Sector 9'), 'Invalid Point');
    if (latitude) await user.type(screen.getByPlaceholderText('Lat'), latitude);
    if (longitude) await user.type(screen.getByPlaceholderText('Lon'), longitude);
    await user.click(screen.getByRole('button', { name: 'Register Camera' }));

    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
    expect(authFetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });

  it('disables registration while the request is in flight and prevents a repeated submit', async () => {
    let finishRequest;
    authFetchMock.mockImplementation((path, options) => {
      if (path === '/cameras' && !options) return Promise.resolve(response(cameraRows));
      if (path === '/cameras' && options?.method === 'POST') {
        return new Promise((resolve) => { finishRequest = () => resolve(response({ camera_id: 'generated-id' }, 201)); });
      }
      return Promise.resolve(response({}));
    });
    const user = userEvent.setup();
    render(<CameraManagement />);
    await screen.findByText('Real Test Camera');
    await user.type(screen.getByPlaceholderText('e.g. Border Post Gamma'), 'One Request');
    await user.type(screen.getByPlaceholderText('e.g. Sector 9'), 'Sector 1');
    const button = screen.getByRole('button', { name: 'Register Camera' });
    await user.click(button);
    expect(screen.getByRole('button', { name: 'Registering...' })).toBeDisabled();
    fireEvent.submit(button.closest('form'));
    expect(authFetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    finishRequest();
    await screen.findByRole('button', { name: 'Register Camera' });
  });

  it('keeps mutation controls hidden for non-admin readers', async () => {
    currentRole = 'OPERATOR';
    render(<CameraManagement />);
    expect(await screen.findByText('Real Test Camera')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Set Location' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Register Camera' })).not.toBeInTheDocument();
  });

  it('does not hardcode production rows', async () => {
    cameraRows = [{ ...staleCamera, camera_id: 'fixture-only-camera', name: 'Fixture Only' }];
    render(<CameraManagement />);
    expect(await screen.findByText('fixture-only-camera')).toBeInTheDocument();
    expect(screen.queryByText('cam-border-01')).not.toBeInTheDocument();
    expect(screen.queryByText('cam-checkpoint-01')).not.toBeInTheDocument();
  });
});

describe('registration coordinate validation helper', () => {
  it('accepts two blank values', () => {
    expect(validateRegistrationCoordinates('', '  ')).toEqual({ coordinates: null, error: null });
  });

  it('rejects non-finite values', () => {
    expect(validateRegistrationCoordinates('Infinity', '0').error).toMatch(/finite/);
    expect(validateRegistrationCoordinates('NaN', '0').error).toMatch(/finite/);
  });
});
