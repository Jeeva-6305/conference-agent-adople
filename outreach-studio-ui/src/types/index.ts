export interface SheetMetadata {
  name: string;
  total_rows: number;
  columns: string[];
  description: string;
  category: 'Outreach' | 'Scoring' | 'Discovery';
}

export interface OverviewMetrics {
  qualified_leads_total: number;
  qualified_leads_upcoming: number;
  non_qualified_leads_total: number;
  non_qualified_leads_upcoming: number;
  outreach_pending: number;
  outreach_sent: number;
  replies_captured: number;
  bounces_captured: number;
  active_threads: number;
  upcoming_run_id: string;
}

export interface SheetDataResponse {
  sheet: string;
  columns: string[];
  total_rows: number;
  filtered_rows: number;
  page: number;
  limit: number;
  total_pages: number;
  rows: Record<string, any>[];
}

export interface Lead {
  id: string;
  is_qualified: boolean;
  rank: number | string;
  overall_score: number;
  qualification_status: string;
  company_name: string;
  company_domain: string;
  conference_name: string;
  conference_id: string;
  contact_type: string;
  contact_name: string;
  job_title: string;
  professional_email: string;
  email_status: string;
  personal_linkedin_url: string;
  primary_industry: string;
  headcount_tier: string;
  outreach_status: string;
  reply_status: string;
  received_reply: string;
  reply_sentiment: string;
  thread_id: string;
  send_message: string;
  evaluated_at: string;
  sheet_source: string;
}

export interface GeneratedEmail {
  status: string;
  source: string;
  subject: string;
  body: string;
  template_file: string;
  model?: string;
  note?: string;
}

export interface ScheduleItem {
  id: string;
  created_at: string;
  scheduled_time: string;
  lead_count: number;
  leads: Lead[];
  custom_subject?: string;
  custom_body?: string;
  notes: string;
  status: 'scheduled' | 'completed' | 'cancelled';
  cancelled_at?: string;
}

export interface ReplyItem {
  id: string;
  speaker_name: string;
  company_name: string;
  job_title: string;
  conference_name: string;
  email: string;
  reply_status: string;
  reply_sentiment: string;
  received_reply: string;
  send_message: string;
  thread_id: string;
  reply_received_at: string;
}

export interface BounceItem {
  id: string;
  message_id: string;
  status: string;
  action_taken: string;
  detected_at: string;
}
