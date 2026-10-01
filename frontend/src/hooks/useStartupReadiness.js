import { useEffect, useState } from 'react';
import {
  requestStartupWake,
  startupWakeState,
  subscribeStartupWake,
} from '../services/startupWake';

export default function useStartupReadiness() {
  const [state, setState] = useState(() => startupWakeState());

  useEffect(() => {
    const unsubscribe = subscribeStartupWake(setState);
    requestStartupWake();
    return unsubscribe;
  }, []);

  return state;
}
