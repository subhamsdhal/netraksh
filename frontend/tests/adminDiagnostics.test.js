import { describe, expect, it } from 'vitest';
import { adminDiagnosticsEnabled } from '../src/utils/adminDiagnostics';

describe('admin diagnostics visibility', () => {
  it('hides diagnostics on the normal Command Center page', () => {
    expect(adminDiagnosticsEnabled('ADMIN', '')).toBe(false);
  });

  it('allows an authenticated admin to opt into diagnostics', () => {
    expect(adminDiagnosticsEnabled('ADMIN', '?debug=1')).toBe(true);
  });

  it('does not expose diagnostics to non-admin users even with the debug flag', () => {
    expect(adminDiagnosticsEnabled('OPERATOR', '?debug=1')).toBe(false);
  });
});
