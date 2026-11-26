import React, { useState } from 'react';
import { Lead } from '../types';
import { api } from '../services/api';
import { X, Calendar, Clock, CheckCircle2, Users } from 'lucide-react';

interface ScheduleModalProps {
  leads: Lead[];
  onClose: () => void;
  onSuccess: () => void;
}

export const ScheduleModal: React.FC<ScheduleModalProps> = ({ leads, onClose, onSuccess }) => {
  if (!leads.length) return null;

  // Default to tomorrow 8:00 PM IST
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(20, 0, 0, 0);

  const [scheduledDateTime, setScheduledDateTime] = useState<string>(
    tomorrow.toISOString().slice(0, 16)
  );
  const [notes, setNotes] = useState<string>('Upcoming Week Enterprise Outreach Batch');
  const [saving, setSaving] = useState<boolean>(false);

  const handleScheduleSubmit = async () => {
    setSaving(true);
    try {
      await api.scheduleOutreach({
        leads,
        scheduled_time: scheduledDateTime,
        notes
      });
      alert(`Successfully scheduled outreach for ${leads.length} lead(s) at ${scheduledDateTime}!`);
      onSuccess();
      onClose();
    } catch (err: any) {
      alert(`Scheduling error: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div className="flex items-center space-x-2.5">
            <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Schedule Automated Outreach</h3>
              <p className="text-xs text-slate-400">Configure target dispatch date and time</p>
            </div>
          </div>

          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <div className="p-6 space-y-4">
          <div className="p-3 rounded-xl bg-slate-800/60 border border-slate-700/60 flex items-center space-x-3">
            <Users className="w-5 h-5 text-blue-400 flex-shrink-0" />
            <div className="text-xs">
              <span className="text-slate-200 font-semibold">{leads.length} Verified Recipients Selected</span>
              <p className="text-slate-400 truncate">
                {leads.slice(0, 3).map(l => l.contact_name).join(', ')}
                {leads.length > 3 ? ` and ${leads.length - 3} others` : ''}
              </p>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center space-x-1.5">
              <Clock className="w-3.5 h-3.5 text-blue-400" />
              <span>Target Dispatch Date & Time</span>
            </label>
            <input
              type="datetime-local"
              value={scheduledDateTime}
              onChange={(e) => setScheduledDateTime(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">Schedule Notes / Campaign Tag</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Thursday 8 PM Qualified Outreach"
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
            Automated scheduler will send via the existing Microsoft Graph pipeline, suppressing any bounced emails and logging Thread IDs to Excel.
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end space-x-2 px-6 py-4 border-t border-slate-800 bg-slate-900/90">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            onClick={handleScheduleSubmit}
            disabled={saving}
            className="flex items-center space-x-1.5 px-5 py-2 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-all shadow-md shadow-blue-600/20 disabled:opacity-50"
          >
            <Calendar className="w-3.5 h-3.5" />
            <span>{saving ? 'Scheduling...' : `Confirm Schedule (${leads.length})`}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
