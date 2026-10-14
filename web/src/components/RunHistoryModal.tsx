import React from 'react';
import { X, Clock, ExternalLink, ChevronRight, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { RunRecord } from '../types';

interface RunHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  runs: RunRecord[];
  onSelectRun: (runId: string) => void;
  currentRunId: string | null;
}

export const RunHistoryModal: React.FC<RunHistoryModalProps> = ({
  isOpen,
  onClose,
  runs,
  onSelectRun,
  currentRunId,
}) => {
  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.7)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 50,
      padding: 20,
    }}>
      <div className="glass-panel" style={{
        maxWidth: 600,
        width: '100%',
        maxHeight: '80vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Run History</h3>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Inspect trace events and quality reports from previous runs.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: 4,
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Runs List */}
        <div style={{
          padding: '16px 20px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}>
          {runs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No runs recorded yet. Start a run from the Control Deck.
            </div>
          ) : (
            runs.map((r) => {
              const isSelected = r.run_id === currentRunId;
              const isAccepted = r.status === 'accepted';
              const isPartial = r.status === 'partial';

              return (
                <div
                  key={r.run_id}
                  onClick={() => {
                    onSelectRun(r.run_id);
                    onClose();
                  }}
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                    border: `1px solid ${isSelected ? '#6366f1' : 'var(--border-subtle)'}`,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div>
                      {isAccepted && <CheckCircle2 size={18} color="#34d399" />}
                      {isPartial && <AlertTriangle size={18} color="#fbbf24" />}
                      {!isAccepted && !isPartial && r.status === 'running' && (
                        <div style={{
                          width: 14,
                          height: 14,
                          borderRadius: '50%',
                          border: '2px solid rgba(99, 102, 241, 0.3)',
                          borderTopColor: '#6366f1',
                          animation: 'spin 1s linear infinite',
                        }} />
                      )}
                      {!isAccepted && !isPartial && r.status !== 'running' && (
                        <XCircle size={18} color="#f87171" />
                      )}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '0.85rem', color: '#f1f5f9' }}>
                        {r.run_id}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Clock size={11} />
                        {new Date(r.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: isAccepted ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                      color: isAccepted ? '#34d399' : '#fbbf24',
                      textTransform: 'uppercase',
                    }}>
                      {r.status}
                    </span>
                    <ChevronRight size={16} color="var(--text-muted)" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
