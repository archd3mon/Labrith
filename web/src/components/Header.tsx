import React from 'react';
import { Layers, Activity, History, ShieldCheck, Terminal } from 'lucide-react';
import { RunRecord } from '../types';

interface HeaderProps {
  currentRun: RunRecord | null;
  activeTab: 'control' | 'feed' | 'report';
  setActiveTab: (tab: 'control' | 'feed' | 'report') => void;
  onOpenHistory: () => void;
  backendOnline: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  currentRun,
  activeTab,
  setActiveTab,
  onOpenHistory,
  backendOnline,
}) => {
  return (
    <header style={{
      borderBottom: '1px solid var(--border-subtle)',
      background: 'rgba(7, 9, 14, 0.85)',
      backdropFilter: 'blur(16px)',
      position: 'sticky',
      top: 0,
      zIndex: 40,
      padding: '12px 24px',
    }}>
      <div style={{
        maxWidth: 1400,
        margin: '0 auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 16,
      }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)',
          }}>
            <Layers size={22} color="#fff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h1 style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.02em' }}>
                FrontForge
              </h1>
              <span style={{
                background: 'rgba(99, 102, 241, 0.15)',
                color: '#818cf8',
                border: '1px solid rgba(99, 102, 241, 0.3)',
                fontSize: '0.65rem',
                fontWeight: 700,
                padding: '2px 6px',
                borderRadius: 4,
                letterSpacing: '0.05em',
              }}>
                MULTI-AGENT v1.0
              </span>
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Cooperative 6-Agent Frontend Engineering Studio (LangGraph)
            </p>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(255, 255, 255, 0.04)',
          borderRadius: 8,
          padding: 4,
          border: '1px solid var(--border-subtle)',
          gap: 4,
        }}>
          <button
            onClick={() => setActiveTab('control')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: '0.82rem',
              fontWeight: 600,
              background: activeTab === 'control' ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
              color: activeTab === 'control' ? '#a5b4fc' : 'var(--text-secondary)',
              border: activeTab === 'control' ? '1px solid rgba(99, 102, 241, 0.4)' : '1px solid transparent',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Terminal size={15} />
            Control Deck
          </button>
          <button
            onClick={() => setActiveTab('feed')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: '0.82rem',
              fontWeight: 600,
              background: activeTab === 'feed' ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
              color: activeTab === 'feed' ? '#a5b4fc' : 'var(--text-secondary)',
              border: activeTab === 'feed' ? '1px solid rgba(99, 102, 241, 0.4)' : '1px solid transparent',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Activity size={15} />
            Live Trace {currentRun?.status === 'running' && (
              <span style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: '#10b981',
                boxShadow: '0 0 8px #10b981',
                display: 'inline-block',
              }} />
            )}
          </button>
          <button
            onClick={() => setActiveTab('report')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              borderRadius: 6,
              fontSize: '0.82rem',
              fontWeight: 600,
              background: activeTab === 'report' ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
              color: activeTab === 'report' ? '#a5b4fc' : 'var(--text-secondary)',
              border: activeTab === 'report' ? '1px solid rgba(99, 102, 241, 0.4)' : '1px solid transparent',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <ShieldCheck size={15} />
            Quality Report & Preview
          </button>
        </div>

        {/* Status & Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Backend Online Indicator */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: '0.75rem',
            color: backendOnline ? '#34d399' : '#f87171',
            background: backendOnline ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            padding: '4px 10px',
            borderRadius: 9999,
            border: `1px solid ${backendOnline ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`,
          }}>
            <span style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: backendOnline ? '#10b981' : '#ef4444',
            }} />
            {backendOnline ? 'FastAPI Online' : 'API Connecting...'}
          </div>

          {/* History Button */}
          <button
            onClick={onOpenHistory}
            className="btn-secondary"
            title="View Past Runs"
          >
            <History size={15} />
            Runs
          </button>
        </div>
      </div>
    </header>
  );
};
