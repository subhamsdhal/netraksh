import { Server, Camera, ShieldCheck, Database, Link, ArrowRight, CheckCircle, Activity, HardDrive, Cpu, Network } from 'lucide-react';
import { useEffect, useState } from 'react';
import { authFetch } from '../services/auth';

export default function Architecture() {
  const [capabilities, setCapabilities] = useState(null);
  useEffect(() => {
    authFetch('/system/capabilities').then((response) => response.ok ? response.json() : null).then(setCapabilities).catch(() => setCapabilities(null));
  }, []);
  const storageReported = capabilities?.evidence != null;
  const blockchainReported = capabilities?.blockchain != null;
  const simulatedLedger = capabilities?.blockchain?.simulated === true;
  const durableStorage = capabilities?.evidence?.durable_storage === true;
  const ArchNode = ({ step, title, subtitle, icon: Icon, children, isCore, glowColor }) => (
    <div 
      className={`architecture-stage-card bg-panel border rounded flex flex-col ${isCore ? 'border-ok glow-ok' : 'border-color'}`}
      data-testid="architecture-stage-card"
      style={{ 
        flex: 1,
        minWidth: 0,
        padding: '1.25rem',
        background: 'linear-gradient(145deg, rgba(15,23,42,0.8) 0%, rgba(15,23,42,0.4) 100%)',
        boxShadow: isCore ? '0 8px 32px rgba(74,222,128,0.1)' : '0 4px 20px rgba(0,0,0,0.2)',
        position: 'relative',
        overflow: 'hidden',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-4px)';
        e.currentTarget.style.boxShadow = isCore ? '0 12px 40px rgba(74,222,128,0.5)' : `0 12px 30px ${glowColor || 'rgba(255,255,255,0.05)'}`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = isCore ? '0 8px 32px rgba(74,222,128,0.1)' : '0 4px 20px rgba(0,0,0,0.2)';
      }}
    >
      {/* Top Border Accent */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: glowColor || (isCore ? '#4ade80' : 'rgba(255,255,255,0.1)') }}></div>

      <div className="flex items-center justify-between gap-2 mb-4 pb-3 border-b border-color">
        <div className="flex items-center gap-2" style={{ color: isCore ? '#4ade80' : '#e2e8f0' }}>
          <Icon size={18} />
          <span className="text-xs font-display uppercase tracking-widest">{title}</span>
        </div>
        <span className="text-[10px] font-display text-muted bg-dark px-2 py-1 rounded border border-color">{step}</span>
      </div>
      <h3 className="text-main font-display mb-3" style={{ fontSize: '1.1rem', letterSpacing: '0.05em' }}>{subtitle}</h3>
      <div className="text-sm font-body text-muted flex-grow">
        {children}
      </div>
    </div>
  );

  const Connector = () => (
    <div className="architecture-stage-connector flex items-center justify-center text-muted" data-testid="architecture-stage-connector" aria-hidden="true">
      <ArrowRight size={20} />
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6" style={{ overflowY: 'auto', paddingRight: '12px', paddingBottom: '2rem' }}>
      
      {/* Header */}
      <div className="section-header flex-shrink-0">
        <div>
          <h2 className="section-title">System Architecture</h2>
          <div className="section-sub">
            Architecture overview showing implemented capabilities and selected current configuration.
          </div>
        </div>
      </div>

      <style>{`
        .architecture-stage-flow {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 20px minmax(0, 1fr) 20px minmax(0, 1fr) 20px minmax(0, 1fr);
          gap: 0.5rem;
          align-items: stretch;
        }
        .architecture-stage-connector {
          min-width: 0;
          padding: 0;
          opacity: 0.5;
        }
        @media (max-width: 980px) {
          .architecture-stage-flow {
            grid-template-columns: minmax(0, 1fr);
          }
          .architecture-stage-connector {
            min-height: 20px;
            transform: rotate(90deg);
          }
        }
      `}</style>

      {/* Main Pipeline Container */}
      <div style={{
        background: 'radial-gradient(circle at 50% -20%, rgba(255,255,255,0.03) 0%, transparent 70%)',
        padding: '1.5rem',
        borderRadius: '0.75rem',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        gap: '2rem'
      }}>
        
        {/* Four-stage flow: one row on desktop, explicit vertical connectors when stacked. */}
        <div className="architecture-stage-flow" data-testid="architecture-stage-flow">
          
          <ArchNode step="STAGE 01" title="Sensor Input" subtitle="Video Ingestion" icon={Camera} glowColor="rgba(56,189,248,0.5)">
            <div className="flex flex-col gap-3">
              <div className="flex items-start gap-2">
                <Activity size={14} className="mt-1 text-main opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.4' }}>Processes live RTSP streams or local video files (demo mode).</span>
              </div>
              <div className="flex items-start gap-2">
                <ShieldCheck size={14} className="mt-1 text-main opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.4' }}>Camera health evaluation during active frame processing (blur, exposure, sync drift).</span>
              </div>
            </div>
          </ArchNode>

          <Connector />

          <ArchNode step="STAGE 02" title="Edge Node" subtitle="CPU Inference Engine" icon={Cpu} glowColor="rgba(167,139,250,0.5)">
            <div className="flex flex-col gap-3">
              <div className="flex justify-between items-center text-xs border-b border-color pb-2">
                <span className="opacity-70">MODEL</span>
                <span className="text-main font-mono bg-dark px-1.5 py-0.5 rounded border border-color">YOLOv8n + ByteTrack</span>
              </div>
              <div className="flex justify-between items-center text-xs border-b border-color pb-2">
                <span className="opacity-70">CURRENT RUNTIME</span>
                <span className="text-main font-mono bg-dark px-1.5 py-0.5 rounded border border-color">CPU / ONNX</span>
              </div>
              <div className="flex justify-between items-center text-xs pb-1">
                <span className="opacity-70">METRICS</span>
                <span className="text-main font-mono bg-dark px-1.5 py-0.5 rounded border border-color">SEE EDGE PERFORMANCE</span>
              </div>
            </div>
          </ArchNode>

          <Connector />

          <ArchNode step="STAGE 03" title="Reliability Engine" subtitle="Confidence Filter" icon={ShieldCheck} isCore={true}>
            <div className="flex flex-col gap-3">
              <div className="text-xs font-mono bg-dark p-2 rounded text-center border border-ok text-ok glow-ok mb-1" style={{ letterSpacing: '0.05em' }}>
                R = 0.40D + 0.20T + 0.20S + 0.20H
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-xs font-display">
                  <div className="w-2 h-2 rounded-full bg-ok flex-shrink-0" style={{ boxShadow: '0 0 8px #4ade80' }}></div>
                  <span className="text-ok w-16 flex-shrink-0">DETECTED</span>
                  <span className="text-muted opacity-80">Scored event, R &ge; 0.75</span>
                </div>
                <div className="flex items-center gap-2 text-xs font-display">
                  <div className="w-2 h-2 rounded-full bg-warning flex-shrink-0" style={{ boxShadow: '0 0 8px #fbbf24' }}></div>
                  <span className="text-warning w-16 flex-shrink-0">UNCERTAIN</span>
                  <span className="text-muted opacity-80">Low-score / fallback event</span>
                </div>
                <div className="flex items-center gap-2 text-xs font-display">
                  <div className="w-2 h-2 rounded-full bg-neutral flex-shrink-0"></div>
                  <span className="text-neutral w-16 flex-shrink-0">ABSTAIN</span>
                  <span className="text-muted opacity-80">Failed-health override; no R</span>
                </div>
              </div>
              <div className="text-[10px] text-muted opacity-80 border-t border-color pt-2">
                Candidates may also be rejected without emitting an event.
              </div>
            </div>
          </ArchNode>

          <Connector />

          <ArchNode step="STAGE 04" title="Command API" subtitle="Backend Aggregator" icon={Server} glowColor="rgba(244,114,182,0.5)">
            <div className="flex flex-col gap-3">
              <div className="flex items-start gap-2">
                <HardDrive size={14} className="mt-1 text-main opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.4' }}>Local SQLite outbox buffers events and retries temporary connectivity failures. Persistence is limited to the current edge filesystem.</span>
              </div>
              <div className="flex items-start gap-2">
                <Network size={14} className="mt-1 text-main opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.4' }}>FastAPI handles synchronization and cross-camera corroboration.</span>
              </div>
            </div>
          </ArchNode>

        </div>

        {/* Divider / Transition Text */}
        <div className="flex items-center gap-3 text-xs text-muted font-body pt-4 border-t border-color">
          <ArrowRight size={14} className="opacity-50" style={{ flexShrink: 0 }} />
          <span>Evidence hashing and signing are implemented. External durable storage and ledger dispatch depend on the runtime configuration shown below.</span>
        </div>

        {/* Data Layer Row (Using Flexbox) */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', alignItems: 'stretch' }}>
          
          {/* Local Ledger */}
          <div 
            className="bg-panel border border-color rounded flex flex-col" 
            style={{ 
              flex: '1 1 300px', 
              padding: '1.5rem',
              background: 'linear-gradient(145deg, rgba(15,23,42,0.8) 0%, rgba(15,23,42,0.4) 100%)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
              position: 'relative',
              overflow: 'hidden',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'translateY(-4px)';
              e.currentTarget.style.boxShadow = '0 12px 30px rgba(56,189,248,0.5)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.2)';
            }}
          >
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: 'rgba(255,255,255,0.1)' }}></div>
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-color text-main">
              <Database size={18} />
              <span className="text-xs font-display uppercase tracking-widest">Evidence Vault</span>
            </div>
            <h3 className="text-main font-display mb-2 text-lg">Local Chain</h3>
            <div className="flex flex-col gap-3 text-sm font-body text-muted mt-2">
              <div className="flex items-start gap-2">
                <CheckCircle size={14} className="mt-1 text-ok opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.5' }}><strong>Signed package hash:</strong> SHA-256 over canonical event metadata and previous-hash linkage.</span>
              </div>
              <div className="bg-dark p-3 rounded border border-color text-xs">
                Durable object storage: {!storageReported ? 'RUNTIME STATUS UNAVAILABLE' : durableStorage ? 'CONFIGURED' : 'NOT CONFIGURED — local Render filesystem is ephemeral'}
              </div>
              <div className="flex items-start gap-2">
                <CheckCircle size={14} className="mt-1 text-ok opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.5' }}><strong>Evidence content hash:</strong> SHA-256 over stored encrypted evidence bytes when binary evidence is present.</span>
              </div>
              <div className="flex items-start gap-2">
                <CheckCircle size={14} className="mt-1 text-ok opacity-80" style={{ flexShrink: 0 }} />
                <span style={{ lineHeight: '1.5' }}>Ed25519 signatures and hash-chain linkage provide cryptographic tamper detection and evidence integrity verification.</span>
              </div>
            </div>
          </div>

          {/* Ledger */}
          <div
            className="border rounded flex flex-col"
            style={{ 
              flex: '1 1 300px', 
              padding: '1.5rem',
              background: 'linear-gradient(145deg, rgba(15,23,42,0.8) 0%, rgba(15,23,42,0.4) 100%)',
              borderColor: 'rgba(251,191,36,0.45)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
              position: 'relative',
              overflow: 'hidden',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'translateY(-4px)';
              e.currentTarget.style.boxShadow = '0 12px 30px rgba(251,191,36,0.22)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.2)';
            }}
          >
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: 'rgba(251,191,36,0.55)' }}></div>
            <div className="flex justify-between items-center gap-2 mb-4 pb-3 border-b border-color text-warning">
              <div className="flex items-center gap-2">
                <Link size={18} />
                <span className="text-xs font-display uppercase tracking-widest">Cryptographic Ledger</span>
              </div>
              <span className="text-warning rounded font-display tracking-widest border border-color" style={{ padding: '0.25rem 0.5rem', fontSize: '9px', background: 'rgba(251,191,36,0.08)' }}>
                {!blockchainReported ? 'STATUS UNAVAILABLE' : simulatedLedger ? 'MOCK MODE' : 'FABRIC MODE'}
              </span>
            </div>
            <h3 className="text-warning font-display mb-2 text-lg tracking-wide">{!blockchainReported ? 'Ledger Mode Unavailable' : simulatedLedger ? 'Simulated Blockchain Mode' : 'Permissioned Ledger'}</h3>
            <div className="flex flex-col gap-3 text-sm font-body text-muted mt-2">
              <span>{!blockchainReported ? 'Runtime mode not reported.' : simulatedLedger ? 'Fabric integration is inactive in the current deployment.' : 'Fabric integration is active in the current deployment.'}</span>
              <div className="bg-dark p-3 rounded border border-color text-xs text-muted" style={{ lineHeight: '1.5' }}>
                {!blockchainReported ? 'Production ledger status is unavailable.' : simulatedLedger ? 'MOCK / SIMULATED mode. No production blockchain confirmation is implied.' : 'Fabric mode reported by the backend runtime.'}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
