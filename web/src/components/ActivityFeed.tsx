import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Shield, Route, AlertCircle, FileText, ChevronDown, ChevronRight, Check } from 'lucide-react';
import { TraceEntry } from '../types';

interface ActivityFeedProps {
  events: TraceEntry[];
  isLoading: boolean;
  runId: string | null;
}

export const ActivityFeed: React.FC<ActivityFeedProps> = ({ events, isLoading, runId }) => {
  const [filter, setFilter] = useState<'all' | 'proof' | 'routing' | 'error' | 'message'>('all');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [expandedSeqs, setExpandedSeqs] = useState<Record<number, boolean>>({});
  const feedEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) {
      feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, autoScroll]);

  const toggleExpand = (seq: number) => {
    setExpandedSeqs((prev) => ({ ...prev, [seq]: !prev[seq] }));
  };

  const filteredEvents = events.filter((e) => {
    if (filter === 'all') return true;
    if (filter === 'proof') return e.event_type === 'proof' || Boolean(e.payload?.claim);
    if (filter === 'routing') return e.event_type === 'routing' || Boolean(e.payload?.decision);
    if (filter === 'error') return e.event_type === 'error' || Boolean(e.payload?.error);
    if (filter === 'message') return e.event_type === 'message';
    return true;
  });

  const getAgentBadgeClass = (agent: string) => {
    switch (agent.toLowerCase()) {
      case 'planner': return 'badge-planner';
      case 'designer': return 'badge-designer';
      case 'engineer': return 'badge-engineer';
      case 'integration': return 'badge-integration';
      case 'qa': return 'badge-qa';
      case 'critic': return 'badge-critic';
      default: return 'badge-planner';
    }
  };

  return (
    <div className="glass-panel" style={{ padding: 20 }}>
      {/* Feed Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 12,
        marginBottom: 16,
        paddingBottom: 14,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: 'rgba(99, 102, 241, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Terminal size={18} color="#818cf8" />
          </div>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>
              Live Trace & Verification Feed
            </h3>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Append-only event stream (SSE) directly from <code>trace.jsonl</code>
              {runId && <span style={{ color: '#818cf8', marginLeft: 6 }}>• Run: {runId}</span>}
            </p>
          </div>
        </div>

        {/* Filter Pills & Auto-scroll */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div style={{
            display: 'flex',
            background: 'rgba(0, 0, 0, 0.3)',
            borderRadius: 6,
            padding: 2,
            border: '1px solid var(--border-subtle)',
          }}>
            {(['all', 'routing', 'proof', 'message', 'error'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  background: filter === f ? 'rgba(99, 102, 241, 0.3)' : 'transparent',
                  color: filter === f ? '#fff' : 'var(--text-muted)',
                  border: 'none',
                  padding: '4px 10px',
                  borderRadius: 4,
                  fontSize: '0.72rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  textTransform: 'capitalize',
                }}
              >
                {f}
              </button>
            ))}
          </div>

          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: '0.75rem',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              style={{ accentColor: '#6366f1' }}
            />
            Auto-scroll
          </label>
        </div>
      </div>

      {/* Events List */}
      <div style={{
        maxHeight: 520,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        paddingRight: 4,
      }}>
        {filteredEvents.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '40px 20px',
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
          }}>
            {isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 24,
                  height: 24,
                  border: '2px solid rgba(99, 102, 241, 0.3)',
                  borderTopColor: '#6366f1',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                }} />
                Listening for agent trace stream...
              </div>
            ) : (
              'No events recorded yet. Start a run from the Control Deck.'
            )}
          </div>
        ) : (
          filteredEvents.map((event) => {
            const isProof = event.event_type === 'proof' || Boolean(event.payload?.claim);
            const isRouting = event.event_type === 'routing' || Boolean(event.payload?.decision);
            const isError = event.event_type === 'error' || Boolean(event.payload?.error);
            const isExpanded = expandedSeqs[event.seq] || false;

            return (
              <div
                key={`${event.run_id}-${event.seq}`}
                style={{
                  background: isProof
                    ? 'rgba(16, 185, 129, 0.04)'
                    : isRouting
                    ? 'rgba(139, 92, 246, 0.04)'
                    : isError
                    ? 'rgba(239, 68, 68, 0.08)'
                    : 'rgba(255, 255, 255, 0.02)',
                  border: `1px solid ${
                    isProof
                      ? 'rgba(16, 185, 129, 0.2)'
                      : isRouting
                      ? 'rgba(139, 92, 246, 0.2)'
                      : isError
                      ? 'rgba(239, 68, 68, 0.3)'
                      : 'var(--border-subtle)'
                  }`,
                  borderRadius: 8,
                  padding: '10px 14px',
                  fontSize: '0.82rem',
                }}
              >
                {/* Event Header */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 6,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className={`badge ${getAgentBadgeClass(event.agent)}`}>
                      {event.agent}
                    </span>

                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      fontSize: '0.7rem',
                      fontWeight: 600,
                      color: isProof ? '#34d399' : isRouting ? '#a78bfa' : isError ? '#f87171' : 'var(--text-muted)',
                    }}>
                      {isProof && <Shield size={12} />}
                      {isRouting && <Route size={12} />}
                      {isError && <AlertCircle size={12} />}
                      {event.event_type.toUpperCase()}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    <span>#{event.seq}</span>
                    <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>

                {/* Event Summary */}
                <div style={{ color: '#e2e8f0', marginBottom: 4 }}>
                  {event.payload?.claim && (
                    <div style={{ fontWeight: 600, color: '#34d399', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Check size={14} />
                      Claim: {event.payload.claim}
                    </div>
                  )}

                  {event.payload?.decision && (
                    <div style={{ fontWeight: 600, color: '#c4b5fd' }}>
                      Routing Decision: Next Agent → <span style={{ textDecoration: 'underline' }}>{event.payload.decision}</span>
                      {event.payload?.reason && (
                        <div style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 400, marginTop: 2 }}>
                          Reason: {event.payload.reason}
                        </div>
                      )}
                    </div>
                  )}

                  {event.payload?.message && (
                    <div>{event.payload.message}</div>
                  )}

                  {event.payload?.reasoning && !event.payload?.decision && (
                    <div style={{ fontSize: '0.78rem', color: '#cbd5e1' }}>
                      Reasoning: {event.payload.reasoning}
                    </div>
                  )}
                </div>

                {/* Evidence or Payload Inspector */}
                {(event.payload?.evidence || Object.keys(event.payload).length > 2) && (
                  <div>
                    <button
                      type="button"
                      onClick={() => toggleExpand(event.seq)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#818cf8',
                        fontSize: '0.72rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: 0,
                        marginTop: 4,
                      }}
                    >
                      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {isExpanded ? 'Hide Evidence & Payload' : 'View Proof Evidence & JSON'}
                    </button>

                    {isExpanded && (
                      <div style={{
                        marginTop: 8,
                        background: 'rgba(0, 0, 0, 0.4)',
                        padding: 8,
                        borderRadius: 6,
                        border: '1px solid rgba(255, 255, 255, 0.05)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.72rem',
                        maxHeight: 180,
                        overflowY: 'auto',
                      }}>
                        {event.payload?.evidence && (
                          <div style={{ marginBottom: 6 }}>
                            <strong style={{ color: '#34d399' }}>Evidence Items:</strong>
                            <ul style={{ paddingLeft: 16, marginTop: 2 }}>
                              {event.payload.evidence.map((ev: any, idx: number) => (
                                <li key={idx} style={{ color: '#94a3b8' }}>
                                  [{ev.type}] <span style={{ color: '#f1f5f9' }}>{ev.ref}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <pre style={{ whiteSpace: 'pre-wrap', color: '#cbd5e1' }}>
                          {JSON.stringify(event.payload, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={feedEndRef} />
      </div>
    </div>
  );
};
