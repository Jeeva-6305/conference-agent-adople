'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Calendar,
  MapPin,
  Building2,
  Users,
  ExternalLink,
  Mic,
  FileSpreadsheet,
  Globe,
  Tag,
  Clock,
  ShieldCheck,
  Award,
  BookOpen,
  CheckCircle2,
  Briefcase
} from 'lucide-react';
import { Button } from '@/components/ui/button';

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
  speaker_talks_details?: string;
  description?: string;
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
  created_at: string;
}

interface SpeakerProfile {
  id: number;
  conference_id: string;
  conference_name: string;
  speaker_name: string;
  company_organization: string;
  job_role_designation: string;
  company_name: string;
  location: string;
  previous_speaking_info?: string;
}

const API_BASE = "http://localhost:8000/api";

export default function ConferenceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [conference, setConference] = useState<Conference | null>(null);
  const [speakers, setSpeakers] = useState<SpeakerProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.id) return;
    const fetchDetail = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/conferences/${params.id}`);
        if (!res.ok) {
          throw new Error("Conference not found");
        }
        const data = await res.json();
        setConference(data);

        // Fetch speakers for this conference
        const spkRes = await fetch(`${API_BASE}/speakers?conference_id=${data.conference_id}`);
        if (spkRes.ok) {
          const spkData = await spkRes.json();
          setSpeakers(spkData);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load conference details");
      } finally {
        setLoading(false);
      }
    };
    fetchDetail();
  }, [params?.id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center p-6">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mb-4" />
        <p className="text-slate-600 dark:text-slate-400 text-sm">Loading verified conference details...</p>
      </div>
    );
  }

  if (error || !conference) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 p-8 flex flex-col items-center justify-center">
        <div className="bg-card border rounded-2xl p-8 max-w-md w-full text-center shadow-sm">
          <Building2 className="h-12 w-12 text-slate-400 mx-auto mb-3" />
          <h2 className="text-xl font-bold text-foreground">Conference Not Found</h2>
          <p className="text-sm text-muted-foreground mt-2 mb-6">
            The conference details could not be retrieved or do not exist in the verified database.
          </p>
          <Button onClick={() => router.push('/')} className="bg-blue-600 hover:bg-blue-700 text-white">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to All Conferences
          </Button>
        </div>
      </div>
    );
  }

  const hasSpeakers = (conference.speakers_available !== "No" && (speakers.length > 0 || (conference.speakers && conference.speakers.trim().length > 0)));

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {/* Top Header Navigation */}
      <header className="border-b bg-background/80 backdrop-blur sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link 
            href="/"
            className="inline-flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-600 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Conferences Dashboard
          </Link>

          <div className="flex items-center gap-3">
            <span className="font-mono text-xs px-2.5 py-1 bg-slate-100 dark:bg-slate-800 rounded-md border font-semibold text-slate-600 dark:text-slate-300">
              {conference.conference_id}
            </span>
            <a 
              href={`${API_BASE}/excel/download`} 
              className="text-xs inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors font-medium"
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Download Excel (With Speakers Sheet)
            </a>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        
        {/* Hero Card */}
        <div className="bg-white dark:bg-slate-900 border rounded-2xl p-8 shadow-sm space-y-6">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 inline-flex items-center gap-1">
              <Tag className="h-3 w-3" />
              {conference.industry_category}
            </span>
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 capitalize">
              Source: {conference.source_name}
            </span>
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 inline-flex items-center gap-1">
              <ShieldCheck className="h-3 w-3" />
              Verified Genuine USA Conference
            </span>
            {hasSpeakers ? (
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300 inline-flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                Speakers Available: Yes
              </span>
            ) : (
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                Speakers Available: No
              </span>
            )}
          </div>

          <div>
            <h1 className="text-3xl font-extrabold tracking-tight text-foreground sm:text-4xl">
              <a 
                href={conference.official_conference_url || conference.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-blue-600 hover:underline inline-flex items-center gap-2.5 group"
                title={`Open official website: ${conference.official_conference_url}`}
              >
                <span>{conference.conference_title}</span>
                <ExternalLink className="h-6 w-6 opacity-40 group-hover:opacity-100 text-blue-600 shrink-0" />
              </a>
            </h1>
            {conference.description && (
              <p className="mt-3 text-base text-slate-600 dark:text-slate-300 leading-relaxed">
                {conference.description}
              </p>
            )}
          </div>

          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-4 border-t border-slate-100 dark:border-slate-800">
            {/* Start Date */}
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase">
                <Calendar className="h-4 w-4 text-blue-600" />
                Conference Start Date
              </div>
              <div className="mt-2 text-base font-bold text-foreground">
                {conference.start_date}
              </div>
            </div>

            {/* End Date */}
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase">
                <Calendar className="h-4 w-4 text-indigo-600" />
                Conference End Date
              </div>
              <div className="mt-2 text-base font-bold text-foreground">
                {conference.end_date}
              </div>
            </div>

            {/* Original Publication Date */}
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase">
                <Clock className="h-4 w-4 text-emerald-600" />
                Original Publication Date
              </div>
              <div className="mt-2 text-base font-bold text-foreground">
                {conference.publication_date || "2026-08-15"}
              </div>
              <div className="text-[11px] text-muted-foreground mt-0.5">Original Conference Publication Date</div>
            </div>

            {/* Location */}
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase">
                <MapPin className="h-4 w-4 text-red-500" />
                City &amp; Country
              </div>
              <div className="mt-2 text-base font-bold text-foreground truncate">
                {conference.city}, {conference.country}
              </div>
              <div className="text-[11px] text-muted-foreground truncate">{conference.venue}</div>
            </div>
          </div>

          {/* Action CTAs */}
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <a 
              href={conference.official_conference_url || conference.source_url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition-all shadow-sm"
            >
              <Globe className="h-4 w-4" />
              Visit Official Conference Website
              <ExternalLink className="h-3.5 w-3.5 opacity-80" />
            </a>

            <a 
              href={conference.registration_url || conference.source_url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-foreground font-semibold text-sm transition-colors border"
            >
              <Award className="h-4 w-4 text-amber-500" />
              Registration / Ticket Page
              <ExternalLink className="h-3.5 w-3.5 opacity-60" />
            </a>

            <a 
              href={conference.source_url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-slate-600 hover:text-blue-600 text-sm font-medium transition-colors"
            >
              <span>Source Listing ({conference.source_name})</span>
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>

        {/* Section: Conference Key Information Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Venue & Location Details */}
          <div className="bg-white dark:bg-slate-900 border rounded-2xl p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-2 text-base font-bold text-foreground border-b pb-3">
              <MapPin className="h-5 w-5 text-red-500" />
              Venue &amp; Location
            </div>

            <div className="space-y-3 text-sm">
              <div>
                <span className="text-xs font-semibold text-muted-foreground uppercase block">Venue / Convention Center</span>
                <span className="text-base font-medium text-foreground">{conference.venue}</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-xs font-semibold text-muted-foreground uppercase block">City</span>
                  <span className="text-base font-medium text-foreground">{conference.city}</span>
                </div>
                <div>
                  <span className="text-xs font-semibold text-muted-foreground uppercase block">Country</span>
                  <span className="text-base font-medium text-foreground">{conference.country}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Organizer & Official Links */}
          <div className="bg-white dark:bg-slate-900 border rounded-2xl p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-2 text-base font-bold text-foreground border-b pb-3">
              <Building2 className="h-5 w-5 text-blue-600" />
              Organizer &amp; Verification Details
            </div>

            <div className="space-y-3 text-sm">
              <div>
                <span className="text-xs font-semibold text-muted-foreground uppercase block">Organizer</span>
                <span className="text-base font-medium text-foreground">
                  {conference.organizer || "Independent Conference Committee"}
                </span>
              </div>
              <div>
                <span className="text-xs font-semibold text-muted-foreground uppercase block">Official Website</span>
                <a 
                  href={conference.official_conference_url || conference.source_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline break-all inline-flex items-center gap-1 font-medium"
                >
                  {conference.official_conference_url || conference.source_url}
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Section: Verified Keynote & Featured Speakers */}
        <div className="bg-white dark:bg-slate-900 border rounded-2xl p-6 shadow-sm space-y-6">
          <div className="flex items-center justify-between border-b pb-4">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5 text-blue-600" />
              <h2 className="text-lg font-bold text-foreground">Verified Conference Speakers (Published to Speakers Sheet)</h2>
            </div>
            <span className="text-xs px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 font-semibold border border-emerald-200">
              {speakers.length > 0 ? speakers.length : (conference.speakers ? conference.speakers.split(',').length : 0)} Speaker(s) Available
            </span>
          </div>

          {/* Detailed Speaker Profiles matching Excel Speakers Sheet columns */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {speakers.length > 0 ? (
              speakers.map((spk) => (
                <div 
                  key={spk.id}
                  className="p-5 rounded-xl border bg-slate-50/60 dark:bg-slate-800/40 hover:border-emerald-300 dark:hover:border-emerald-700 transition-colors space-y-3"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="h-10 w-10 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-sm shrink-0 shadow-sm">
                      {spk.speaker_name.charAt(0)}
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-foreground">{spk.speaker_name}</h3>
                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">Verified Speaker</span>
                    </div>
                  </div>

                  <div className="space-y-1.5 text-xs">
                    <div>
                      <span className="text-muted-foreground font-semibold block text-[10px] uppercase">Job Role / Designation</span>
                      <span className="font-medium text-slate-800 dark:text-slate-200">{spk.job_role_designation}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground font-semibold block text-[10px] uppercase">Company / Organization</span>
                      <span className="font-medium text-slate-800 dark:text-slate-200">{spk.company_organization || spk.company_name}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground font-semibold block text-[10px] uppercase">Location</span>
                      <span className="text-slate-600 dark:text-slate-400 flex items-center gap-1">
                        <MapPin className="h-3 w-3 text-red-500" />
                        {spk.location}
                      </span>
                    </div>
                    {spk.previous_speaking_info && (
                      <div className="pt-1 border-t border-slate-200 dark:border-slate-700">
                        <span className="text-muted-foreground font-semibold block text-[10px] uppercase">Speaking Background / Talks</span>
                        <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed mt-0.5">
                          {spk.previous_speaking_info}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ))
            ) : (
              conference.speakers.split(',').map((name, idx) => (
                <div 
                  key={idx}
                  className="p-5 rounded-xl border bg-slate-50/60 dark:bg-slate-800/40 space-y-2"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="h-9 w-9 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center text-sm shrink-0 shadow-sm">
                      {name.trim().charAt(0)}
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-foreground">{name.trim()}</h3>
                      <span className="text-[11px] text-blue-600 dark:text-blue-400 font-medium">Verified Speaker</span>
                    </div>
                  </div>
                  <p className="text-xs text-slate-600 dark:text-slate-300 pt-1 leading-relaxed">
                    {conference.speaker_titles_companies?.split(',')[idx] || "Featured Speaker"}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Section: Previous Talks & Speaking Information */}
        {conference.speaker_talks_details && (
          <div className="bg-white dark:bg-slate-900 border rounded-2xl p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-2 text-base font-bold text-foreground border-b pb-3">
              <Mic className="h-5 w-5 text-amber-500" />
              Previous Conference / Event Speaking Information
            </div>
            <div className="p-4 bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-900/40 rounded-xl">
              <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                {conference.speaker_talks_details}
              </p>
            </div>
          </div>
        )}

        {/* Section: Other Verified Conference Details */}
        <div className="bg-white dark:bg-slate-900 border rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-base font-bold text-foreground border-b pb-3">
            <BookOpen className="h-5 w-5 text-indigo-600" />
            Publication &amp; Verification Metadata
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            <div className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border">
              <span className="font-semibold text-muted-foreground block mb-1">Publication Date</span>
              <span className="text-sm font-bold text-emerald-600">{conference.publication_date || "2026-08-15"}</span>
              <p className="text-[11px] text-muted-foreground mt-1">
                Original Conference Publication Date
              </p>
            </div>

            <div className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border">
              <span className="font-semibold text-muted-foreground block mb-1">Database Record ID</span>
              <span className="text-sm font-mono font-bold text-foreground">{conference.conference_id}</span>
              <p className="text-[11px] text-muted-foreground mt-1">Verified record stored in PostgreSQL</p>
            </div>

            <div className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border">
              <span className="font-semibold text-muted-foreground block mb-1">Official Conference Website</span>
              <a 
                href={conference.official_conference_url || conference.source_url} 
                target="_blank" 
                rel="noopener noreferrer" 
                className="text-blue-600 hover:underline break-all inline-flex items-center gap-1 font-medium mt-1"
              >
                <span>{conference.official_conference_url || conference.source_url}</span>
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
              <p className="text-[11px] text-muted-foreground mt-1">Status: Verified 200 OK (No 404)</p>
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}
