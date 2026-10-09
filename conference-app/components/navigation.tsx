'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { 
  Building2, 
  FileSpreadsheet, 
  BellRing, 
  Globe2, 
  Bot, 
  ExternalLink,
  CalendarDays
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';

const navigation = [
  { name: 'USA Conferences', href: '/', icon: CalendarDays },
  { name: 'Excel Published Sheet', href: '/#excel-table', icon: FileSpreadsheet },
];

const sources = [
  { name: '10times', url: 'https://10times.com/usa/conferences' },
  { name: 'Luma', url: 'https://lu.ma/discover' },
  { name: 'Eventbrite', url: 'https://www.eventbrite.com/d/united-states/conferences/' },
  { name: 'Meetup', url: 'https://www.meetup.com/find/?keywords=conference&location=us' },
  { name: 'Cvent', url: 'https://www.cvent.com/events' },
  { name: 'Events In America', url: 'https://eventsinamerica.com' },
];

export function Navigation() {
  const pathname = usePathname();

  return (
    <div className="flex h-screen w-64 flex-col border-r bg-card shadow-sm">
      <div className="flex h-16 items-center border-b px-6 gap-2">
        <Building2 className="h-6 w-6 text-blue-600" />
        <div className="flex flex-col">
          <span className="text-sm font-bold tracking-tight text-foreground">Conference Agent</span>
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">USA 24/7 Intelligence</span>
        </div>
      </div>

      <ScrollArea className="flex-1 px-3 py-4">
        <div className="space-y-4">
          <div>
            <p className="px-3 text-xs font-semibold text-muted-foreground tracking-wider uppercase mb-2">Main Navigation</p>
            <nav className="flex flex-col gap-1">
              {navigation.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href;
                return (
                  <Link key={item.name} href={item.href}>
                    <Button
                      variant={isActive ? 'secondary' : 'ghost'}
                      className={cn(
                        'w-full justify-start gap-3 text-sm font-medium',
                        isActive && 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300 font-semibold'
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      {item.name}
                    </Button>
                  </Link>
                );
              })}
            </nav>
          </div>

          <Separator />

          <div>
            <p className="px-3 text-xs font-semibold text-muted-foreground tracking-wider uppercase mb-2">6 Monitored Sources</p>
            <div className="flex flex-col gap-1">
              {sources.map((src) => (
                <a
                  key={src.name}
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Globe2 className="h-3.5 w-3.5 text-blue-500" />
                    {src.name}
                  </span>
                  <ExternalLink className="h-3 w-3 opacity-60" />
                </a>
              ))}
            </div>
          </div>

          <Separator />

          <div className="px-3 py-2 bg-slate-50 dark:bg-slate-900 rounded-lg border text-xs space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-foreground">
              <Bot className="h-4 w-4 text-emerald-500" />
              <span>AI & Automation Engine</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Continuous 24/7 scraping with Gemini validation. Excel publication occurs exactly 2 days before each conference.
            </p>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
