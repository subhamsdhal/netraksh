import { useEffect, useState } from 'react';
import { startupWakeState, subscribeStartupWake } from '../services/startupWake';

// Read-only view of the process-wide coordinator. Consumers such as Header
// must hydrate state without starting a new readiness cycle when they mount.
export default function useStartupSnapshot() {
  const [snapshot, setSnapshot] = useState(() => startupWakeState());

  useEffect(() => subscribeStartupWake(setSnapshot), []);

  return snapshot;
}
