import React, { useState, useEffect } from 'react';
import { ScheduleItem } from '../types';
import { api } from '../services/api';
import { Calendar, Clock, CheckCircle2, XCircle, AlertCircle, RefreshCw, Trash2, Users } from 'lucide-react';

export const ScheduledList: React.FC = () => {
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    loadSchedules();
  }, []);

  const loadSchedules = async () => {
    setLoading(true);
    try {
      const data = await api.getSchedules();
      setSchedules(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async (id: string) => {
    if (!confirm('Are you sure you want to cancel this scheduled outreach?')) return;
    try {
      await api.cancelSchedule(id);
      loadSchedules();
    } catch (err: any) {
      alert(`Error cancelling schedule: ${err.message}`);
    }
  };

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 p-5 shadow-sm">
      <div className="flex items-center justify-between pb-5 border-b border-slate-700/60">
        <div>
          <div className="flex items-center space-x-2">
            <Calendar className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Outreach Dispatch Schedules</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage queued campaigns and scheduled outreach timings.
          </p>
        </div>

        <button
          onClick={loadSchedules}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="py-5">
        {loading ? (
          <div className="py-16 text-center text-slate-400 text-xs">Loading scheduled campaigns...</div>
        ) : schedules.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-xs">
            No active schedules found. Use the Outreach Studio tab to select leads and schedule an outreach campaign.
          </div>
        ) : (
          <div className="space-y-3">
            {schedules.map((s) => {
              const isScheduled = s.status === 'scheduled';
              return (
                <div
                  key={s.id}
                  className="p-4 rounded-xl bg-slate-900/80 border border-slate-700/70 flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
                >
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="font-mono text-xs font-semibold text-white">{s.id}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                        isScheduled
                          ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                          : s.status === 'completed'
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : 'bg-slate-800 text-slate-400 border border-slate-700'
                      }`}>
                        {s.status.toUpperCase()}
                      </span>
                    </div>

                    <p className="text-xs text-slate-300 font-medium">{s.notes}</p>

                    <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400 pt-1">
                      <span className="flex items-center space-x-1">
                        <Clock className="w-3 h-3 text-blue-400" />
                        <span>Dispatch at: <b className="text-slate-200">{s.scheduled_time}</b></span>
                      </span>

                      <span className="flex items-center space-x-1">
                        <Users className="w-3 h-3 text-slate-400" />
                        <span>{s.lead_count} Recipients</span>
                      </span>

                      <span>Created: {new Date(s.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>

                  {isScheduled && (
                    <button
                      onClick={() => handleCancel(s.id)}
                      className="flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 transition-all"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Cancel Schedule</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
