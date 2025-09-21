import React, { useEffect, useState, useCallback } from 'react'

export default function CrawlIssues(){
  const [errorsByHost, setErrorsByHost] = useState(null)
  const [loading, setLoading] = useState(false)
  const [savingHost, setSavingHost] = useState(null)
  const [notesByHost, setNotesByHost] = useState({})
  const fetchJson = useCallback(async (url, opts) => {
    const res = await fetch(url, opts)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json().catch(()=>null)
  }, [])

  useEffect(()=>{ load() }, [])

  async function load(){
    setLoading(true)
    try{
      const data = await fetchJson('/api/crawl_errors')
      setErrorsByHost(data || {})
    }catch(e){ console.error('failed to load crawl errors', e); setErrorsByHost({}) }
    setLoading(false)
  }

  function formatDate(ts){ if(!ts) return ''; try{ const d = new Date(ts); return d.toLocaleString() }catch(e){ return String(ts) } }

  async function saveNotes(host){
    const notes = (notesByHost[host] || '').trim()
    setSavingHost(host)
    try{
      const resp = await fetch(`/api/domain_feedback/${encodeURIComponent(host)}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ notes }) })
      if(!resp.ok) throw new Error('save failed')
      // update local state
      setErrorsByHost(prev => ({ ...(prev||{}), [host]: prev && prev[host] ? { ...prev[host], _notes: notes } : prev && prev[host] }))
      alert('Notes saved')
    }catch(e){ console.error(e); alert('Failed to save notes: ' + (e && e.message ? e.message : String(e))) }
    setSavingHost(null)
  }

  return (
    <div style={{padding:12}}>
      <h3>Crawl Errors</h3>
      {loading ? <div>Loading…</div> : null}
      {!loading && (!errorsByHost || Object.keys(errorsByHost).length===0) ? (<div>No crawl errors found.</div>) : null}
      <div style={{display:'grid', gridTemplateColumns:'1fr', gap:12}}>
        {Object.keys(errorsByHost || {}).map(host => {
          const info = errorsByHost[host] || {}
          const errs = info.errors || {}
          return (
            <div key={host} style={{border:'1px solid #eee', padding:12, borderRadius:6}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <div>
                  <strong>{host}</strong>
                  <div style={{fontSize:12, color:'#666'}}>{info.total || 0} error(s)</div>
                </div>
                <div>
                  <button onClick={()=>{ load() }} style={{padding:'6px 10px'}}>Refresh</button>
                </div>
              </div>
              <div style={{marginTop:8}}>
                {Object.keys(errs).map(reason => {
                  const e = errs[reason] || {}
                  return (
                    <div key={reason} style={{padding:8, borderTop:'1px dashed #f3f3f3'}}>
                      <div style={{fontWeight:600}}>{reason}</div>
                      <div style={{fontSize:12, color:'#444', marginTop:4}}>Count: {e.count || 0} — Last seen: {formatDate(e.last_seen)} </div>
                      {e.example_url ? (<div style={{marginTop:6}}><a href={e.example_url} target="_blank" rel="noreferrer">Example URL</a></div>) : null}
                    </div>
                  )
                })}
              </div>
              <div style={{marginTop:10}}>
                <div style={{fontSize:13, marginBottom:6}}>Reviewer notes</div>
                <textarea rows={4} style={{width:'100%', padding:8}} value={notesByHost[host] || (info._notes || '')} onChange={(e)=> setNotesByHost(prev => ({ ...(prev||{}), [host]: e.target.value }))} />
                <div style={{marginTop:8}}>
                  <button disabled={savingHost===host} onClick={()=> saveNotes(host)} style={{padding:'6px 10px'}}>{savingHost===host ? 'Saving…' : 'Save notes'}</button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
