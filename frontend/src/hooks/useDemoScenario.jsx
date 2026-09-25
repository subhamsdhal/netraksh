import { createContext, useContext, useState } from 'react';

// Shared demo-scenario state. Previously local to DemoSidebar.jsx alone —
// clicking a scenario button toggled that button's own highlight and
// nothing else anywhere in the app (confirmed: no other component read
// DemoSidebar's state, and it lived only in that one component). The
// buttons also called /demo/inject-condition, /demo/trigger-camera-failure,
// /demo/simulate-offline — none of which exist anywhere in the backend
// (no backend/api/demo.py or equivalent router), so every click also threw
// a real 401/404 into the console for no benefit. This context makes the
// scenario a real, shared, app-level piece of state so other components
// (VideoFeed, Header) can honestly react to it, and removes the dead
// backend calls entirely rather than leaving them silently failing.
const DemoScenarioContext = createContext({
  scenario: 'normal',
  setScenario: () => {},
});

export function DemoScenarioProvider({ children }) {
  const [scenario, setScenario] = useState('normal'); // 'normal' | 'fog' | 'failure' | 'offline'
  return (
    <DemoScenarioContext.Provider value={{ scenario, setScenario }}>
      {children}
    </DemoScenarioContext.Provider>
  );
}

export default function useDemoScenario() {
  return useContext(DemoScenarioContext);
}
