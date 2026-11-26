import React, { useState } from 'react';
import { Lead } from '../types';
import { Search, Send, Calendar, Mail, CheckSquare, Square, Sparkles, ExternalLink, ShieldCheck, Clock, CheckCircle2 } from 'lucide-react';

interface OutreachStudioProps {
  leads: Lead[];
  loading: boolean;
  onComposeEmail: (lead: Lead) => void;
  onScheduleLeads: (leads: Lead[]) => void;
  onSendDirect: (lead: Lead) => void;
  onRefresh: () => void;
}

export const OutreachStudio: React.FC<OutreachStudioProps> = ({
  leads,
  loading,
  onComposeEmail,
  onScheduleLeads,
  onSendDirect,
  onRefresh
}) => {
  const [filterType, setFilterType] = useState<'all' | 'qualified' | 'non-qualified'>('qualified');
  const [search, setSearch] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Filter leads
  const filteredLeads = leads.filter(lead => {
    if (filterType === 'qualified' && !lead.is_qualified) return false;
    if (filterType === 'non-qualified' && lead.is_qualified) return false;
    if (statusFilter !== 'all' && lead.outreach_status.toLowerCase() !== statusFilter.toLowerCase()) return false;
    if (search.trim()) {
      const term = search.toLowerCase();
      const haystack = `${lead.contact_name} ${lead.company_name} ${lead.conference_name} ${lead.professional_email}`.toLowerCase();
      if (!haystack.includes(term)) return false;
    }
    return true;
  });

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredLeads.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredLeads.map(l => l.id)));
    }
  };

  const toggleSelectLead = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const selectedLeads = leads.filter(l => selectedIds.has(l.id));

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 p-5 shadow-sm">
      {/* Studio Controls Header */}
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pb-5 border-b border-slate-700/60">
        <div>
          <div className="flex items-center space-x-2">
            <Send className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-semibold text-white">Outreach Dispatch & Lead Manager</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Personalize, test, and dispatch outreach directly to verified conference leaders.
          </p>
        </div>

        {/* Action Buttons for Selected Leads */}
        <div className="flex items-center space-x-2 w-full lg:w-auto">
          {selectedIds.size > 0 && (
            <>
              <button
                onClick={() => onScheduleLeads(selectedLeads)}
                className="flex items-center space-x-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-all shadow-sm"
              >
                <Calendar className="w-3.5 h-3.5" />
                <span>Schedule ({selectedIds.size})</span>
              </button>

              <button
                onClick={() => {
                  if (confirm(`Send live outreach to ${selectedIds.size} selected leads?`)) {
                    selectedLeads.forEach(l => onSendDirect(l));
                  }
                }}
                className="flex items-center space-x-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition-all shadow-sm"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Batch Send ({selectedIds.size})</span>
              </button>
            </>
          )}

          {/* Category Tabs */}
          <div className="flex bg-slate-900 p-1 rounded-lg border border-slate-700 text-xs">
            <button
              onClick={() => setFilterType('qualified')}
              className={`px-3 py-1.5 rounded-md font-medium transition-all ${
                filterType === 'qualified' ? 'bg-emerald-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
            >
              Qualified Leads ({leads.filter(l => l.is_qualified).length})
            </button>
            <button
              onClick={() => setFilterType('non-qualified')}
              className={`px-3 py-1.5 rounded-md font-medium transition-all ${
                filterType === 'non-qualified' ? 'bg-amber-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
            >
              Non-Qualified ({leads.filter(l => !l.is_qualified).length})
            </button>
            <button
              onClick={() => setFilterType('all')}
              className={`px-3 py-1.5 rounded-md font-medium transition-all ${
                filterType === 'all' ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
            >
              All ({leads.length})
            </button>
          </div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 py-4">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search by contact, company, email, conference..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        <div className="flex items-center space-x-3 text-xs">
          <div className="flex items-center space-x-1.5">
            <span className="text-slate-400">Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 text-xs focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="Pending">Pending</option>
              <option value="Sent">Sent</option>
              <option value="Replied">Replied</option>
            </select>
          </div>

          <button
            onClick={toggleSelectAll}
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded bg-slate-900 border border-slate-700 text-slate-300 hover:text-white text-xs"
          >
            {selectedIds.size === filteredLeads.length && filteredLeads.length > 0 ? (
              <CheckSquare className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <Square className="w-3.5 h-3.5 text-slate-400" />
            )}
            <span>Select All ({filteredLeads.length})</span>
          </button>
        </div>
      </div>

      {/* Leads Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-700/80 max-h-[580px] overflow-y-auto">
        {loading ? (
          <div className="py-20 text-center text-slate-400 text-xs">Loading leads directly from Excel...</div>
        ) : filteredLeads.length === 0 ? (
          <div className="py-20 text-center text-slate-500 text-xs">No leads match the selected filter criteria.</div>
        ) : (
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/90 sticky top-0 z-10 text-[11px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700">
              <tr>
                <th className="py-3 px-3 w-8 text-center">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === filteredLeads.length && filteredLeads.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded bg-slate-800 border-slate-700 text-emerald-500 focus:ring-0 cursor-pointer"
                  />
                </th>
                <th className="py-3 px-3">Rank / Score</th>
                <th className="py-3 px-3">Company & Domain</th>
                <th className="py-3 px-3">Contact Person</th>
                <th className="py-3 px-3">Conference</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredLeads.map((lead) => {
                const isSelected = selectedIds.has(lead.id);
                const score = Number(lead.overall_score || 0);
                const isSent = lead.outreach_status.toLowerCase() === 'sent';

                return (
                  <tr
                    key={lead.id}
                    className={`transition-colors ${
                      isSelected ? 'bg-emerald-950/20' : 'hover:bg-slate-750/50 hover:bg-slate-700/30'
                    }`}
                  >
                    <td className="py-3 px-3 text-center">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelectLead(lead.id)}
                        className="rounded bg-slate-800 border-slate-700 text-emerald-500 focus:ring-0 cursor-pointer"
                      />
                    </td>

                    {/* Rank / Score */}
                    <td className="py-3 px-3 whitespace-nowrap">
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-slate-500">#{lead.rank || '-'}</span>
                        <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                          score >= 75 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          score >= 50 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                          'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}>
                          {score.toFixed(1)}
                        </span>
                      </div>
                    </td>

                    {/* Company */}
                    <td className="py-3 px-3">
                      <div className="font-medium text-white truncate max-w-xs">{lead.company_name}</div>
                      <div className="text-[11px] text-slate-400 flex items-center space-x-1.5 mt-0.5">
                        <span>{lead.company_domain || 'domain N/A'}</span>
                        {lead.primary_industry && (
                          <span className="text-slate-500">• {lead.primary_industry}</span>
                        )}
                      </div>
                    </td>

                    {/* Contact Person */}
                    <td className="py-3 px-3">
                      <div className="font-medium text-slate-200">{lead.contact_name}</div>
                      <div className="text-[11px] text-slate-400 truncate max-w-xs">{lead.job_title}</div>
                      <div className="text-[11px] font-mono text-emerald-400/90 mt-0.5 flex items-center space-x-1.5">
                        <span>{lead.professional_email}</span>
                        {lead.personal_linkedin_url && (
                          <a href={lead.personal_linkedin_url} target="_blank" rel="noopener noreferrer" className="text-slate-500 hover:text-teal-400">
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                    </td>

                    {/* Conference */}
                    <td className="py-3 px-3 max-w-xs">
                      <div className="text-slate-300 truncate" title={lead.conference_name}>
                        {lead.conference_name}
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                        Role: {lead.contact_type}
                      </div>
                    </td>

                    {/* Status Badges */}
                    <td className="py-3 px-3 whitespace-nowrap">
                      <div className="flex flex-col space-y-1">
                        <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium w-fit ${
                          isSent
                            ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
                            : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                        }`}>
                          {isSent ? <CheckCircle2 className="w-3 h-3" /> : <Clock className="w-3 h-3" />}
                          <span>{lead.outreach_status}</span>
                        </span>

                        {lead.reply_status && (
                          <span className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-teal-500/10 text-teal-400 border border-teal-500/20 w-fit">
                            Reply: {lead.reply_status}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Action Buttons */}
                    <td className="py-3 px-3 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end space-x-1.5">
                        <button
                          onClick={() => onComposeEmail(lead)}
                          className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-emerald-600 text-white transition-all shadow-sm"
                          title="Generate, Preview, or Edit Personalized Template"
                        >
                          <Sparkles className="w-3 h-3 text-emerald-400 group-hover:text-white" />
                          <span>Compose</span>
                        </button>

                        <button
                          onClick={() => onSendDirect(lead)}
                          className="p-1.5 rounded-lg text-slate-300 hover:text-white bg-slate-700 hover:bg-slate-600"
                          title="Send Direct Outreach Email"
                        >
                          <Send className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
