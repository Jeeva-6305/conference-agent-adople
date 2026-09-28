'use client';

import { useState, useEffect } from 'react';
import { 
  Building2, 
  Search, 
  Download, 
  CheckCircle2, 
  Clock, 
  FileSpreadsheet, 
  ExternalLink, 
  RefreshCw,
  Sparkles,
  MapPin,
  Calendar,
  Users,
  ShieldCheck
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

const API_BASE = "http://localhost:8000/api";

export default function ConferencesDashboard() {
  const [conferences, setConferences] = useState<Conference[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [publishedFilter, setPublishedFilter] = useState("all");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const fetchConferences = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/conferences`);
      if (res.ok) {
        const data = await res.json();
        setConferences(data);
      } else {
        throw new Error("Failed to fetch from backend");
      }
    } catch (err) {
      console.warn("Backend not yet connected or offline.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConferences();
    // Poll every 30 seconds for live continuous updates
    const interval = setInterval(fetchConferences, 30000);
    return () => clearInterval(interval);
  }, []);

  const triggerScrape = async () => {
    setActionLoading(true);
    setStatusMessage("Triggering 24/7 web scraper & Gemini AI validation across 6 sources...");
    try {
      const res = await fetch(`${API_BASE}/trigger/scrape`, { method: "POST" });
      if (res.ok) {
        setStatusMessage("✅ Scraping cycle running. Polling for newly extracted conferences...");
        setTimeout(fetchConferences, 4000);
      }
    } catch (e) {
      setStatusMessage("Could not contact backend at http://localhost:8000");
    } finally {
      setActionLoading(false);
      setTimeout(() => setStatusMessage(null), 6000);
    }
  };

  const triggerPublish = async () => {
    setActionLoading(true);
    setStatusMessage("Checking for conferences starting in exactly 2 days to publish to Excel...");
    try {
      const res = await fetch(`${API_BASE}/trigger/publish`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setStatusMessage(`✅ Publication check complete! Published: ${data.published_count} conference(s).`);
        fetchConferences();
      }
    } catch (e) {
      setStatusMessage("Could not contact backend at http://localhost:8000");
    } finally {
      setActionLoading(false);
      setTimeout(() => setStatusMessage(null), 6000);
    }
  };

  const filteredConferences = conferences.filter(c => {
    const matchesSearch = 
      (c.conference_title || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.speakers || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.city || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.venue || '').toLowerCase().includes(search.toLowerCase());

    const matchesSource = sourceFilter === "all" || c.source_name.toLowerCase().includes(sourceFilter.toLowerCase());
    const matchesPublished = 
      publishedFilter === "all" ? true :
      publishedFilter === "published" ? c.is_published_to_excel :
      !c.is_published_to_excel;

    return matchesSearch && matchesSource && matchesPublished;
  });

  const totalPublished = conferences.filter(c => c.is_published_to_excel).length;

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
            Autonomous 24/7 web scraping from 6 websites with Gemini AI validation. Exactly 2 days before each event, verified details are published to the Excel sheet.
          </p>
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
            Trigger 24/7 Scraper
          </Button>

          <Button 
            variant="outline" 
            size="sm"
            onClick={triggerPublish}
            disabled={actionLoading}
            className="flex items-center gap-2 border-emerald-200 hover:bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:text-emerald-300"
          >
            <Clock className="h-4 w-4" />
            Run 2-Day Excel Check
          </Button>

          <a href={`${API_BASE}/excel/download`} target="_blank" rel="noopener noreferrer">
            <Button size="sm" className="bg-blue-600 hover:bg-blue-700 text-white flex items-center gap-2">
              <Download className="h-4 w-4" />
              Download Excel (.xlsx)
            </Button>
          </a>
        </div>
      </div>

      {statusMessage && (
        <div className="p-3 bg-blue-50 border border-blue-200 text-blue-800 rounded-lg text-sm flex items-center gap-2 shadow-sm animate-fade-in">
          <Sparkles className="h-4 w-4 text-blue-600" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* KPI Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="p-5 bg-card border rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Total Real Conferences</span>
            <Building2 className="h-5 w-5 text-blue-600" />
          </div>
          <div className="mt-3 text-2xl font-bold">{conferences.length}</div>
          <p className="text-xs text-muted-foreground mt-1">Genuine USA events verified by Gemini AI</p>
        </div>

        <div className="p-5 bg-card border rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Published to Excel (T-2 Days)</span>
            <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
          </div>
          <div className="mt-3 text-2xl font-bold text-emerald-600">{totalPublished}</div>
          <p className="text-xs text-muted-foreground mt-1">Stored in Excel exactly 2 days prior</p>
        </div>

        <div className="p-5 bg-card border rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Pending Publication</span>
            <Clock className="h-5 w-5 text-amber-500" />
          </div>
          <div className="mt-3 text-2xl font-bold text-amber-600">{conferences.length - totalPublished}</div>
          <p className="text-xs text-muted-foreground mt-1">Scheduled for automatic T-2 day publication</p>
        </div>

        <div className="p-5 bg-card border rounded-xl shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Verified Sources</span>
            <ShieldCheck className="h-5 w-5 text-indigo-600" />
          </div>
          <div className="mt-3 text-2xl font-bold">6 Sites</div>
          <p className="text-xs text-muted-foreground mt-1">10times, Luma, Eventbrite, Meetup, Cvent, EIA</p>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-card p-4 rounded-xl border shadow-sm">
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by Title, Speaker, City, Venue..."
            className="pl-9 h-9 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5 w-full sm:w-auto">
          <select 
            className="h-9 px-3 text-xs rounded-md border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value="all">All Sources (6)</option>
            <option value="10times">10times</option>
            <option value="luma">Luma</option>
            <option value="eventbrite">Eventbrite</option>
            <option value="meetup">Meetup</option>
            <option value="cvent">Cvent</option>
            <option value="events_in_america">Events In America</option>
          </select>

          <select 
            className="h-9 px-3 text-xs rounded-md border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            value={publishedFilter}
            onChange={(e) => setPublishedFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="published">Published to Excel (T-2 Days)</option>
            <option value="pending">Pending (Awaiting T-2 Days)</option>
          </select>
        </div>
      </div>

      {/* Conference Table Matching 15 Excel Columns */}
      <div id="excel-table" className="rounded-xl border bg-card shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-blue-600" />
            <h2 className="text-base font-semibold">Genuine USA Conference Details & Excel Mirror Table</h2>
          </div>
          <span className="text-xs text-muted-foreground">
            Showing {filteredConferences.length} of {conferences.length} records (All 15 Excel Columns)
          </span>
        </div>

        <div className="overflow-x-auto max-h-[600px]">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-100 dark:bg-slate-900 sticky top-0 z-10 text-muted-foreground font-semibold uppercase tracking-wider">
              <tr>
                <th className="px-3.5 py-3 border-b">ID</th>
                <th className="px-3.5 py-3 border-b min-w-[240px]">Title & Category</th>
                <th className="px-3.5 py-3 border-b min-w-[120px]">Dates</th>
                <th className="px-3.5 py-3 border-b min-w-[200px]">Speakers & Companies</th>
                <th className="px-3.5 py-3 border-b min-w-[160px]">Venue & City</th>
                <th className="px-3.5 py-3 border-b">Country</th>
                <th className="px-3.5 py-3 border-b min-w-[140px]">Organizer</th>
                <th className="px-3.5 py-3 border-b">Source</th>
                <th className="px-3.5 py-3 border-b min-w-[140px]">Publication Date</th>
                <th className="px-3.5 py-3 border-b">Actions / Link</th>
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
                      {conf.conference_id}
                    </td>

                    {/* 2 & 3. Title & Industry */}
                    <td className="px-3.5 py-3">
                      <a 
                        href={conf.official_conference_url || conf.source_url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="font-semibold text-foreground hover:text-blue-600 hover:underline flex items-center gap-1.5"
                      >
                        <span>{conf.conference_title}</span>
                        <ExternalLink className="h-3 w-3 opacity-60 inline-block shrink-0" />
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

                    {/* 6 & 7. Speakers & Companies */}
                    <td className="px-3.5 py-3">
                      <div className="font-medium text-foreground flex items-center gap-1">
                        <Users className="h-3 w-3 text-slate-400" />
                        <span>{conf.speakers || "Keynote Speakers TBD"}</span>
                      </div>
                      {conf.speaker_titles_companies && (
                        <div className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">
                          {conf.speaker_titles_companies}
                        </div>
                      )}
                    </td>

                    {/* 8 & 9. Venue & City */}
                    <td className="px-3.5 py-3">
                      <div className="font-medium flex items-center gap-1">
                        <MapPin className="h-3 w-3 text-red-500" />
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

                    {/* 15. Publication Date (T-2 Days) */}
                    <td className="px-3.5 py-3 whitespace-nowrap">
                      {conf.is_published_to_excel ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                          <CheckCircle2 className="h-3 w-3" />
                          Published ({conf.publication_date})
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950 dark:text-amber-300">
                          <Clock className="h-3 w-3" />
                          Pending (T-2 days)
                        </span>
                      )}
                    </td>

                    {/* Action Links */}
                    <td className="px-3.5 py-3 whitespace-nowrap">
                      <a 
                        href={conf.registration_url || conf.source_url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="px-2.5 py-1 rounded bg-blue-50 text-blue-700 hover:bg-blue-100 dark:bg-blue-950 dark:text-blue-300 text-[11px] font-medium inline-flex items-center gap-1 transition-colors"
                      >
                        <span>View / Register</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
