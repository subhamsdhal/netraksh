import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AlertTriangle, WifiOff } from 'lucide-react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import DemoSidebar from './components/DemoSidebar';
import { DemoScenarioProvider } from './hooks/useDemoScenario';
import ProtectedRoute from './components/ProtectedRoute';

import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import DashboardErrorBoundary from './components/DashboardErrorBoundary';
import Evidence from './pages/Evidence';
import Health from './pages/Health';
import Architecture from './pages/Architecture';
import Alerts from './pages/Alerts';
import Performance from './pages/Performance';
import CameraManagement from './pages/CameraManagement';
import Watchlist from './pages/Watchlist';
import MapView from './pages/Map';
import Analytics from './pages/Analytics';
import Audit from './pages/Audit';

function AppLayout() {
  const [isWsConnected, setIsWsConnected] = useState(true);

  useEffect(() => {
    const handleConnect    = () => setIsWsConnected(true);
    const handleDisconnect = () => setIsWsConnected(false);

    window.addEventListener('netraksh-ws-connect',    handleConnect);
    window.addEventListener('netraksh-ws-disconnect', handleDisconnect);

    return () => {
      window.removeEventListener('netraksh-ws-connect',    handleConnect);
      window.removeEventListener('netraksh-ws-disconnect', handleDisconnect);
    };
  }, []);

  return (
    <div className="app-container relative">
      {/* WebSocket disconnect overlay */}
      {!isWsConnected && (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ background: 'rgba(8,14,26,0.88)', backdropFilter: 'blur(4px)', zIndex: 100 }}
        >
          <div
            className="flex flex-col items-center gap-4 text-center"
            style={{
              border: '1px solid rgba(239,68,68,0.4)',
              padding: '2.5rem 3rem',
              background: 'rgba(239,68,68,0.07)',
              borderRadius: 'var(--radius-xl)',
              boxShadow: '0 0 40px rgba(239,68,68,0.2)',
            }}
          >
            <WifiOff size={48} className="text-danger animate-pulse" />
            <div className="flex flex-col gap-2">
              <span
                className="font-display font-bold tracking-widest text-danger animate-pulse"
                style={{ fontSize: '1rem', textTransform: 'uppercase', letterSpacing: '0.15em' }}
              >
                Telemetry Link Severed
              </span>
              <span
                className="font-mono text-muted"
                style={{ fontSize: '0.7rem', letterSpacing: '0.06em' }}
              >
                Reestablishing secure WebSocket connection…
              </span>
            </div>
          </div>
        </div>
      )}

      <Sidebar />
      <Header />

      <main className="main-content">
        <Routes>
          <Route path="/"                   element={<DashboardErrorBoundary><Dashboard /></DashboardErrorBoundary>} />
          <Route path="/map"                element={<MapView />} />
          <Route path="/camera-health"      element={<Health />} />
          <Route path="/evidence"           element={<Evidence />} />
          <Route path="/cross-command-alerts" element={<Alerts />} />
          <Route path="/performance"        element={<Performance />} />
          <Route path="/watchlist"          element={<Watchlist />} />
          <Route path="/camera-management"  element={<CameraManagement />} />
          <Route path="/architecture"       element={<Architecture />} />
          <Route path="/analytics"          element={<Analytics />} />
          <Route path="/audit"              element={<Audit />} />
        </Routes>
      </main>

      {import.meta.env.DEV && <DemoSidebar />}
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <DemoScenarioProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          />
        </Routes>
      </DemoScenarioProvider>
    </BrowserRouter>
  );
}

export default App;
