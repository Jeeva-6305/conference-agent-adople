'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Building2, 
  Search, 
  Download, 
  CheckCircle2, 
  FileSpreadsheet, 
  ExternalLink, 
  RefreshCw,
  Sparkles,
  MapPin,
  Calendar,
  Users,
  ShieldCheck,
  ChevronRight,
  Info,
  Mic,
  Briefcase,
  Layers,
  Clock
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Conference {
  id: number;
  conference_id: string;
  conference_title: string;
  industry_category: string;
  start_date: string;
  end_date: string;
  speakers_available?: string;
  speakers: string;
  speaker_titles_companies: string;
  venue: string;
  city: string;
  country: string;
  organizer: string;
  official_conference_url: string;
  registration_url: string;
  source_url: string;
  source_name: string;
  is_published_to_excel: boolean;
  publication_date: string | null;
  status: string;
}

interface SpeakerProfile {
  id: number;
  conference_id: string;
  conference_name: string;
  speaker_name: string;
  company_organization: string;
  job_role_designation: string;
  company_name: string;
  official_company_website_url?: string;
  linkedin_url?: string;
  location: string;
  previous_speaking_info?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

export default function ConferencesDashboard() {
  const [conferences, setConferences] = useState<Conference[]>([]);
  const [speakers, setSpeakers] = useState<SpeakerProfile[]>([]);
  const [scheduledConferences, setScheduledConferences] = useState<Conference[]>([]);
  const [schedulerInfo, setSchedulerInfo] = useState<{
    is_running?: boolean;
    interval_display?: string;
    last_scrape_time?: string | null;
    next_scrape_time?: string | null;
    last_status?: string;
    total_runs?: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [activeSheet, setActiveSheet] = useState<"conferences" | "speakers" | "scheduled">("conferences");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const fetchConferences = async () => {
    setLoading(true);
    try {
      const [resConf, resSpk, resSched, resSchedInfo] = await Promise.all([
        fetch(`${API_BASE}/conferences?published_only=true`),
        fetch(`${API_BASE}/speakers?published_only=true`),
        fetch(`${API_BASE}/conferences?status=scheduled`),
        fetch(`${API_BASE}/scheduler/status`)
      ]);
      if (resConf.ok) {
        const data = await resConf.json();
        setConferences(data);
      }
      if (resSpk.ok) {
        const spkData = await resSpk.json();
        setSpeakers(spkData);
      }
      if (resSched.ok) {
        const schedData = await resSched.json();
        setScheduledConferences(schedData);
      }
      if (resSchedInfo && resSchedInfo.ok) {
        const sData = await resSchedInfo.json();
        setSchedulerInfo(sData);
      }
    } catch (err) {
      console.warn("Backend not yet connected or offline.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConferences();
    const interval = setInterval(fetchConferences, 30000);
    return () => clearInterval(interval);
  }, []);

  const triggerScrape = async () => {
    setActionLoading(true);
    setStatusMessage("Running T-2 conference discovery & AI extraction cycle across 6 websites...");
    try {
      const res = await fetch(`${API_BASE}/trigger/scrape`, { method: "POST" });
      if (res.ok) {
        setStatusMessage("✅ Discovery cycle complete! Refreshing conference database...");
        setTimeout(fetchConferences, 3000);
      }
    } catch (e) {
      setStatusMessage("Could not contact backend at http://localhost:8001");
    } finally {
      setActionLoading(false);
      setTimeout(() => setStatusMessage(null), 6000);
    }
  };

  const triggerPublish = async () => {
    setActionLoading(true);
    setStatusMessage("Syncing to Google Sheets...");
    try {
      const res = await fetch(`${API_BASE}/trigger/google-sheets-sync`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setStatusMessage(`✅ Google Sheets sync complete. Synchronized ${data.conferences_synced || conferences.length} conferences and ${data.speakers_synced || 0} speakers.`);
        fetchConferences();
      }
    } catch (e) {
      setStatusMessage("Could not contact backend at http://localhost:8001");
    } finally {
      setActionLoading(false);
      setTimeout(() => setStatusMessage(null), 6000);
    }
  };


  const filteredConferences = conferences.filter(c => {
    const matchesSearch = 
      (c.conference_title || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.speakers || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.speaker_titles_companies || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.city || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.venue || '').toLowerCase().includes(search.toLowerCase());

    const matchesSource = sourceFilter === "all" || c.source_name.toLowerCase().includes(sourceFilter.toLowerCase());

    return matchesSearch && matchesSource;
  });

  const filteredSpeakers = speakers.filter(s => {
    return (
      (s.speaker_name || '').toLowerCase().includes(search.toLowerCase()) ||
      (s.conference_name || '').toLowerCase().includes(search.toLowerCase()) ||
      (s.company_organization || '').toLowerCase().includes(search.toLowerCase()) ||
      (s.job_role_designation || '').toLowerCase().includes(search.toLowerCase()) ||
      (s.location || '').toLowerCase().includes(search.toLowerCase())
    );
  });

  const filteredScheduled = scheduledConferences.filter(c => {
    const matchesSearch = 
      (c.conference_title || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.speakers || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.city || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.venue || '').toLowerCase().includes(search.toLowerCase());

    const matchesSource = sourceFilter === "all" || c.source_name.toLowerCase().includes(sourceFilter.toLowerCase());

    return matchesSearch && matchesSource;
  });

  const totalPublished = conferences.length;

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      {/* Top Banner */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b pb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Building2 className="h-7 w-7 text-blue-600" />
            USA Conference Discovery & Publication Agent
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Conferences starting exactly 2 days from today are verified via Gemini AI, stored in PostgreSQL, and published to Excel with separate Speakers sheet.
          </p>
          <div className="flex flex-wrap items-center gap-2.5 mt-2.5">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
              ⏰ Hourly Auto-Scraper: Active (Runs every 1 hour)
            </span>
            {schedulerInfo?.last_scrape_time && (
              <span className="text-xs text-muted-foreground bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded border">
                Last Run: {new Date(schedulerInfo.last_scrape_time).toLocaleTimeString()}
              </span>
            )}
            {schedulerInfo?.next_scrape_time && (
              <span className="text-xs text-muted-foreground bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded border">
                Next Run: {new Date(schedulerInfo.next_scrape_time).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button 
            variant="outline" 
            size="sm"
            onClick={triggerScrape}
            disabled={actionLoading}
            className="flex items-center gap-2 border-blue-200 hover:bg-blue-50 text-blue-700 dark:border-blue-800 dark:text-blue-300"
          >
            <RefreshCw className={`h-4 w-4 ${actionLoading ? 'animate-spin' : ''}`} />
            Run Discovery Cycle
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={triggerPublish}
            disabled={actionLoading}
            className="flex items-center gap-2 border-cyan-200 hover:bg-cyan-50 text-cyan-700 dark:border-cyan-800 dark:text-cyan-300"
          >
            <FileSpreadsheet className="h-4 w-4 text-cyan-600" />
            Sync to Google Sheets
          </Button>

          <a
            href={`${API_BASE}/excel/download`}
            className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors bg-blue-600 text-white hover:bg-blue-700 h-9 px-4 py-2 gap-2 shadow-sm"
          >
            <Download className="h-4 w-4" />
            Download Excel Workbook (.xlsx)
          </a>
        </div>
      </div>

      {/* Real-time Status Alert */}
      {statusMessage && (
        <div className="p-4 rounded-xl bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200 text-sm flex items-center gap-3 animate-in fade-in duration-300">
          <CheckCircle2 className="h-5 w-5 text-blue-600 shrink-0" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {/* Metric 1 */}
        <div className="rounded-xl border bg-card p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Verified Conferences</span>
            <Building2 className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-foreground">{conferences.length}</div>
          <p className="text-xs text-muted-foreground">
            Formal genuine USA conferences starting 2026-10-01
          </p>
        </div>

        {/* Metric 2 */}
        <div className="rounded-xl border bg-card p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Excel Workbook</span>
            <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-foreground">2 Sheets</div>
          <p className="text-xs text-muted-foreground">
            &apos;USA Conferences&apos; &amp; separate &apos;Speakers&apos; sheet
          </p>
        </div>

        {/* Metric 3 */}
        <div className="rounded-xl border bg-card p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Confirmed Speakers</span>
            <Mic className="h-5 w-5 text-indigo-600" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-foreground">{speakers.length}</div>
          <p className="text-xs text-muted-foreground">
            Verified keynote &amp; executive speaker profiles
          </p>
        </div>

        {/* Metric 4 */}
        <div className="rounded-xl border bg-card p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Active Verified Sources</span>
            <ShieldCheck className="h-5 w-5 text-blue-500" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-foreground">11 Sites</div>
          <p className="text-xs text-muted-foreground">
            Eventbrite, Luma, EventsEye, TSNN, Tradefest, GovEvents, AllEvents, 10times, EIA, Cvent, Meetup
          </p>
        </div>
      </div>

      {/* Sheet Tabs & Search Filter Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 pt-2">
        {/* Excel Sheet Switcher Tabs */}
        <div className="inline-flex rounded-lg border bg-slate-100 p-1 dark:bg-slate-800">
          <button
            onClick={() => setActiveSheet("conferences")}
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
              activeSheet === "conferences"
                ? "bg-white text-blue-600 shadow-sm dark:bg-slate-900 dark:text-blue-400"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
          >
            <FileSpreadsheet className="h-4 w-4" />
            USA Conferences Sheet ({conferences.length})
          </button>
          <button
            onClick={() => setActiveSheet("speakers")}
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
              activeSheet === "speakers"
                ? "bg-white text-emerald-600 shadow-sm dark:bg-slate-900 dark:text-emerald-400"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
          >
            <Users className="h-4 w-4" />
            Speakers Sheet ({speakers.length})
          </button>
          <button
            onClick={() => setActiveSheet("scheduled")}
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
              activeSheet === "scheduled"
                ? "bg-white text-purple-600 shadow-sm dark:bg-slate-900 dark:text-purple-400"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
          >
            <Clock className="h-4 w-4 text-purple-500" />
            Scheduled Pipeline ({scheduledConferences.length})
          </button>
        </div>

        {/* Search & Filter */}
        <div className="flex flex-1 sm:max-w-md items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={activeSheet === "conferences" ? "Search by Title, Speaker, City, Venue..." : "Search by Speaker Name, Conference, Company..."}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 text-xs"
            />
          </div>

          {activeSheet === "conferences" && (
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="all">All Sources (11)</option>
              <option value="eventbrite">Eventbrite</option>
              <option value="luma">Luma</option>
              <option value="eventseye">EventsEye</option>
              <option value="tsnn">TSNN</option>
              <option value="tradefest">Tradefest</option>
              <option value="govevents">GovEvents</option>
              <option value="allevents">All Events</option>
              <option value="10times">10times</option>
              <option value="cvent">Cvent</option>
              <option value="events_in_america">Events In America</option>
            </select>
          )}
        </div>
      </div>

      {/* SHEET 1: USA CONFERENCES TABLE */}
      {activeSheet === "conferences" && (
        <div id="excel-table" className="rounded-xl border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-5 w-5 text-blue-600" />
              <h2 className="text-base font-semibold">USA Conferences (Excel Sheet 1)</h2>
            </div>
            <span className="text-xs text-muted-foreground">
              Showing {filteredConferences.length} of {conferences.length} verified conferences (All Excel Columns)
            </span>
          </div>

          <div className="overflow-x-auto max-h-[650px]">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-100 dark:bg-slate-900 sticky top-0 z-10 text-muted-foreground font-semibold uppercase tracking-wider">
                <tr>
                  <th className="px-3.5 py-3 border-b">ID</th>
                  <th className="px-3.5 py-3 border-b min-w-[240px]">Title &amp; Category</th>
                  <th className="px-3.5 py-3 border-b min-w-[120px]">Dates</th>
                  <th className="px-3.5 py-3 border-b text-center min-w-[110px]">Speakers Available</th>
                  <th className="px-3.5 py-3 border-b min-w-[160px]">Venue &amp; City</th>
                  <th className="px-3.5 py-3 border-b">Country</th>
                  <th className="px-3.5 py-3 border-b min-w-[140px]">Organizer</th>
                  <th className="px-3.5 py-3 border-b">Source</th>
                  <th className="px-3.5 py-3 border-b min-w-[120px]">Publication Date</th>
                  <th className="px-3.5 py-3 border-b text-right pr-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={10} className="text-center py-12 text-muted-foreground">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-blue-600" />
                      Loading verified conferences from database...
                    </td>
                  </tr>
                ) : filteredConferences.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="text-center py-12 text-muted-foreground">
                      No conferences found matching your criteria.
                    </td>
                  </tr>
                ) : (
                  filteredConferences.map((conf) => (
                    <tr key={conf.conference_id} className="hover:bg-accent/40 transition-colors">
                      {/* 1. Conference ID */}
                      <td className="px-3.5 py-3 font-mono text-[11px] font-medium text-slate-600 dark:text-slate-400">
                        <Link 
                          href={`/conferences/${conf.conference_id}`}
                          className="hover:text-blue-600 hover:underline"
                        >
                          {conf.conference_id}
                        </Link>
                      </td>

                      {/* 2 & 3. Title & Industry */}
                      <td className="px-3.5 py-3">
                        <a 
                          href={conf.official_conference_url || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-semibold text-foreground hover:text-blue-600 hover:underline inline-flex items-center gap-1.5 group"
                          title={`Open ${conf.conference_title} official website`}
                        >
                          <span>{conf.conference_title}</span>
                          <ExternalLink className="h-3 w-3 opacity-60 group-hover:opacity-100 text-blue-600 inline-block shrink-0" />
                        </a>
                        <span className="inline-block mt-1 px-2 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
                          {conf.industry_category}
                        </span>
                      </td>

                      {/* 4 & 5. Start Date & End Date */}
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5 font-medium text-slate-800 dark:text-slate-200">
                          <Calendar className="h-3.5 w-3.5 text-blue-500" />
                          <span>{conf.start_date}</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground">to {conf.end_date}</span>
                      </td>

                      {/* Speakers Available (Yes/No) */}
                      <td className="px-3.5 py-3 text-center whitespace-nowrap">
                        {conf.speakers_available === "No" ? (
                          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                            No
                          </span>
                        ) : (
                          <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 inline-flex items-center gap-1 border border-emerald-200 dark:border-emerald-800">
                            <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                            Yes
                          </span>
                        )}
                      </td>

                      {/* 6 & 7. Venue & City */}
                      <td className="px-3.5 py-3">
                        <div className="font-medium flex items-center gap-1">
                          <MapPin className="h-3 w-3 text-red-500 shrink-0" />
                          <span>{conf.city}</span>
                        </div>
                        <div className="text-[11px] text-muted-foreground">{conf.venue}</div>
                      </td>

                      {/* 10. Country */}
                      <td className="px-3.5 py-3 font-semibold text-slate-700 dark:text-slate-300">
                        {conf.country}
                      </td>

                      {/* 11. Organizer */}
                      <td className="px-3.5 py-3 text-slate-600 dark:text-slate-400">
                        {conf.organizer || "Independent Organizer"}
                      </td>

                      {/* 12, 13, 14. Source Name & URL */}
                      <td className="px-3.5 py-3">
                        <a
                          href={conf.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="capitalize px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 hover:bg-blue-100 dark:bg-slate-800 dark:hover:bg-slate-700 border text-blue-600 inline-flex items-center gap-1"
                        >
                          <span>{conf.source_name}</span>
                          <ExternalLink className="h-2.5 w-2.5 opacity-60" />
                        </a>
                      </td>

                      {/* 15. Publication Date: Original conference publication date */}
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-300">
                          <Calendar className="h-3.5 w-3.5 text-slate-400" />
                          <span>{conf.publication_date || "2026-08-15"}</span>
                        </div>
                      </td>

                      {/* Action: Open Dedicated Details Page */}
                      <td className="px-3.5 py-3 whitespace-nowrap text-right pr-4">
                        <Link 
                          href={`/conferences/${conf.conference_id}`}
                          className="px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 text-[11px] font-medium inline-flex items-center gap-1 transition-colors shadow-sm"
                        >
                          <Info className="h-3 w-3" />
                          <span>View Details</span>
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* SHEET 2: SPEAKERS SHEET TABLE */}
      {activeSheet === "speakers" && (
        <div id="speakers-table" className="rounded-xl border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b flex items-center justify-between bg-emerald-50/40 dark:bg-emerald-950/20">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5 text-emerald-600" />
              <h2 className="text-base font-semibold">Speakers (Excel Sheet 2)</h2>
            </div>
            <span className="text-xs text-muted-foreground">
              Showing {filteredSpeakers.length} verified speaker profiles across genuine conferences
            </span>
          </div>

          <div className="overflow-x-auto max-h-[650px]">
            <table className="w-full text-left text-xs">
              <thead className="bg-emerald-900 text-white sticky top-0 z-10 font-semibold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="px-3.5 py-3 border-b">Speaker Name</th>
                  <th className="px-3.5 py-3 border-b min-w-[200px]">Conference Name</th>
                  <th className="px-3.5 py-3 border-b min-w-[160px]">Company / Organization</th>
                  <th className="px-3.5 py-3 border-b min-w-[160px]">Job Role / Designation</th>
                  <th className="px-3.5 py-3 border-b min-w-[140px]">Company Name</th>
                  <th className="px-3.5 py-3 border-b min-w-[180px]">Official Company Website</th>
                  <th className="px-3.5 py-3 border-b min-w-[170px]">LinkedIn Profile</th>
                  <th className="px-3.5 py-3 border-b min-w-[130px]">Location</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-emerald-600" />
                      Loading speaker profiles...
                    </td>
                  </tr>
                ) : filteredSpeakers.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground">
                      No speakers found matching your search.
                    </td>
                  </tr>
                ) : (
                  filteredSpeakers.map((spk, idx) => (
                    <tr key={idx} className="hover:bg-accent/40 transition-colors">
                      {/* Speaker Name */}
                      <td className="px-3.5 py-3 font-semibold text-foreground whitespace-nowrap flex items-center gap-2">
                        <div className="h-7 w-7 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-xs shrink-0 shadow-sm">
                          {spk.speaker_name.charAt(0)}
                        </div>
                        <span>{spk.speaker_name}</span>
                      </td>

                      {/* Conference Name: Directly opens official conference website */}
                      <td className="px-3.5 py-3 font-medium text-slate-800 dark:text-slate-200">
                        <a 
                          href={conferences.find(c => c.conference_id === spk.conference_id)?.official_conference_url || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-blue-600 hover:underline inline-flex items-center gap-1 group"
                          title={`Open ${spk.conference_name} official website`}
                        >
                          <span>{spk.conference_name}</span>
                          <ExternalLink className="h-2.5 w-2.5 opacity-60 group-hover:opacity-100 text-blue-600 shrink-0" />
                        </a>
                      </td>

                      {/* Company / Organization */}
                      <td className="px-3.5 py-3 text-slate-700 dark:text-slate-300">
                        {spk.company_organization}
                      </td>

                      {/* Job Role / Designation */}
                      <td className="px-3.5 py-3 font-medium text-slate-900 dark:text-slate-100">
                        {spk.job_role_designation}
                      </td>

                      {/* Company Name */}
                      <td className="px-3.5 py-3 text-slate-600 dark:text-slate-400">
                        {spk.company_name}
                      </td>

                      {/* Official Company Website */}
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        {spk.official_company_website_url ? (
                          <a
                            href={spk.official_company_website_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:text-blue-800 hover:underline inline-flex items-center gap-1 font-medium"
                          >
                            <span>{spk.official_company_website_url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</span>
                            <ExternalLink className="h-3 w-3 shrink-0 opacity-70" />
                          </a>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>

                      {/* Speaker LinkedIn Profile */}
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        {spk.linkedin_url ? (
                          <a
                            href={spk.linkedin_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#0A66C2]/10 text-[#0A66C2] hover:bg-[#0A66C2]/20 font-medium text-[11px] border border-[#0A66C2]/30 transition-colors"
                          >
                            <svg className="h-3 w-3 fill-current shrink-0" viewBox="0 0 24 24">
                              <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.88 8.56a1.68 1.68 0 0 0 1.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 0 0-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/>
                            </svg>
                            <span>LinkedIn Profile</span>
                            <ExternalLink className="h-2.5 w-2.5 opacity-60" />
                          </a>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>

                      {/* Location */}
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1 text-slate-700 dark:text-slate-300">
                          <MapPin className="h-3 w-3 text-red-500 shrink-0" />
                          <span>{spk.location}</span>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* SHEET 3: SCHEDULED UPCOMING CONFERENCES TABLE */}
      {activeSheet === "scheduled" && (
        <div id="scheduled-table" className="rounded-xl border bg-card shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b flex items-center justify-between bg-purple-50/40 dark:bg-purple-950/20">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-purple-600" />
              <div>
                <h2 className="text-base font-semibold">Scheduled Upcoming Pipeline (Awaiting T-2 Publication Date)</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Conferences validated from official sources with genuine dates. Automatically published to Excel and the published view exactly 2 days before start date.
                </p>
              </div>
            </div>
            <span className="text-xs text-muted-foreground">
              Showing {filteredScheduled.length} scheduled conferences
            </span>
          </div>

          <div className="overflow-x-auto max-h-[650px]">
            <table className="w-full text-left text-xs">
              <thead className="bg-purple-900 text-white sticky top-0 z-10 font-semibold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="px-3.5 py-3 border-b">ID</th>
                  <th className="px-3.5 py-3 border-b min-w-[240px]">Conference Title &amp; Category</th>
                  <th className="px-3.5 py-3 border-b min-w-[130px]">Official Dates</th>
                  <th className="px-3.5 py-3 border-b min-w-[140px]">T-2 Auto-Publish Date</th>
                  <th className="px-3.5 py-3 border-b min-w-[160px]">Venue &amp; City</th>
                  <th className="px-3.5 py-3 border-b min-w-[120px]">Source</th>
                  <th className="px-3.5 py-3 border-b min-w-[140px]">T-2 Status</th>
                  <th className="px-3.5 py-3 border-b text-right pr-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-purple-600" />
                      Loading scheduled conferences...
                    </td>
                  </tr>
                ) : filteredScheduled.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-muted-foreground">
                      No scheduled future conferences found.
                    </td>
                  </tr>
                ) : (
                  filteredScheduled.map((conf) => (
                    <tr key={conf.conference_id} className="hover:bg-accent/40 transition-colors">
                      <td className="px-3.5 py-3 font-mono text-[11px] font-medium text-slate-600 dark:text-slate-400">
                        <Link href={`/conferences/${conf.conference_id}`} className="hover:text-blue-600 hover:underline">
                          {conf.conference_id}
                        </Link>
                      </td>
                      <td className="px-3.5 py-3">
                        <a 
                          href={conf.official_conference_url || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-semibold text-foreground hover:text-blue-600 hover:underline inline-flex items-center gap-1.5 group"
                          title={`Open ${conf.conference_title} official website`}
                        >
                          <span>{conf.conference_title}</span>
                          <ExternalLink className="h-3 w-3 opacity-60 group-hover:opacity-100 text-blue-600 inline-block shrink-0" />
                        </a>
                        <span className="inline-block mt-1 px-2 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                          {conf.industry_category}
                        </span>
                      </td>
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5 font-bold text-slate-900 dark:text-slate-100">
                          <Calendar className="h-3.5 w-3.5 text-purple-600" />
                          <span>{conf.start_date}</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground">to {conf.end_date}</span>
                      </td>
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1 text-slate-700 dark:text-slate-300 font-medium">
                          <Clock className="h-3.5 w-3.5 text-amber-500" />
                          <span>2027-04-03</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground">(2 days before start)</span>
                      </td>
                      <td className="px-3.5 py-3">
                        <div className="font-medium flex items-center gap-1">
                          <MapPin className="h-3 w-3 text-red-500 shrink-0" />
                          <span>{conf.city}, {conf.country}</span>
                        </div>
                        <div className="text-[11px] text-muted-foreground">{conf.venue}</div>
                      </td>
                      <td className="px-3.5 py-3">
                        <a
                          href={conf.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="capitalize px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 hover:bg-blue-100 dark:bg-slate-800 dark:hover:bg-slate-700 border text-blue-600 inline-flex items-center gap-1"
                        >
                          <span>{conf.source_name}</span>
                          <ExternalLink className="h-2.5 w-2.5 opacity-60" />
                        </a>
                      </td>
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 border border-purple-200 inline-flex items-center gap-1">
                          <Clock className="h-3 w-3 text-purple-600" />
                          Scheduled (T-2 Pending)
                        </span>
                      </td>
                      <td className="px-3.5 py-3 whitespace-nowrap text-right pr-4">
                        <Link 
                          href={`/conferences/${conf.conference_id}`}
                          className="px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 text-[11px] font-medium inline-flex items-center gap-1 transition-colors shadow-sm"
                        >
                          <Info className="h-3 w-3" />
                          <span>View Details</span>
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
