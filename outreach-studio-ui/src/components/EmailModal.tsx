import React, { useState, useEffect } from 'react';
import { Lead, GeneratedEmail } from '../types';
import { api } from '../services/api';
import { X, Sparkles, Send, Mail, RefreshCw, CheckCircle2, AlertCircle, FileText, User } from 'lucide-react';

interface EmailModalProps {
  lead: Lead | null;
  onClose: () => void;
  onSuccess: () => void;
}

export const EmailModal: React.FC<EmailModalProps> = ({ lead, onClose, onSuccess }) => {
  if (!lead) return null;

  const [subject, setSubject] = useState<string>('');
  const [body, setBody] = useState<string>('');
  const [useLLM, setUseLLM] = useState<boolean>(false);
  const [customPrompt, setCustomPrompt] = useState<string>('');
  const [generating, setGenerating] = useState<boolean>(false);
  const [sendingTest, setSendingTest] = useState<boolean>(false);
  const [testEmailAddress, setTestEmailAddress] = useState<string>('skjeeva2005@gmail.com');
  const [testStatus, setTestStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [sendingOutreach, setSendingOutreach] = useState<boolean>(false);
  const [sourceInfo, setSourceInfo] = useState<string>('');
  const [templateFile, setTemplateFile] = useState<string>('');

  useEffect(() => {
    generateContent();
  }, [lead]);

  const generateContent = async () => {
    setGenerating(true);
    setTestStatus(null);
    try {
      const res = await api.generateEmail({
        contact_name: lead.contact_name,
        job_title: lead.job_title,
        company_name: lead.company_name,
        conference_name: lead.conference_name,
        contact_type: lead.contact_type || 'Speaker',
        industry: lead.primary_industry || 'ai',
        use_llm: useLLM,
        custom_instructions: customPrompt
      });
      setSubject(res.subject);
      setBody(res.body);
      setSourceInfo(res.source);
      setTemplateFile(res.template_file);
    } catch (err: any) {
      console.error(err);
      setTestStatus({ ok: false, msg: `Generation failed: ${err.message}` });
    } finally {
      setGenerating(false);
    }
  };

  const handleSendTest = async () => {
    if (!testEmailAddress.includes('@')) {
      alert('Please enter a valid test recipient email address');
      return;
    }
    setSendingTest(true);
    setTestStatus(null);
    try {
      const res = await api.sendTestEmail({
        recipient_email: testEmailAddress,
        subject,
        body,
        lead_name: lead.contact_name,
        company_name: lead.company_name
      });
      setTestStatus({ ok: true, msg: `Test email dispatched to ${testEmailAddress}!` });
    } catch (err: any) {
      setTestStatus({ ok: false, msg: err.message || 'Failed to dispatch test email' });
    } finally {
      setSendingTest(false);
    }
  };

  const handleSendLive = async () => {
    if (!confirm(`Are you sure you want to send live outreach to ${lead.contact_name} at ${lead.professional_email}?`)) {
      return;
    }
    setSendingOutreach(true);
    try {
      await api.sendOutreach({
        email: lead.professional_email,
        subject,
        body,
        category: lead.contact_type || 'Speaker',
        dry_run: false
      });
      alert(`Outreach successfully sent to ${lead.contact_name}! Excel and OneDrive updated.`);
      onSuccess();
      onClose();
    } catch (err: any) {
      alert(`Error sending outreach: ${err.message}`);
    } finally {
      setSendingOutreach(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col max-h-[92vh] overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Outreach Email Composer & Personalizer</h3>
              <p className="text-xs text-slate-400">
                To: <span className="text-slate-200 font-medium">{lead.contact_name}</span> ({lead.job_title} @ {lead.company_name})
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Target Metadata Banner */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 text-xs">
            <div>
              <span className="text-slate-400 block text-[11px]">Conference</span>
              <span className="text-slate-200 font-medium truncate block">{lead.conference_name}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Deliverable Email</span>
              <span className="text-emerald-400 font-mono font-medium truncate block">{lead.professional_email}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Base Template Format</span>
              <span className="text-slate-200 truncate block">
                {templateFile} ({sourceInfo === 'llm_personalized' ? '⚡ LLM Personalized' : 'Static Rendered'})
              </span>
            </div>
          </div>

          {/* Personalization Controls */}
          <div className="p-3.5 rounded-xl bg-slate-800/40 border border-slate-700/50 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="llm-toggle"
                  checked={useLLM}
                  onChange={(e) => setUseLLM(e.target.checked)}
                  className="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0 cursor-pointer"
                />
                <label htmlFor="llm-toggle" className="text-xs font-medium text-slate-200 cursor-pointer flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Use Azure OpenAI for intelligent hook & industry personalization</span>
                </label>
              </div>

              <button
                onClick={generateContent}
                disabled={generating}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition-all disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${generating ? 'animate-spin' : ''}`} />
                <span>{generating ? 'Regenerating...' : 'Regenerate'}</span>
              </button>
            </div>

            {useLLM && (
              <div className="pt-1">
                <input
                  type="text"
                  placeholder="Optional custom instruction (e.g. 'Emphasize document extraction' or 'Mention their keynote panel')"
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                  className="w-full bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </div>
            )}
          </div>

          {/* Email Subject Editor */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Subject Line</label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-xs text-slate-100 font-medium focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          {/* Email Body Editor */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Email Body (Editable — Preserves Exact Approved Template Format)
            </label>
            <textarea
              rows={12}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-xl p-4 text-xs text-slate-200 font-mono leading-relaxed focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none"
            />
          </div>

          {/* Status Alert if any */}
          {testStatus && (
            <div className={`p-3 rounded-xl text-xs flex items-center space-x-2 ${
              testStatus.ok ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
            }`}>
              {testStatus.ok ? <CheckCircle2 className="w-4 h-4 flex-shrink-0" /> : <AlertCircle className="w-4 h-4 flex-shrink-0" />}
              <span>{testStatus.msg}</span>
            </div>
          )}
        </div>

        {/* Modal Footer: Test Send & Live Outreach Dispatch */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-6 py-4 border-t border-slate-800 bg-slate-900/90">
          {/* Test Email Section */}
          <div className="flex items-center space-x-2 w-full sm:w-auto">
            <input
              type="email"
              value={testEmailAddress}
              onChange={(e) => setTestEmailAddress(e.target.value)}
              placeholder="Your test email (e.g. skjeeva2005@gmail.com)"
              className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 w-60 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <button
              onClick={handleSendTest}
              disabled={sendingTest}
              className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 hover:border-slate-600 transition-all disabled:opacity-50"
            >
              <Mail className="w-3.5 h-3.5 text-emerald-400" />
              <span>{sendingTest ? 'Sending...' : 'Send Test'}</span>
            </button>
          </div>

          {/* Live Action Buttons */}
          <div className="flex items-center space-x-2 w-full sm:w-auto justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>

            <button
              onClick={handleSendLive}
              disabled={sendingOutreach}
              className="flex items-center space-x-1.5 px-5 py-2 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition-all shadow-lg shadow-emerald-600/20 disabled:opacity-50"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{sendingOutreach ? 'Dispatching...' : 'Approve & Send Outreach'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
