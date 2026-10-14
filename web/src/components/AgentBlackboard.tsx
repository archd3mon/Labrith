import React from 'react';
import { Compass, Palette, Code2, Network, CheckCircle2, AlertOctagon, ArrowRight } from 'lucide-react';
import { TraceEntry } from '../types';

interface AgentBlackboardProps {
  activeAgent: string | null;
  recentEvents: TraceEntry[];
  runStatus: string;
}

export const AgentBlackboard: React.FC<AgentBlackboardProps> = ({
  activeAgent,
  recentEvents,
  runStatus,
}) => {
  // Find the latest proof or action for each agent
  const agentInfo = [
    {
      id: 'planner',
      name: 'Planner (Supervisor)',
      role: 'Routes tasks, orchestrates loops & replans',
      icon: Compass,
      color: '#8b5cf6',
      badgeClass: 'badge-planner',
    },
    {
      id: 'designer',
      name: 'Design Architect',
      role: 'Design tokens, layout & typography',
      icon: Palette,
      color: '#ec4899',
      badgeClass: 'badge-designer',
    },
    {
      id: 'engineer',
      name: 'Component Engineer',
      role: 'React + TS + Tailwind code & build tests',
      icon: Code2,
      color: '#0ea5e9',
      badgeClass: 'badge-engineer',
    },
    {
      id: 'integration',
      name: 'Integration Agent',
      role: 'API client, types & mismatch reports',
      icon: Network,
      color: '#f59e0b',
      badgeClass: 'badge-integration',
    },
    {
      id: 'qa',
      name: 'QA Agent',
      role: 'Playwright browser tests & console audits',
      icon: CheckCircle2,
      color: '#10b981',
      badgeClass: 'badge-qa',
    },
    {
      id: 'critic',
      name: 'Design & A11y Critic',
      role: 'WCAG AA, axe-core & Lighthouse gates',
      icon: AlertOctagon,
      color: '#ef4444',
      badgeClass: 'badge-critic',
    },
  ];

  const getAgentLatestClaim = (agentId: string) => {
    const proofs = recentEvents.filter(
      (e) => e.agent === agentId && (e.event_type === 'proof' || e.payload?.claim)
    );
    if (proofs.length > 0) {
      const latest = proofs[proofs.length - 1];
      return latest.payload?.claim || latest.payload?.reasoning || 'Proof of work submitted';
    }
    const msgs = recentEvents.filter((e) => e.agent === agentId);
    if (msgs.length > 0) {
      const latest = msgs[msgs.length - 1];
      return latest.payload?.message || latest.payload?.decision || `Event: ${latest.event_type}`;
    }
    return 'Waiting for routing...';
  };

  return (
    <div className="glass-panel" style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>
            Active Blackboard & Agent State
          </h3>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            Supervisor pattern over shared blackboard — workers post proofs; Planner routes.
          </p>
        </div>
        <div style={{
          fontSize: '0.75rem',
          fontWeight: 600,
          color: runStatus === 'running' ? '#818cf8' : 'var(--text-muted)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}>
          {runStatus === 'running' && (
            <span style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: '#6366f1',
              boxShadow: '0 0 10px #6366f1',
            }} />
          )}
          Status: {runStatus.toUpperCase()}
        </div>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
        gap: 12,
      }}>
        {agentInfo.map((agent) => {
          const Icon = agent.icon;
          const isActive = activeAgent === agent.id;
          const latestClaim = getAgentLatestClaim(agent.id);
          const hasParticipated = recentEvents.some((e) => e.agent === agent.id);

          return (
            <div
              key={agent.id}
              style={{
                background: isActive
                  ? 'rgba(99, 102, 241, 0.16)'
                  : hasParticipated
                  ? 'rgba(255, 255, 255, 0.04)'
                  : 'rgba(255, 255, 255, 0.015)',
                border: `1px solid ${isActive ? agent.color : hasParticipated ? 'rgba(255, 255, 255, 0.1)' : 'var(--border-subtle)'}`,
                borderRadius: 10,
                padding: '12px 14px',
                position: 'relative',
                overflow: 'hidden',
                transition: 'all 0.2s ease',
                boxShadow: isActive ? `0 0 16px ${agent.color}33` : 'none',
              }}
            >
              {isActive && (
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  height: 3,
                  background: agent.color,
                  boxShadow: `0 0 8px ${agent.color}`,
                }} />
              )}

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    background: `${agent.color}22`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    <Icon size={16} color={agent.color} />
                  </div>
                  <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#f1f5f9' }}>
                    {agent.name.split(' ')[0]}
                  </span>
                </div>

                {isActive ? (
                  <span style={{
                    fontSize: '0.65rem',
                    fontWeight: 700,
                    color: agent.color,
                    background: `${agent.color}15`,
                    padding: '2px 6px',
                    borderRadius: 4,
                    border: `1px solid ${agent.color}40`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                  }}>
                    <span style={{
                      width: 5,
                      height: 5,
                      borderRadius: '50%',
                      background: agent.color,
                      display: 'inline-block',
                      animation: 'pulse-subtle 1.2s infinite',
                    }} />
                    ACTIVE
                  </span>
                ) : hasParticipated ? (
                  <span style={{
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    color: '#94a3b8',
                  }}>
                    POSTED
                  </span>
                ) : (
                  <span style={{
                    fontSize: '0.65rem',
                    color: '#64748b',
                  }}>
                    IDLE
                  </span>
                )}
              </div>

              <p style={{
                fontSize: '0.72rem',
                color: 'var(--text-muted)',
                marginBottom: 8,
                lineHeight: 1.3,
              }}>
                {agent.role}
              </p>

              {/* Latest Claim / Proof of Work snippet */}
              <div style={{
                background: 'rgba(0, 0, 0, 0.3)',
                padding: '6px 8px',
                borderRadius: 6,
                border: '1px solid rgba(255, 255, 255, 0.04)',
                fontSize: '0.7rem',
                color: hasParticipated ? '#cbd5e1' : '#64748b',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {latestClaim}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
