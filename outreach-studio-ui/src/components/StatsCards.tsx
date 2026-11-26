import React from 'react';
import { OverviewMetrics } from '../types';
import { CheckCircle2, Clock, Send, MessageCircle, AlertTriangle, Layers } from 'lucide-react';

interface StatsCardsProps {
  metrics: OverviewMetrics | null;
  sheetCounts: Record<string, number>;
}

export const StatsCards: React.FC<StatsCardsProps> = ({ metrics, sheetCounts }) => {
  if (!metrics) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-6 animate-pulse">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-24 bg-slate-800/60 rounded-xl border border-slate-700/50"></div>
        ))}
      </div>
    );
  }

  const cards = [
    {
      title: 'Upcoming Qualified',
      value: metrics.qualified_leads_upcoming,
      sub: `${metrics.qualified_leads_total} Total Qualified`,
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      border: 'border-emerald-500/20'
    },
    {
      title: 'Upcoming Non-Qualified',
      value: metrics.non_qualified_leads_upcoming,
      sub: `${metrics.non_qualified_leads_total} Total Disqualified`,
      icon: Layers,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      border: 'border-amber-500/20'
    },
    {
      title: 'Outreach Pending',
      value: metrics.outreach_pending,
      sub: 'Ready for Scheduled Dispatch',
      icon: Clock,
      color: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
      border: 'border-blue-500/20'
    },
    {
      title: 'Emails Dispatched',
      value: metrics.outreach_sent,
      sub: `${metrics.active_threads} Active Threads`,
      icon: Send,
      color: 'text-purple-400',
      bgColor: 'bg-purple-500/10',
      border: 'border-purple-500/20'
    },
    {
      title: 'Captured Replies',
      value: metrics.replies_captured,
      sub: 'Tracked in Speakers Replies',
      icon: MessageCircle,
      color: 'text-teal-400',
      bgColor: 'bg-teal-500/10',
      border: 'border-teal-500/20'
    },
    {
      title: 'Bounces Suppressed',
      value: metrics.bounces_captured,
      sub: 'Zero Domain Risk',
      icon: AlertTriangle,
      color: 'text-rose-400',
      bgColor: 'bg-rose-500/10',
      border: 'border-rose-500/20'
    }
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
      {cards.map((card, idx) => {
        const Icon = card.icon;
        return (
          <div
            key={idx}
            className={`p-4 rounded-xl bg-slate-800/80 border ${card.border} shadow-sm flex flex-col justify-between`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-slate-400">{card.title}</span>
              <div className={`p-1.5 rounded-lg ${card.bgColor}`}>
                <Icon className={`w-4 h-4 ${card.color}`} />
              </div>
            </div>
            <div>
              <div className={`text-2xl font-bold ${card.color}`}>{card.value}</div>
              <div className="text-[11px] text-slate-500 truncate mt-0.5">{card.sub}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
