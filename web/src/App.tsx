import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import { RunForm } from './components/RunForm';
import { AgentBlackboard } from './components/AgentBlackboard';
import { ActivityFeed } from './components/ActivityFeed';
import { QualityReportView } from './components/QualityReportView';
import { RunHistoryModal } from './components/RunHistoryModal';
import { InputRequest, RunRecord, TraceEntry } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'control' | 'feed' | 'report'>('control');
  const [currentRun, setCurrentRun] = useState<RunRecord | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [events, setEvents] = useState<TraceEntry[]>([]);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean>(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState<boolean>(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  // Check health and list existing runs on mount
  useEffect(() => {
    const checkBackend = async () => {
      try {
        const res = await fetch('/health');
        if (res.ok) {
          setBackendOnline(true);
        } else {
          setBackendOnline(false);
        }
      } catch {
        setBackendOnline(false);
      }
    };

    const fetchRuns = async () => {
      try {
        const res = await fetch('/runs');
        if (res.ok) {
          const data = await res.json();
          setRuns(data);
          // If no active run but runs exist, select the most recent one
          if (!currentRun && data.length > 0) {
            const latest = data[data.length - 1];
            setCurrentRun(latest);
            if (latest.report) {
              // already has report
            }
          }
        }
      } catch {
        // ignore
      }
    };

    checkBackend();
    fetchRuns();
    const interval = setInterval(checkBackend, 10000);
    return () => clearInterval(interval);
  }, []);

  // Connect to SSE stream whenever currentRun changes
  useEffect(() => {
    if (!currentRun) return;

    // Close any previous stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    // Connect to /runs/{id}/events
    const es = new EventSource(`/runs/${currentRun.run_id}/events`);
    eventSourceRef.current = es;

    es.addEventListener('trace', (e: MessageEvent) => {
      try {
        const entry: TraceEntry = JSON.parse(e.data);
        setEvents((prev) => {
          // Avoid duplicate entries
          if (prev.some((p) => p.seq === entry.seq)) return prev;
          return [...prev, entry];
        });

        // Set active agent
        if (entry.agent) {
          setActiveAgent(entry.agent);
        }
      } catch (err) {
        console.error('Failed to parse SSE trace event', err);
      }
    });

    es.addEventListener('end', (e: MessageEvent) => {
      try {
        const summary = JSON.parse(e.data);
        setCurrentRun((prev) => (prev ? { ...prev, ...summary } : summary));
        setActiveAgent(null);
        setIsLoading(false);
        // Refresh run details
        fetchRunDetails(currentRun.run_id);
      } catch (err) {
        console.error('Failed to parse SSE end event', err);
      } finally {
        es.close();
      }
    });

    es.onerror = () => {
      // Re-fetch run details in case it finished
      fetchRunDetails(currentRun.run_id);
    };

    return () => {
      es.close();
    };
  }, [currentRun?.run_id]);

  const fetchRunDetails = async (runId: string) => {
    try {
      const res = await fetch(`/runs/${runId}`);
      if (res.ok) {
        const data = await res.json();
        setCurrentRun(data);
        if (data.status !== 'running') {
          setIsLoading(false);
        }
      }
    } catch {
      // ignore
    }
  };

  const handleStartRun = async (request: InputRequest) => {
    setIsLoading(true);
    setError(null);
    setEvents([]);
    setActiveAgent('planner');

    try {
      const res = await fetch('/runs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errData.detail || `Request failed with status ${res.status}`);
      }

      const data = await res.json();
      const newRecord: RunRecord = {
        run_id: data.run_id,
        status: 'running',
        created_at: data.created_at || new Date().toISOString(),
      };
      setCurrentRun(newRecord);
      setRuns((prev) => [newRecord, ...prev]);
      setActiveTab('feed');
    } catch (err: any) {
      setError(err.message || 'Failed to start run');
      setIsLoading(false);
      setActiveAgent(null);
    }
  };

  const handleSelectRun = async (runId: string) => {
    setIsLoading(false);
    setError(null);
    setEvents([]);
    await fetchRunDetails(runId);
    setActiveTab('report');
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header
        currentRun={currentRun}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onOpenHistory={() => setIsHistoryOpen(true)}
        backendOnline={backendOnline}
      />

      <main style={{ maxWidth: 1400, margin: '0 auto', width: '100%', padding: '24px 20px', flex: 1 }}>
        {/* Top Blackboard is visible on all views for live agent awareness */}
        <div style={{ marginBottom: 24 }}>
          <AgentBlackboard
            activeAgent={activeAgent}
            recentEvents={events}
            runStatus={currentRun?.status || 'idle'}
          />
        </div>

        {/* Tab Content */}
        {activeTab === 'control' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: 24 }}>
            <RunForm
              onSubmit={handleStartRun}
              isLoading={isLoading}
              error={error}
            />
            <ActivityFeed
              events={events}
              isLoading={isLoading}
              runId={currentRun?.run_id || null}
            />
          </div>
        )}

        {activeTab === 'feed' && (
          <div style={{ maxWidth: 900, margin: '0 auto' }}>
            <ActivityFeed
              events={events}
              isLoading={isLoading}
              runId={currentRun?.run_id || null}
            />
          </div>
        )}

        {activeTab === 'report' && (
          <QualityReportView currentRun={currentRun} />
        )}
      </main>

      <footer style={{
        borderTop: '1px solid var(--border-subtle)',
        padding: '16px 24px',
        textAlign: 'center',
        fontSize: '0.75rem',
        color: 'var(--text-muted)',
      }}>
        FrontForge Multi-Agent System (LangGraph, Python, FastAPI, React) • Verified via 5 Quality Gates & Proof-of-Work
      </footer>

      <RunHistoryModal
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        runs={runs}
        onSelectRun={handleSelectRun}
        currentRunId={currentRun?.run_id || null}
      />
    </div>
  );
};
export default App;
