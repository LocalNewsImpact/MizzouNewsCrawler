import React, { useEffect, useState, useCallback } from 'react'
import TelemetryQueue from './TelemetryQueue'

export default function Dashboard({ onOpen }){
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const fetchJson = useCallback(async (url, opts) => {
    const res = await fetch(url, opts)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json().catch(()=>null)
  }, [])

  useEffect(()=>{
    let cancelled = false
    async function load(){
      try{
    const [ui, domains] = await Promise.all([fetchJson('/api/ui_overview'), fetchJson('/api/domain_issues')])
    const merged = ui || {}
    // compute sites with missing fields from domain_issues mapping
    try{ merged.sites_with_missing = domains ? Object.keys(domains).length : 0 }catch(e){ merged.sites_with_missing = 0 }
    if (!cancelled) setStats(merged)
      }catch(e){ if (!cancelled) setError(e.message) }
    }
    load()
    return ()=>{ cancelled = true }
  }, [fetchJson])

  if (error) return <div style={{color:'crimson'}}>Error: {error}</div>
  if (!stats) return <div>Loading dashboard…</div>

  // ordered pipeline pages (updated labels and order)
  const pages = [
    { key: 'crawl', label: 'Crawl Errors', count: stats.crawl_errors || 0, buttonLabel: 'Check' },
    { key: 'candidates', label: 'Sites with missing fields', count: stats.sites_with_missing, buttonLabel: 'Extractions' },
    { key: 'dedupe', label: 'Potential Duplicates', count: stats.dedupe_near_misses, buttonLabel: 'Deuplicate' },
    { key: 'wire', label: 'Wire filtering', count: stats.wire_count, buttonLabel: 'Wire' },
    { key: 'review', label: 'Final Review', count: stats.total_articles, buttonLabel: 'Open' }
  ]

  return (
    <div>
      <h3>Pipeline Dashboard</h3>
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))', gap:12}}>
        {pages.map(p => (
          <div key={p.key} style={{padding:12, border:'1px solid #eee', borderRadius:6}}>
            <div style={{fontSize:12, color:'#666'}}>{p.label}</div>
            <div style={{fontSize:24, fontWeight:600, marginTop:6}}>{typeof p.count === 'number' ? p.count : '—'}</div>
            <div style={{marginTop:8}}>
              <button
                onClick={() => {
                  // Extraction Candidates are shown in the Domain Reports page —
                  // navigate there instead of relying on the internal tab key.
                  if (p.key === 'candidates') {
                    onOpen && onOpen('domain-reports')
                    return
                  }
                  onOpen && onOpen(p.key)
                }}
                style={{padding:'6px 10px'}}
              >{p.buttonLabel || 'Open'}</button>
            </div>
          </div>
        ))}
      </div>
      <div style={{marginTop:16}}>
        <h4 style={{marginBottom:8}}>Telemetry</h4>
        <div style={{maxWidth:320}}>
          <TelemetryQueue />
        </div>
      </div>
  {/* debug details removed */}
    </div>
  )
}
