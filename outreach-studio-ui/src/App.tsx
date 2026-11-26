import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { OutreachStudio } from './components/OutreachStudio';
import { ExcelExplorer } from './components/ExcelExplorer';
import { ScheduledList } from './components/ScheduledList';
import { RepliesMonitor } from './components/RepliesMonitor';
import { BouncesMonitor } from './components/BouncesMonitor';
import { EmailModal } from './components/EmailModal';
import { ScheduleModal } from './components/ScheduleModal';
import { OverviewMetrics, SheetMetadata, Lead } from './types';
import { api } from './services/api';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'outreach' | 'excel' | 'schedules' | 'replies' | 'bounces'>('outreach');
  const [metrics, setMetrics] = useState<OverviewMetrics | null>(null);
  const [sheetCounts, setSheetCounts] = useState<Record<string, number>>({});
  const [sheets, setSheets] = useState<SheetMetadata[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loadingLeads, setLoadingLeads] = useState<boolean>(true);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);

  // Modals state
  const [composeLead, setComposeLead] = useState<Lead | null>(null);
  const [scheduleLeadsList, setScheduleLeadsList] = useState<Lead[]>([]);

  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    try {
      const [overviewData, sheetsData] = await Promise.all([
        api.getOverview(),
        api.getSheets()
      ]);
      setMetrics(overviewData.metrics);
      setSheetCounts(overviewData.sheet_counts);
      setSheets(sheetsData);
    } catch (err) {
      console.error('Error loading initial metadata:', err);
    }

    loadLeads();
  };

  const loadLeads = async () => {
    setLoadingLeads(true);
    try {
      const data = await api.getLeads('all', undefined, true);
      setLeads(data);
    } catch (err) {
      console.error('Error loading leads:', err);
    } finally {
      setLoadingLeads(false);
    }
  };

  const handleSyncExcel = async () => {
    setIsSyncing(true);
    try {
      await api.syncExcel();
      await loadInitialData();
      alert('Excel workbook & OneDrive SharePoint successfully re-synchronized!');
    } catch (err: any) {
      alert(`Sync note: ${err.message}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleSendDirectLead = async (lead: Lead) => {
    if (!confirm(`Dispatch live outreach email to ${lead.contact_name} (${lead.professional_email})?`)) {
      return;
    }
    try {
      await api.sendOutreach({
        email: lead.professional_email,
        category: lead.contact_type || 'Speaker',
        dry_run: false
      });
      alert(`Outreach successfully sent to ${lead.contact_name}!`);
      loadLeads();
      const overviewData = await api.getOverview();
      setMetrics(overviewData.metrics);
    } catch (err: any) {
      alert(`Dispatch error: ${err.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Global Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onSync={handleSyncExcel}
        isSyncing={isSyncing}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Real-time KPI Stats Banner */}
        <StatsCards metrics={metrics} sheetCounts={sheetCounts} />

        {/* Tab Views */}
        {activeTab === 'outreach' && (
          <OutreachStudio
            leads={leads}
            loading={loadingLeads}
            onComposeEmail={(lead) => setComposeLead(lead)}
            onScheduleLeads={(selected) => setScheduleLeadsList(selected)}
            onSendDirect={handleSendDirectLead}
            onRefresh={loadLeads}
          />
        )}

        {activeTab === 'excel' && (
          <ExcelExplorer sheets={sheets} />
        )}

        {activeTab === 'schedules' && (
          <ScheduledList />
        )}

        {activeTab === 'replies' && (
          <RepliesMonitor />
        )}

        {activeTab === 'bounces' && (
          <BouncesMonitor />
        )}
      </main>

      {/* Email Composer & LLM Personalizer Modal */}
      {composeLead && (
        <EmailModal
          lead={composeLead}
          onClose={() => setComposeLead(null)}
          onSuccess={() => {
            loadLeads();
            api.getOverview().then(d => setMetrics(d.metrics));
          }}
        />
      )}

      {/* Schedule Modal */}
      {scheduleLeadsList.length > 0 && (
        <ScheduleModal
          leads={scheduleLeadsList}
          onClose={() => setScheduleLeadsList([])}
          onSuccess={() => {
            loadLeads();
            setActiveTab('schedules');
          }}
        />
      )}

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/80 py-4 text-center text-xs text-slate-600">
        Outreach Studio • Adople AI Enterprise Automated Pipeline • Live Connected to usa_conferences_published.xlsx
      </footer>
    </div>
  );
};

export default App;
