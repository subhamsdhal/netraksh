export function adminDiagnosticsEnabled(role, search = '') {
  return String(role || '').toUpperCase() === 'ADMIN'
    && new URLSearchParams(search).get('debug') === '1';
}
