import React, { useState, useEffect } from 'react';
import { ReplyItem } from '../types';
import { api } from '../services/api';
import { MessageSquare, RefreshCw, ChevronDown, ChevronUp, Mail, User, Building2, Calendar, Sparkles } from 'lucide-react';

export const RepliesMonitor: React.FC = () => {
  const [replies, setReplies] = useState<ReplyItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    loadReplies();
  }, []);

  const loadReplies = async () => {
    setLoading(true);
    try {
      const data = await api.getReplies();
      setReplies(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 p-5 shadow-sm">
      <div className="flex items-center justify-between pb-5 border-b border-slate-700/60">
        <div>
          <div className="flex items-center space-x-2">
            <MessageSquare className="w-5 h-5 text-teal-400" />
            <h2 className="text-lg font-semibold text-white">Captured Outreach Replies</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time replies synced with the 'Speakers Replies' workbook sheet and Teams card trigger.
          </p>
        </div>

        <button
          onClick={loadReplies}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Replies</span>
        </button>
      </div>

      <div className="py-5">
        {loading ? (
          <div className="py-16 text-center text-slate-400 text-xs">Loading replies from Excel workbook...</div>
        ) : replies.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-xs">
            No incoming replies captured yet. The 24/7 background reply watcher is active.
          </div>
        ) : (
          <div className="space-y-3">
            {replies.map((rep) => {
              const isExpanded = expandedId === rep.id;
              const sentiment = (rep.reply_sentiment || 'Neutral').toLowerCase();
              const sentimentColor = sentiment.includes('positive')
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : sentiment.includes('negative')
                ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                : 'bg-teal-500/10 text-teal-400 border-teal-500/20';

              return (
                <div
                  key={rep.id}
                  className="rounded-xl bg-slate-900/80 border border-slate-700/70 overflow-hidden transition-all"
                >
                  <div
                    onClick={() => toggleExpand(rep.id)}
                    className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 cursor-pointer hover:bg-slate-800/40"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <span className="font-semibold text-xs text-white">{rep.speaker_name}</span>
                        {rep.company_name && (
                          <span className="text-xs text-slate-400">@ {rep.company_name}</span>
                        )}
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${sentimentColor}`}>
                          {rep.reply_sentiment || 'Neutral'}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                        <span className="font-mono text-emerald-400">{rep.email}</span>
                        {rep.conference_name && <span>• {rep.conference_name}</span>}
                        {rep.reply_received_at && (
                          <span className="text-slate-500">• Received: {rep.reply_received_at}</span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center space-x-2">
                      <span className="text-[11px] text-slate-400 font-medium">
                        {isExpanded ? 'Hide Conversation' : 'View Thread'}
                      </span>
                      {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-slate-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-slate-400" />
                      )}
                    </div>
                  </div>

                  {/* Expanded Conversation View */}
                  {isExpanded && (
                    <div className="p-4 border-t border-slate-800 bg-slate-950/60 space-y-3 text-xs">
                      {/* Received Reply Content */}
                      <div>
                        <div className="flex items-center space-x-1.5 text-teal-400 font-medium mb-1">
                          <MessageSquare className="w-3.5 h-3.5" />
                          <span>Incoming Reply Message:</span>
                        </div>
                        <div className="p-3.5 rounded-xl bg-slate-900 border border-teal-500/20 text-slate-200 whitespace-pre-wrap font-sans leading-relaxed">
                          {rep.received_reply || 'No text content available'}
                        </div>
                      </div>

                      {/* Original Sent Message */}
                      {rep.send_message && (
                        <div>
                          <div className="flex items-center space-x-1.5 text-slate-400 font-medium mb-1">
                            <Mail className="w-3.5 h-3.5" />
                            <span>Original Sent Outreach Message:</span>
                          </div>
                          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 text-slate-400 whitespace-pre-wrap font-mono text-[11px] max-h-48 overflow-y-auto">
                            {rep.send_message}
                          </div>
                        </div>
                      )}

                      {rep.thread_id && (
                        <div className="text-[10px] text-slate-500 font-mono">
                          Graph Thread ID: {rep.thread_id}
                        </div>
                      )}
                    </div>
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
