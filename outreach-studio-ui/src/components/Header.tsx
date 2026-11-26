import React from 'react';
import { Send, FileSpreadsheet, Calendar, MessageSquare, AlertOctagon, RefreshCw, Sparkles, CheckCircle2, FileText, BarChart3 } from 'lucide-react';

interface HeaderProps {
  activeTab: 'outreach' | 'excel' | 'schedules' | 'replies' | 'bounces';
  setActiveTab: (tab: 'outreach' | 'excel' | 'schedules' | 'replies' | 'bounces') => void;
  onSync: () => void;
  isSyncing: boolean;
}

export const Header: React.FC<HeaderProps> = ({ activeTab, setActiveTab, onSync, isSyncing }) => {
  return (
    <header className="sticky top-0 z-40 bg-slate-900/90 backdrop-blur-md border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Branding */}
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xl font-bold tracking-tight text-white">Outreach Studio</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                  Live Excel Connected
                </span>
              </div>
              <p className="text-xs text-slate-400">Adople AI Enterprise Conference Outreach Engine</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex space-x-1 bg-slate-800/80 p-1 rounded-xl border border-slate-700/60">
            <button
              onClick={() => setActiveTab('outreach')}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'outreach'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <Send className="w-4 h-4" />
              <span>Outreach Studio</span>
            </button>

            <button
              onClick={() => setActiveTab('excel')}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'excel'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <FileSpreadsheet className="w-4 h-4" />
              <span>Excel Explorer (13 Sheets)</span>
            </button>

            <button
              onClick={() => setActiveTab('schedules')}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'schedules'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Schedules</span>
            </button>

            <button
              onClick={() => setActiveTab('replies')}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'replies'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <MessageSquare className="w-4 h-4" />
              <span>Replies Monitor</span>
            </button>

            <button
              onClick={() => setActiveTab('bounces')}
              className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === 'bounces'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <AlertOctagon className="w-4 h-4" />
              <span>Bounce Capture</span>
            </button>
          </nav>

          {/* Action Links: PDF Report, Dashboard, and Sync */}
          <div className="flex items-center space-x-2">
            <a
              href="/api/reporting/download/latest?format=pdf"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 transition-all"
              title="Download Consolidated PDF Report"
            >
              <FileText className="w-3.5 h-3.5 text-rose-400" />
              <span>PDF Report</span>
            </a>

            <a
              href="/reports"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 transition-all"
              title="Open 24/7 Visual Reporting Hub"
            >
              <BarChart3 className="w-3.5 h-3.5 text-indigo-400" />
              <span>Reports Hub</span>
            </a>

            <button
              onClick={onSync}
              disabled={isSyncing}
              className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 hover:border-slate-600 transition-all disabled:opacity-50"
              title="Force sync Local Excel, PostgreSQL, and OneDrive SharePoint"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-emerald-400' : 'text-slate-400'}`} />
              <span>{isSyncing ? 'Syncing...' : 'Sync'}</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
