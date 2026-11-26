import React, { useState, useEffect } from 'react';
import { SheetMetadata, SheetDataResponse } from '../types';
import { api } from '../services/api';
import { Search, ChevronLeft, ChevronRight, Download, Filter, FileSpreadsheet, Loader2, ArrowUpDown } from 'lucide-react';

interface ExcelExplorerProps {
  sheets: SheetMetadata[];
}

export const ExcelExplorer: React.FC<ExcelExplorerProps> = ({ sheets }) => {
  const [selectedSheet, setSelectedSheet] = useState<string>('Qualified Leads');
  const [data, setData] = useState<SheetDataResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [search, setSearch] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const [limit, setLimit] = useState<number>(50);
  const [sortCol, setSortCol] = useState<string | undefined>(undefined);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  useEffect(() => {
    loadData();
  }, [selectedSheet, page, limit, sortCol, sortDir]);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await api.getSheetData(selectedSheet, page, limit, search, sortCol, sortDir);
      setData(res);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadData();
  };

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
    setPage(1);
  };

  const exportCSV = () => {
    if (!data || !data.rows.length) return;
    const headers = data.columns.join(',');
    const rows = data.rows.map(row => 
      data.columns.map(col => `"${String(row[col] ?? '').replace(/"/g, '""')}"`).join(',')
    );
    const csvContent = "data:text/csv;charset=utf-8," + [headers, ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${selectedSheet}_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const currentSheetMeta = sheets.find(s => s.name === selectedSheet);

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 p-5 shadow-sm">
      {/* Top Controls: Sheet Selector */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-5 border-b border-slate-700/60">
        <div>
          <div className="flex items-center space-x-2">
            <FileSpreadsheet className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-semibold text-white">Workbook Sheets Explorer</h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            {currentSheetMeta?.description || 'Browse live data from workbook tabs'}
          </p>
        </div>

        {/* Sheet Pill Selector */}
        <div className="flex items-center space-x-2 overflow-x-auto max-w-full pb-1">
          <select
            value={selectedSheet}
            onChange={(e) => {
              setSelectedSheet(e.target.value);
              setPage(1);
              setSearch('');
            }}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs font-medium text-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            {sheets.map(s => (
              <option key={s.name} value={s.name}>
                {s.name} ({s.total_rows} rows)
              </option>
            ))}
          </select>

          <button
            onClick={exportCSV}
            className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-white transition-all shadow-sm"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {/* Search & Pagination Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 py-4">
        <form onSubmit={handleSearchSubmit} className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder={`Search across ${selectedSheet}...`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </form>

        <div className="flex items-center space-x-3 text-xs text-slate-400">
          <span>Rows per page:</span>
          <select
            value={limit}
            onChange={(e) => { setLimit(Number(e.target.value)); setPage(1); }}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none"
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>

          <span>
            {data ? `${(page - 1) * limit + 1}-${Math.min(page * limit, data.filtered_rows)} of ${data.filtered_rows}` : '0 of 0'}
          </span>

          <div className="flex items-center space-x-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:hover:bg-slate-700 text-white"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage(p => Math.min(data?.total_pages || 1, p + 1))}
              disabled={!data || page >= data.total_pages}
              className="p-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:hover:bg-slate-700 text-white"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Data Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-700/80 max-h-[580px] overflow-y-auto">
        {loading ? (
          <div className="py-24 flex flex-col items-center justify-center space-y-3">
            <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
            <p className="text-xs text-slate-400">Loading {selectedSheet} data directly from Excel...</p>
          </div>
        ) : !data || data.rows.length === 0 ? (
          <div className="py-20 text-center text-slate-500 text-xs">
            No rows match the search query or this sheet is currently empty.
          </div>
        ) : (
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-900/90 sticky top-0 z-10 text-[11px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700">
              <tr>
                <th className="py-3 px-3 w-10 text-center text-slate-500">#</th>
                {data.columns.map((col) => (
                  <th
                    key={col}
                    onClick={() => handleSort(col)}
                    className="py-3 px-3 cursor-pointer hover:text-white select-none whitespace-nowrap"
                  >
                    <div className="flex items-center space-x-1">
                      <span>{col}</span>
                      <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {data.rows.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-750/50 hover:bg-slate-700/30 transition-colors">
                  <td className="py-2.5 px-3 text-center text-slate-500 font-mono">
                    {(page - 1) * limit + idx + 1}
                  </td>
                  {data.columns.map((col) => {
                    const val = row[col];
                    const strVal = String(val ?? '');
                    
                    // Formatting badges for status columns
                    const isStatus = col.toLowerCase().includes('status');
                    const isScore = col.toLowerCase().includes('score');
                    const isEmail = col.toLowerCase().includes('email');
                    const isUrl = strVal.startsWith('http');

                    return (
                      <td key={col} className="py-2.5 px-3 truncate max-w-xs">
                        {isStatus ? (
                          <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-medium ${
                            strVal.toLowerCase().includes('verified') || strVal.toLowerCase().includes('high') || strVal.toLowerCase().includes('sent')
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : strVal.toLowerCase().includes('pending') || strVal.toLowerCase().includes('moderate')
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                              : 'bg-slate-700/50 text-slate-400'
                          }`}>
                            {strVal || '-'}
                          </span>
                        ) : isScore && !isNaN(Number(val)) && val !== '' ? (
                          <span className="font-semibold text-emerald-400">{Number(val).toFixed(1)}</span>
                        ) : isUrl ? (
                          <a href={strVal} target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline truncate block">
                            {strVal}
                          </a>
                        ) : isEmail ? (
                          <span className="font-mono text-slate-200">{strVal || '-'}</span>
                        ) : (
                          <span>{strVal || '-'}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
