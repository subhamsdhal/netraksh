import { CheckCircle, Cloud, AlertCircle, WifiOff, ChevronRight, ChevronLeft, FlaskConical } from 'lucide-react';
import { useState } from 'react';
import useDemoScenario from '../hooks/useDemoScenario';
import { authFetch } from '../services/auth';

// DemoSidebar — floating demo scenario control panel.
// Collapsed by default, toggled open by the tab button on the left edge.
export default function DemoSidebar() {
  const { scenario, setScenario } = useDemoScenario();
  const [open, setOpen] = useState(false);

  // What each scenario actually does in the pipeline (not marketing copy):
  const SCENARIO_META = {
    normal: {
      icon: CheckCircle,
      title: 'Normal Ops',
      desc: 'Full pipeline · YOLO detects → R computed → DETECTED if R ≥ 0.75',
    },
    fog: {
      icon: Cloud,
      title: 'Dense Fog',
      desc: 'Frame blurred → FOG_RAIN → S drops → may produce UNCERTAIN',
    },
    failure: {
      icon: AlertCircle,
      title: 'Sensor Failure',
      desc: 'Frozen frames → FAILED → Gate 1 hard-override → ABSTAIN',
    },
    offline: {
      icon: WifiOff,
      title: 'Offline State',
      desc: 'SyncClient pauses → events queue locally → header shows BUFFERING',
    },
  };

  const handleScenario = async (id) => {
    setScenario(id);
    try {
      await authFetch('/demo/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: id }),
      });
    } catch (e) {
      console.debug('[DemoSidebar] POST /demo/scenario failed (non-fatal):', e);
    }
  };

  return (
    <>
      {/* Toggle Tab */}
      <button
        onClick={() => setOpen(!open)}
        title="Demo Scenario Controls"
        style={{
          position: 'fixed',
          right: open ? 260 : 0,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 35,
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-color)',
          borderRight: open ? '1px solid var(--border-color)' : 'none',
          borderRadius: open ? '4px 0 0 4px' : '4px 0 0 4px',
          padding: '0.75rem 0.375rem',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.5rem',
          cursor: 'pointer',
          color: 'var(--text-muted)',
          transition: 'right 0.25s ease',
        }}
      >
        <FlaskConical size={13} style={{ color: 'var(--accent)' }} />
        <span
          style={{
            writingMode: 'vertical-rl',
            textOrientation: 'mixed',
            transform: 'rotate(180deg)',
            fontSize: '0.5rem',
            fontFamily: 'var(--font-display)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--text-dim)',
          }}
        >
          Demo
        </span>
        {open ? <ChevronRight size={11} /> : <ChevronLeft size={11} />}
      </button>

      {/* Panel */}
      <aside
        style={{
          position: 'fixed',
          right: 0,
          top: 0,
          bottom: 0,
          width: 260,
          background: 'var(--bg-panel)',
          borderLeft: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          padding: '1.25rem 1rem',
          zIndex: 30,
          transform: open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.25s ease',
          overflowY: 'auto',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            marginBottom: '1.25rem',
            paddingBottom: '1rem',
            borderBottom: '1px solid var(--border-color)',
          }}
        >
          <FlaskConical size={14} style={{ color: 'var(--accent)' }} />
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: '0.65rem',
              fontWeight: 700,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--text-muted)',
            }}
          >
            Demo Scenario Control
          </span>
          <div
            style={{
              marginLeft: 'auto',
              fontSize: '0.5rem',
              fontFamily: 'var(--font-display)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              padding: '0.1rem 0.4rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-accent)',
              color: 'var(--accent)',
              background: 'var(--accent-dim)',
            }}
          >
            Simulated
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
          {Object.entries(SCENARIO_META).map(([id, { icon: Icon, title, desc }]) => {
            const isActive = scenario === id;
            return (
              <button
                key={id}
                onClick={() => handleScenario(id)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  textAlign: 'left',
                  padding: '0.75rem',
                  borderRadius: 'var(--radius-md)',
                  border: isActive
                    ? `1px solid ${id === 'normal' ? 'var(--color-ok)' : 'var(--color-warning)'}`
                    : '1px solid var(--border-color)',
                  background: isActive ? 'var(--bg-elevated)' : 'transparent',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  width: '100%',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                  <Icon
                    size={14}
                    style={{
                      color: isActive
                        ? id === 'normal' ? 'var(--color-ok)' : 'var(--color-warning)'
                        : 'var(--text-muted)',
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: '0.72rem',
                      fontWeight: 600,
                      color: isActive ? 'var(--text-main)' : 'var(--text-muted)',
                    }}
                  >
                    {title}
                  </span>
                  {isActive && (
                    <span
                      style={{
                        marginLeft: 'auto',
                        fontSize: '0.5rem',
                        fontFamily: 'var(--font-display)',
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        padding: '0.1rem 0.3rem',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--color-ok)',
                        color: 'var(--color-ok)',
                        background: 'rgba(34,211,164,0.08)',
                      }}
                    >
                      Active
                    </span>
                  )}
                </div>
                <span
                  style={{
                    fontSize: '0.65rem',
                    color: 'var(--text-dim)',
                    fontFamily: 'var(--font-body)',
                    lineHeight: 1.5,
                  }}
                >
                  {desc}
                </span>
              </button>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 'auto',
            paddingTop: '1rem',
            borderTop: '1px solid var(--border-color)',
            fontSize: '0.6rem',
            color: 'var(--text-dim)',
            fontFamily: 'var(--font-body)',
            lineHeight: 1.5,
          }}
        >
          Scenario changes take effect on the next edge polling cycle (~5s).
          Events generated during simulation are real and persisted.
        </div>
      </aside>
    </>
  );
}
