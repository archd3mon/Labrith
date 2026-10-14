import React, { useState } from 'react';
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  ExternalLink,
  Download,
  Code,
  Gauge,
  CheckCircle2,
  Accessibility,
  Network,
  Cpu,
} from 'lucide-react';
import { QualityReport, RunRecord } from '../types';

interface QualityReportViewProps {
  currentRun: RunRecord | null;
}

export const QualityReportView: React.FC<QualityReportViewProps> = ({ currentRun }) => {
  const [showRawJson, setShowRawJson] = useState<boolean>(false);
  const report: QualityReport | undefined = currentRun?.report || undefined;

  if (!currentRun || (!report && currentRun.status === 'running')) {
    return (
      <div className="glass-panel" style={{ padding: 40, textAlign: 'center' }}>
        <div style={{
          width: 48,
          height: 48,
          borderRadius: '50%',
          border: '3px solid rgba(99, 102, 241, 0.2)',
          borderTopColor: '#6366f1',
          animation: 'spin 1s linear infinite',
          margin: '0 auto 16px',
        }} />
        <h3 style={{ fontSize: '1.1rem', marginBottom: 6 }}>Run in Progress...</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: 500, margin: '0 auto' }}>
          FrontForge agents are collaborating. The 5 verification gates and final quality report will render here upon completion.
        </p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="glass-panel" style={{ padding: 40, textAlign: 'center' }}>
        <AlertTriangle size={40} color="#f59e0b" style={{ margin: '0 auto 16px' }} />
        <h3 style={{ fontSize: '1.1rem', marginBottom: 6 }}>No Report Available Yet</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Launch a run from the Control Deck to generate a verified quality report.
        </p>
      </div>
    );
  }

  const isAccepted = report.status === 'accepted';
  const isPartial = report.status === 'partial';

  const downloadReportJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `quality_report_${report.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Status Hero Banner */}
      <div
        className="glass-panel"
        style={{
          padding: 24,
          background: isAccepted
            ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(18, 24, 38, 0.8) 100%)'
            : isPartial
            ? 'linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(18, 24, 38, 0.8) 100%)'
            : 'linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(18, 24, 38, 0.8) 100%)',
          border: `1px solid ${
            isAccepted ? 'rgba(16, 185, 129, 0.4)' : isPartial ? 'rgba(245, 158, 11, 0.4)' : 'rgba(239, 68, 68, 0.4)'
          }`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{
              width: 52,
              height: 52,
              borderRadius: 12,
              background: isAccepted ? 'rgba(16, 185, 129, 0.2)' : isPartial ? 'rgba(245, 158, 11, 0.2)' : 'rgba(239, 68, 68, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              {isAccepted && <CheckCircle size={28} color="#34d399" />}
              {isPartial && <AlertTriangle size={28} color="#fbbf24" />}
              {!isAccepted && !isPartial && <XCircle size={28} color="#f87171" />}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h2 style={{ fontSize: '1.4rem' }}>
                  {isAccepted ? 'Build Accepted' : isPartial ? 'Partial Delivery' : 'Run Failed'}
                </h2>
                <span style={{
                  padding: '3px 8px',
                  borderRadius: 6,
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  background: isAccepted ? 'rgba(16, 185, 129, 0.25)' : 'rgba(245, 158, 11, 0.25)',
                  color: isAccepted ? '#34d399' : '#fbbf24',
                }}>
                  RUN ID: {report.run_id}
                </span>
              </div>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: 4 }}>
                {isAccepted
                  ? 'All 5 verification gates passed with concrete proof of work.'
                  : isPartial
                  ? 'Run completed within iteration budget; some items remain unresolved and documented.'
                  : 'Run terminated due to errors.'}
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {report.preview_url && (
              <a
                href={report.preview_url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary"
                style={{ textDecoration: 'none' }}
              >
                <ExternalLink size={16} />
                Open Live Preview
              </a>
            )}
            <button onClick={downloadReportJson} className="btn-secondary">
              <Download size={15} />
              Export JSON
            </button>
            <button onClick={() => setShowRawJson(!showRawJson)} className="btn-secondary">
              <Code size={15} />
              {showRawJson ? 'Hide Raw' : 'View Raw'}
            </button>
          </div>
        </div>
      </div>

      {/* The 5 Verification Gates */}
      <div>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 12 }}>
          Verification Gates Audit (Design Doc §6)
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14 }}>
          {/* 1. Build Gate */}
          <div className="glass-panel" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Cpu size={18} color="#0ea5e9" />
                <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>1. Build Gate</span>
              </div>
              <span style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                color: report.gates.build?.passed ? '#34d399' : '#f87171',
              }}>
                {report.gates.build?.passed ? 'PASSED' : 'FAILED'}
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 8 }}>
              React + TypeScript compilation & Vite bundle build.
            </p>
            {report.gates.build?.evidence && (
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', background: 'rgba(0,0,0,0.3)', padding: 6, borderRadius: 4 }}>
                Log: <code>{report.gates.build.evidence}</code>
              </div>
            )}
          </div>

          {/* 2. Tests Gate */}
          <div className="glass-panel" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <CheckCircle2 size={18} color="#10b981" />
                <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>2. Test Gate</span>
              </div>
              <span style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                color: report.gates.tests?.passed ? '#34d399' : '#f87171',
              }}>
                {report.gates.tests?.passed ? 'PASSED' : 'FAILED'}
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 8 }}>
              Playwright headless browser flows & user journey verification.
            </p>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e2e8f0' }}>
              Flows: {report.gates.tests?.flows_passed ?? 0} / {report.gates.tests?.flows_total ?? 0} Passing
            </div>
          </div>

          {/* 3. Accessibility Gate */}
          <div className="glass-panel" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Accessibility size={18} color="#ec4899" />
                <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>3. Accessibility Gate</span>
              </div>
              <span style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                color: report.gates.accessibility?.passed ? '#34d399' : '#f87171',
              }}>
                {report.gates.accessibility?.passed ? 'PASSED' : 'FAILED'}
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 8 }}>
              axe-core automated WCAG 2.1 AA audit.
            </p>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e2e8f0' }}>
              Violations: {report.gates.accessibility?.critical ?? 0} critical, {report.gates.accessibility?.serious ?? 0} serious
            </div>
          </div>

          {/* 4. Quality Gate */}
          <div className="glass-panel" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Gauge size={18} color="#8b5cf6" />
                <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>4. Quality Gate</span>
              </div>
              <span style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                color: '#818cf8',
              }}>
                AUDITED
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 8 }}>
              Lighthouse synthetic performance and UX scores.
            </p>
            <div style={{ display: 'flex', gap: 12, fontSize: '0.82rem', fontWeight: 600 }}>
              <div>A11y: <span style={{ color: '#34d399' }}>{report.gates.quality?.lighthouse_accessibility ?? 'N/A'}%</span></div>
              <div>Perf: <span style={{ color: '#38bdf8' }}>{report.gates.quality?.lighthouse_performance ?? 'N/A'}%</span></div>
            </div>
          </div>

          {/* 5. Integration Gate */}
          <div className="glass-panel" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Network size={18} color="#f59e0b" />
                <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>5. Integration Gate</span>
              </div>
              <span style={{
                fontSize: '0.72rem',
                fontWeight: 700,
                color: report.gates.integration?.passed ? '#34d399' : '#fbbf24',
              }}>
                {report.gates.integration?.passed ? 'PASSED' : 'PARTIAL'}
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 8 }}>
              API client matches OpenAPI spec contract.
            </p>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e2e8f0' }}>
              Documented mismatches: {report.gates.integration?.documented_mismatches ?? 0}
            </div>
          </div>
        </div>
      </div>

      {/* Iterations Breakdown & Revisions */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        {/* Iterations */}
        <div className="glass-panel" style={{ padding: 20 }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: 12 }}>
            Iteration Breakdown (Total: {report.iterations?.total ?? 0})
          </h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(report.iterations?.by_agent || {}).map(([agent, count]) => (
              <div
                key={agent}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 10px',
                  borderRadius: 6,
                  background: 'rgba(255, 255, 255, 0.02)',
                  fontSize: '0.82rem',
                }}
              >
                <span style={{ textTransform: 'capitalize', fontWeight: 600 }}>{agent}</span>
                <span style={{ color: '#818cf8', fontWeight: 700 }}>{count} cycles</span>
              </div>
            ))}
          </div>
        </div>

        {/* Revisions & Conflicts */}
        <div className="glass-panel" style={{ padding: 20 }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: 12 }}>
            Agent Revisions & Adaptations
          </h4>
          {report.revisions && report.revisions.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {report.revisions.map((rev, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '8px 12px',
                    borderRadius: 6,
                    background: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.8rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: '#f1f5f9', marginBottom: 2 }}>
                    <span style={{ textTransform: 'capitalize' }}>{rev.by}</span> → <span style={{ textTransform: 'capitalize' }}>{rev.to}</span>
                    <span style={{
                      fontSize: '0.65rem',
                      padding: '1px 5px',
                      borderRadius: 4,
                      background: rev.resolved ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                      color: rev.resolved ? '#34d399' : '#fbbf24',
                      marginLeft: 'auto',
                    }}>
                      {rev.resolved ? 'RESOLVED' : 'OPEN'}
                    </span>
                  </div>
                  <div style={{ color: 'var(--text-muted)' }}>{rev.reason}</div>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              No cross-agent revisions were required during this run.
            </p>
          )}
        </div>
      </div>

      {/* Unresolved items (if any) */}
      {report.unresolved && report.unresolved.length > 0 && (
        <div className="glass-panel" style={{ padding: 20, border: '1px solid rgba(245, 158, 11, 0.3)' }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#fbbf24', marginBottom: 10 }}>
            Unresolved Items (Escalated by Planner)
          </h4>
          <ul style={{ paddingLeft: 18, fontSize: '0.82rem', color: '#cbd5e1' }}>
            {report.unresolved.map((item, idx) => (
              <li key={idx} style={{ marginBottom: 6 }}>
                <strong>{item.issue}</strong> — Evidence: <code>{item.evidence}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Raw JSON Drawer */}
      {showRawJson && (
        <div className="glass-panel" style={{ padding: 20, fontFamily: 'var(--font-mono)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>quality_report.json</span>
            <button onClick={() => setShowRawJson(false)} className="btn-secondary" style={{ fontSize: '0.75rem' }}>
              Close
            </button>
          </div>
          <pre style={{
            background: 'rgba(0,0,0,0.5)',
            padding: 14,
            borderRadius: 8,
            overflowX: 'auto',
            fontSize: '0.75rem',
            color: '#a5b4fc',
          }}>
            {JSON.stringify(report, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
