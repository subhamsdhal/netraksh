import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import ProtectedRoute from '../src/components/ProtectedRoute';

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={['/secure']}>
      <Routes>
        <Route path="/login" element={<div>Operator login</div>} />
        <Route path="/secure" element={<ProtectedRoute><div>Command dashboard</div></ProtectedRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('protected dashboard routing', () => {
  it('redirects an unauthenticated operator to login', async () => {
    renderProtected();
    expect(await screen.findByText('Operator login')).toBeInTheDocument();
  });

  it('renders protected content with an existing session', async () => {
    localStorage.setItem('netraksh_token', 'test-token');
    renderProtected();
    expect(await screen.findByText('Command dashboard')).toBeInTheDocument();
  });
});
