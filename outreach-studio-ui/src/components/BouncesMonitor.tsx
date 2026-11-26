import React, { useState, useEffect } from 'react';
import { BounceItem } from '../types';
import { api } from '../services/api';
import { AlertOctagon, ShieldCheck, RefreshCw, AlertTriangle } from 'lucide-react';

export const BouncesMonitor: React.FC = () => {
  const [bounces, setBounces] = useState<BounceItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    loadBounces();
  }, []);

  const loadBounces = async () => {
    setLoading(true);
    try {
      const data = await api.getBounces();
      setBounces(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 p-5 shadow-sm">
      <div className="flex items-center justify-between pb-5 border-b border-slate-700/60">
        <div>
          <div className="flex items-center space-x-2">
            <AlertOctagon className="w-5 h-5 text-rose-400" />
            <h2 className="text-lg font-semibold text-white">NDR & Bounce Suppression Capture</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time Non-Delivery Reports (NDR) captured by the 24/7 Bounce Watcher to protect domain reputation.
          </p>
        </div>

        <button
          onClick={loadBounces}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Bounces</span>
        </button>
      </div>

      <div className="py-5">
        {/* Protection Banner */}
        <div className="mb-4 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center space-x-3 text-xs text-emerald-300">
          <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0" />
          <div>
            <span className="font-semibold text-white">Automated Domain Safeguard Active</span>
            <p className="text-emerald-400/90 mt-0.5">
              All suppressed addresses are permanently blocked from subsequent email dispatches, preventing email bounces and preserving high sender domain deliverability.
            </p>
          </div>
        </div>

        {loading ? (
          <div className="py-16 text-center text-slate-400 text-xs">Loading bounce logs...</div>
        ) : bounces.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-xs">
            Zero bounces detected in the active window. All outreach dispatches have clean deliverability.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-700/80 max-h-[500px] overflow-y-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900 sticky top-0 text-[11px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700">
                <tr>
                  <th className="py-3 px-4">#</th>
                  <th className="py-3 px-4">Message / NDR Identifier</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Action Taken</th>
                  <th className="py-3 px-4">Logged Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {bounces.map((b, idx) => (
                  <tr key={b.id} className="hover:bg-slate-700/30">
                    <td className="py-2.5 px-4 font-mono text-slate-500">{idx + 1}</td>
                    <td className="py-2.5 px-4 font-mono text-rose-300 truncate max-w-sm">{b.message_id}</td>
                    <td className="py-2.5 px-4">
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
                        {b.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-slate-300">{b.action_taken}</td>
                    <td className="py-2.5 px-4 text-slate-400">{b.detected_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
