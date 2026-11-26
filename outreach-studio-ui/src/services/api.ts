import { OverviewMetrics, SheetMetadata, SheetDataResponse, Lead, GeneratedEmail, ScheduleItem, ReplyItem, BounceItem } from '../types';

const BASE_URL = '/api/studio';

export const api = {
  // 1. Overview
  async getOverview(): Promise<{ metrics: OverviewMetrics; sheet_counts: Record<string, number> }> {
    const res = await fetch(`${BASE_URL}/overview`);
    if (!res.ok) throw new Error('Failed to fetch overview metrics');
    return res.json();
  },

  // 2. Sheets
  async getSheets(): Promise<SheetMetadata[]> {
    const res = await fetch(`${BASE_URL}/sheets`);
    if (!res.ok) throw new Error('Failed to fetch sheets');
    const data = await res.json();
    return data.sheets || [];
  },

  async getSheetData(
    sheet: string,
    page: number = 1,
    limit: number = 50,
    search: string = '',
    sort_col?: string,
    sort_dir: string = 'asc'
  ): Promise<SheetDataResponse> {
    const params = new URLSearchParams({
      sheet,
      page: page.toString(),
      limit: limit.toString(),
      search: search || '',
      sort_dir
    });
    if (sort_col) params.append('sort_col', sort_col);

    const res = await fetch(`${BASE_URL}/sheet-data?${params.toString()}`);
    if (!res.ok) throw new Error(`Failed to load sheet data for ${sheet}`);
    return res.json();
  },

  // 3. Leads
  async getLeads(category: string = 'all', status?: string, upcomingOnly: boolean = true, search?: string): Promise<Lead[]> {
    const params = new URLSearchParams({
      category,
      upcoming_only: upcomingOnly ? 'true' : 'false'
    });
    if (status && status !== 'all') params.append('status', status);
    if (search) params.append('search', search);

    const res = await fetch(`${BASE_URL}/leads?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch leads');
    const data = await res.json();
    return data.leads || [];
  },

  // 4. Generate Personalized Email
  async generateEmail(payload: {
    contact_name: string;
    job_title: string;
    company_name: string;
    conference_name: string;
    contact_type: string;
    industry: string;
    use_llm: boolean;
    custom_instructions?: string;
  }): Promise<GeneratedEmail> {
    const res = await fetch(`${BASE_URL}/generate-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to generate personalized email');
    return res.json();
  },

  // 5. Send Test Email
  async sendTestEmail(payload: {
    recipient_email: string;
    subject: string;
    body: string;
    lead_name?: string;
    company_name?: string;
  }): Promise<{ status: string; message: string; message_id?: string }> {
    const res = await fetch(`${BASE_URL}/send-test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Test email failed');
    }
    return res.json();
  },

  // 6. Send Actual Outreach
  async sendOutreach(payload: {
    email: string;
    subject?: string;
    body?: string;
    category?: string;
    dry_run?: boolean;
  }): Promise<any> {
    const res = await fetch(`${BASE_URL}/send-outreach`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Outreach dispatch failed');
    }
    return res.json();
  },

  // 7. Scheduling
  async scheduleOutreach(payload: {
    leads: Lead[];
    scheduled_time: string;
    custom_subject?: string;
    custom_body?: string;
    notes?: string;
  }): Promise<any> {
    const res = await fetch(`${BASE_URL}/schedule-outreach`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to schedule outreach');
    return res.json();
  },

  async getSchedules(): Promise<ScheduleItem[]> {
    const res = await fetch(`${BASE_URL}/schedules`);
    if (!res.ok) throw new Error('Failed to fetch schedules');
    const data = await res.json();
    return data.schedules || [];
  },

  async cancelSchedule(scheduleId: string): Promise<any> {
    const res = await fetch(`${BASE_URL}/cancel-schedule`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule_id: scheduleId })
    });
    if (!res.ok) throw new Error('Failed to cancel schedule');
    return res.json();
  },

  // 8. Replies and Bounces
  async getReplies(): Promise<ReplyItem[]> {
    const res = await fetch(`${BASE_URL}/replies`);
    if (!res.ok) throw new Error('Failed to fetch replies');
    const data = await res.json();
    return data.replies || [];
  },

  async getBounces(): Promise<BounceItem[]> {
    const res = await fetch(`${BASE_URL}/bounces`);
    if (!res.ok) throw new Error('Failed to fetch bounces');
    const data = await res.json();
    return data.bounces || [];
  },

  // 9. Force Sync
  async syncExcel(): Promise<any> {
    const res = await fetch(`${BASE_URL}/sync-excel`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger Excel sync');
    return res.json();
  }
};
