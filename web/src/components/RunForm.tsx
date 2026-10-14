import React, { useState } from 'react';
import { Play, Sparkles, Plus, Trash2, LayoutDashboard, FormInput, Grid, AlertCircle } from 'lucide-react';
import { InputRequest, TargetType } from '../types';

interface RunFormProps {
  onSubmit: (request: InputRequest) => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

export const RunForm: React.FC<RunFormProps> = ({ onSubmit, isLoading, error }) => {
  const [brief, setBrief] = useState(
    'A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.'
  );
  const [apiSpecUrl, setApiSpecUrl] = useState('https://demo-backend.example.com/openapi.json');
  const [target, setTarget] = useState<TargetType>('dashboard');
  const [styleHints, setStyleHints] = useState<string[]>(['minimal', 'data-dense']);
  const [newHint, setNewHint] = useState('');
  const [requiredFlows, setRequiredFlows] = useState<string[]>([
    'list tickets',
    'filter by priority',
    'open ticket detail',
    'send reply',
  ]);
  const [newFlow, setNewFlow] = useState('');
  const [maxIterations, setMaxIterations] = useState<number>(3);

  // Preset briefs
  const applyPreset = (presetName: string) => {
    if (presetName === 'support') {
      setBrief('A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.');
      setApiSpecUrl('https://demo-backend.example.com/openapi.json');
      setTarget('dashboard');
      setStyleHints(['minimal', 'data-dense']);
      setRequiredFlows(['list tickets', 'filter by priority', 'open ticket detail', 'send reply']);
      setMaxIterations(3);
    } else if (presetName === 'feedback') {
      setBrief('Customer feedback collector with rating stars, categorized issues, attachment upload, and instant confirmation.');
      setApiSpecUrl('https://demo-backend.example.com/openapi.json');
      setTarget('form_app');
      setStyleHints(['clean', 'high-contrast', 'accessible']);
      setRequiredFlows(['submit rating', 'select category', 'fill feedback', 'verify success']);
      setMaxIterations(3);
    } else if (presetName === 'analytics') {
      setBrief('DevOps metrics portal with CPU/Memory usage graphs, deployment log viewer, and incident rollback actions.');
      setApiSpecUrl('https://demo-backend.example.com/openapi.json');
      setTarget('mixed');
      setStyleHints(['dark', 'data-dense', 'monospace-logs']);
      setRequiredFlows(['view metrics charts', 'inspect active pods', 'trigger rollback']);
      setMaxIterations(4);
    }
  };

  const loadSampleInput = async () => {
    try {
      const res = await fetch('/api/sample-input');
      if (res.ok) {
        const data = await res.json();
        setBrief(data.brief || '');
        setApiSpecUrl(typeof data.api_spec_url === 'string' ? data.api_spec_url : JSON.stringify(data.api_spec_url));
        setTarget(data.target || 'dashboard');
        setStyleHints(data.style_hints || []);
        setRequiredFlows(data.required_flows || []);
        setMaxIterations(data.max_iterations || 3);
      }
    } catch {
      applyPreset('support');
    }
  };

  const handleAddHint = () => {
    if (newHint.trim() && !styleHints.includes(newHint.trim())) {
      setStyleHints([...styleHints, newHint.trim()]);
      setNewHint('');
    }
  };

  const handleRemoveHint = (hint: string) => {
    setStyleHints(styleHints.filter((h) => h !== hint));
  };

  const handleAddFlow = () => {
    if (newFlow.trim() && !requiredFlows.includes(newFlow.trim())) {
      setRequiredFlows([...requiredFlows, newFlow.trim()]);
      setNewFlow('');
    }
  };

  const handleRemoveFlow = (flow: string) => {
    setRequiredFlows(requiredFlows.filter((f) => f !== flow));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      brief,
      api_spec_url: apiSpecUrl,
      target,
      style_hints: styleHints,
      required_flows: requiredFlows,
      max_iterations: Number(maxIterations),
    });
  };

  return (
    <div className="glass-panel" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', marginBottom: 4 }}>Configure Run Request</h2>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            Define the product requirements and backend spec for the 6-agent team.
          </p>
        </div>

        {/* Quick Presets */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            onClick={loadSampleInput}
            className="btn-secondary"
            style={{ fontSize: '0.8rem', padding: '6px 12px' }}
          >
            <Sparkles size={14} color="#818cf8" />
            Load Sample
          </button>
          <button
            type="button"
            onClick={() => applyPreset('support')}
            className="btn-secondary"
            style={{ fontSize: '0.75rem', padding: '4px 8px' }}
          >
            Support
          </button>
          <button
            type="button"
            onClick={() => applyPreset('feedback')}
            className="btn-secondary"
            style={{ fontSize: '0.75rem', padding: '4px 8px' }}
          >
            Form App
          </button>
          <button
            type="button"
            onClick={() => applyPreset('analytics')}
            className="btn-secondary"
            style={{ fontSize: '0.75rem', padding: '4px 8px' }}
          >
            Analytics
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 8,
          padding: '12px 16px',
          color: '#fca5a5',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'flex-start',
          gap: 10,
          marginBottom: 20,
        }}>
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{error}</div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {/* Product Brief */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: 6, color: '#e2e8f0' }}>
            Product Brief <span style={{ color: '#ec4899' }}>*</span>
          </label>
          <textarea
            className="input-field"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            required
            rows={3}
            placeholder="Plain-language description of the product, users, and desired workflow..."
          />
        </div>

        {/* OpenAPI Spec URL */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: 6, color: '#e2e8f0' }}>
            OpenAPI 3.0 Spec URL or Inline JSON <span style={{ color: '#ec4899' }}>*</span>
          </label>
          <input
            type="text"
            className="input-field"
            value={apiSpecUrl}
            onChange={(e) => setApiSpecUrl(e.target.value)}
            required
            placeholder="https://your-backend.com/openapi.json or inline OpenAPI JSON"
          />
          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginTop: 4 }}>
            Tip: Use <code>https://demo-backend.example.com/openapi.json</code> to test with the mock ticket backend.
          </span>
        </div>

        {/* Interface Target (Dashboard, Form App, Mixed) */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: 8, color: '#e2e8f0' }}>
            Interface Target <span style={{ color: '#ec4899' }}>*</span>
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
            {[
              { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, desc: 'Data tables, charts & metrics' },
              { id: 'form_app', label: 'Form App', icon: FormInput, desc: 'Multi-step forms & inputs' },
              { id: 'mixed', label: 'Mixed', icon: Grid, desc: 'Composite workspace flows' },
            ].map((item) => {
              const Icon = item.icon;
              const isSelected = target === item.id;
              return (
                <div
                  key={item.id}
                  onClick={() => setTarget(item.id as TargetType)}
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.03)',
                    border: `1px solid ${isSelected ? '#6366f1' : 'var(--border-subtle)'}`,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <Icon size={16} color={isSelected ? '#818cf8' : 'var(--text-secondary)'} />
                    <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isSelected ? '#fff' : 'var(--text-secondary)' }}>
                      {item.label}
                    </span>
                  </div>
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{item.desc}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Required User Flows */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: 6, color: '#e2e8f0' }}>
            Required QA User Flows
          </label>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <input
              type="text"
              className="input-field"
              value={newFlow}
              onChange={(e) => setNewFlow(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddFlow(); } }}
              placeholder="e.g. filter tickets by priority..."
              style={{ fontSize: '0.82rem' }}
            />
            <button
              type="button"
              onClick={handleAddFlow}
              className="btn-secondary"
              style={{ padding: '0 12px' }}
            >
              <Plus size={15} />
            </button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {requiredFlows.map((flow) => (
              <span
                key={flow}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '4px 10px',
                  borderRadius: 6,
                  background: 'rgba(16, 185, 129, 0.1)',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                  color: '#34d399',
                  fontSize: '0.75rem',
                  fontWeight: 500,
                }}
              >
                {flow}
                <Trash2
                  size={12}
                  style={{ cursor: 'pointer', opacity: 0.7 }}
                  onClick={() => handleRemoveFlow(flow)}
                />
              </span>
            ))}
          </div>
        </div>

        {/* Style Hints & Iterations */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 24 }}>
          {/* Style Hints */}
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: 6, color: '#e2e8f0' }}>
              Style Hints
            </label>
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <input
                type="text"
                className="input-field"
                value={newHint}
                onChange={(e) => setNewHint(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddHint(); } }}
                placeholder="e.g. data-dense, dark..."
                style={{ fontSize: '0.82rem' }}
              />
              <button
                type="button"
                onClick={handleAddHint}
                className="btn-secondary"
                style={{ padding: '0 10px' }}
              >
                <Plus size={14} />
              </button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {styleHints.map((hint) => (
                <span
                  key={hint}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '3px 8px',
                    borderRadius: 4,
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border-subtle)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.72rem',
                  }}
                >
                  #{hint}
                  <span
                    style={{ cursor: 'pointer', opacity: 0.6 }}
                    onClick={() => handleRemoveHint(hint)}
                  >
                    ×
                  </span>
                </span>
              ))}
            </div>
          </div>

          {/* Max Iterations */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0' }}>
                Iteration Budget
              </label>
              <span style={{ fontSize: '0.8rem', color: '#818cf8', fontWeight: 700 }}>
                {maxIterations} cycles
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={6}
              value={maxIterations}
              onChange={(e) => setMaxIterations(Number(e.target.value))}
              style={{ width: '100%', accentColor: '#6366f1', cursor: 'pointer' }}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Hard limit on retry/fix loops before Planner escalates.
            </span>
          </div>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="btn-primary"
          style={{ width: '100%', padding: '14px', fontSize: '1rem' }}
        >
          {isLoading ? (
            <>
              <div style={{
                width: 18,
                height: 18,
                border: '2px solid rgba(255, 255, 255, 0.3)',
                borderTopColor: '#fff',
                borderRadius: '50%',
                animation: 'spin 0.8s linear infinite',
              }} />
              Starting 6-Agent System...
            </>
          ) : (
            <>
              <Play size={18} fill="#fff" />
              Launch FrontForge Run
            </>
          )}
        </button>
      </form>
    </div>
  );
};
