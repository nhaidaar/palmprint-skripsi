import { useCallback, useEffect, useRef, useState } from 'react'

import { AccessLog, apiJson, buildQuery } from '../lib/api'
import { emptyLogFilters, nextLogFilters } from '../lib/logFilters'

const PAGE_SIZE = 20

type LogPanelProps = {
  active: boolean
  refreshKey?: number
}

export function LogPanel({ active, refreshKey = 0 }: LogPanelProps) {
  const [filters, setFilters] = useState(emptyLogFilters)
  const [searchQ, setSearchQ] = useState(emptyLogFilters.q)
  const [rows, setRows] = useState<AccessLog[]>([])
  const [count, setCount] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const latestRequestRef = useRef(0)

  const loadLogs = useCallback(async () => {
    const requestId = ++latestRequestRef.current
    setBusy(true)
    setError('')
    try {
      const params = {
        limit: PAGE_SIZE,
        offset: (filters.page - 1) * PAGE_SIZE,
        q: filters.q,
        status: filters.status,
        start_date: filters.startDate,
        end_date: filters.endDate,
      }
      const [nextRows, nextCount] = await Promise.all([
        apiJson<AccessLog[]>(`/api/logs${buildQuery(params)}`),
        apiJson<{ count: number }>(`/api/logs/count${buildQuery(params)}`),
      ])
      if (requestId !== latestRequestRef.current) return
      setRows(nextRows)
      setCount(nextCount.count)
    } catch (err) {
      if (requestId === latestRequestRef.current) setError(err instanceof Error ? err.message : 'Failed to load logs')
    } finally {
      if (requestId === latestRequestRef.current) setBusy(false)
    }
  }, [filters])

  useEffect(() => {
    if (searchQ === filters.q) return
    const id = window.setTimeout(() => {
      setFilters((current) => nextLogFilters(current, { q: searchQ }))
    }, 300)
    return () => window.clearTimeout(id)
  }, [searchQ, filters.q])

  useEffect(() => {
    void loadLogs()
  }, [loadLogs, refreshKey])

  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  const filtersActive = Boolean(searchQ || filters.status || filters.startDate || filters.endDate)
  const exportHref = `/api/logs/export.xlsx${buildQuery({
    q: filters.q,
    status: filters.status,
    start_date: filters.startDate,
    end_date: filters.endDate,
  })}`

  return (
    <section className={`panel${active ? ' active' : ''}`} id="panel-log">
      <div className="log-header">
        <h2 className="log-title">Access log</h2>
        <div className="log-header-actions">
          <a className="btn btn-ghost btn-refresh" href={exportHref} download>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 2v8m0 0 3-3m-3 3L5 7M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Export Excel
          </a>
          <button className="btn btn-ghost btn-refresh" id="btnRefresh" type="button" onClick={() => void loadLogs()} disabled={busy}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M14 8A6 6 0 112 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M14 4v4h-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      <div className="log-filters" role="group" aria-label="Access log filters">
        <label className="log-filter-field log-filter-search">
          <span className="log-filter-label">Search</span>
          <span className="log-search-wrap">
            <svg className="log-search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              className="field-input log-filter-input log-search-input"
              type="search"
              placeholder="Search name, NIM, or description"
              value={searchQ}
              onChange={(event) => setSearchQ(event.target.value)}
            />
          </span>
        </label>
        <label className="log-filter-field">
          <span className="log-filter-label">Status</span>
          <select
            className="field-input log-filter-input"
            value={filters.status}
            onChange={(event) => setFilters((current) => nextLogFilters(current, { status: event.target.value as typeof filters.status }))}
          >
            <option value="">All statuses</option>
            <option value="ALLOWED">Allowed</option>
            <option value="DENIED">Denied</option>
          </select>
        </label>
        <label className="log-filter-field">
          <span className="log-filter-label">From</span>
          <input
            className="field-input log-filter-input"
            type="date"
            value={filters.startDate}
            onChange={(event) => setFilters((current) => nextLogFilters(current, { startDate: event.target.value }))}
          />
        </label>
        <label className="log-filter-field">
          <span className="log-filter-label">To</span>
          <input
            className="field-input log-filter-input"
            type="date"
            value={filters.endDate}
            onChange={(event) => setFilters((current) => nextLogFilters(current, { endDate: event.target.value }))}
          />
        </label>
        <button
          className="btn btn-ghost log-filter-clear"
          type="button"
          disabled={!filtersActive}
          onClick={() => { setSearchQ(''); setFilters(emptyLogFilters) }}
        >
          Clear
        </button>
      </div>
      <p className="log-filter-hint">
        <span className="log-filter-hint-dot" aria-hidden="true" />
        Results and Excel export use the same active filters
      </p>

      {error && <div className="log-empty">{error}</div>}

      <div className="log-table-wrap">
        <table className="log-table">
          <thead>
            <tr><th>Time</th><th>Name</th><th>Status</th><th>Match %</th><th>Duration</th><th>Description</th></tr>
          </thead>
          <tbody id="logTableBody">
            {busy ? (
              <tr className="log-empty-row"><td colSpan={6}><div className="log-empty"><span>Loading access log…</span></div></td></tr>
            ) : rows.length === 0 ? (
              <tr className="log-empty-row"><td colSpan={6}><div className="log-empty"><span>No access attempts recorded yet</span></div></td></tr>
            ) : rows.map((row) => (
              <tr key={row.id}>
                <td>{row.timestamp}</td>
                <td>{row.matched_name || 'Unknown'}</td>
                <td><span className={`log-status ${row.status === 'ALLOWED' ? 'allowed' : 'denied'}`}>{row.status}</span></td>
                <td>{Math.round(row.similarity * 100)}%</td>
                <td>{row.duration_ms == null ? '—' : `${row.duration_ms} ms`}</td>
                <td>{row.description ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="log-pagination" id="logPagination">
        <button className="btn btn-ghost btn-pag" id="btnLogPrev" type="button" disabled={filters.page <= 1} onClick={() => setFilters((current) => ({ ...current, page: current.page - 1 }))}>Prev</button>
        <span className="pag-info" id="pagInfo">Page {filters.page} of {pages}</span>
        <button className="btn btn-ghost btn-pag" id="btnLogNext" type="button" disabled={filters.page >= pages} onClick={() => setFilters((current) => ({ ...current, page: current.page + 1 }))}>Next</button>
      </div>
    </section>
  )
}
