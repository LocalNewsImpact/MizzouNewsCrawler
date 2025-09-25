import React, { useEffect, useState, useCallback } from 'react'

export default function WireReview(){
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingIdx, setSavingIdx] = useState(null)

  const fetchJson = useCallback(async (url, opts) => {
    const res = await fetch(url, opts)
    if (!res.ok) { throw new Error(`${res.status} ${res.statusText}`) }
    return res.json().catch(()=>null)
  }, [])

  useEffect(()=>{
    let cancelled = false
    async function load(){
      setLoading(true)
      try{
        const resp = await fetchJson('/api/articles?limit=500')
        const rows = resp && resp.results ? resp.results : []
        // keep index mapping so we can POST to /api/articles/{idx}/reviews
        const withIdx = rows.map((r,i)=>({ ...r, __idx: i }))
        // filter wire-marked rows: the CSV may include a 'wire' column
        const wires = withIdx.filter(r => (typeof r.wire !== 'undefined' ? (r.wire === 1 || r.wire === '1' || r.wire === true) : false))
        if (!cancelled) setArticles(wires)
      }catch(e){ if (!cancelled) setError(e.message) }
      if (!cancelled) setLoading(false)
    }
    load()
    return ()=>{ cancelled = true }
  }, [fetchJson])

  async function sendFeedback(idx, val){
    // val: boolean true==wire, false==not wire
    setSavingIdx(idx)
    try{
      const payload = {
        reviewer: 'wire-review-ui',
        article_uid: articles[idx].id || articles[idx].uid || null,
        rating: 3,
        tags: [ val ? 'wire:yes' : 'wire:no' ],
        notes: val ? 'wire_yes' : 'wire_no'
      }
      // POST to review endpoint using CSV idx mapping
      const resp = await fetchJson(`/api/articles/${articles[idx].__idx}/reviews`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      // Optimistic update: mark article as reviewed locally
      setArticles(prev => prev.map((a,i)=> i===idx ? ({ ...a, __reviewed: (val ? 'yes' : 'no'), __review_id: resp && resp.id ? resp.id : null }) : a))
    }catch(e){ setError(e.message) }
    setSavingIdx(null)
  }

  if (loading) return <div>Loading wire-marked articles…</div>
  if (error) return <div style={{color:'crimson'}}>Error: {error}</div>
  if (!articles || articles.length === 0) return <div>No wire-marked articles found.</div>

  return (
    <div>
      <h3>Wire-marked articles</h3>
      <div style={{display:'flex',flexDirection:'column',gap:8}}>
        {articles.map((a, i) => (
          <div key={a.url || a.id || i} style={{padding:8, border:'1px solid #eee', borderRadius:6, display:'flex', alignItems:'center', gap:12}}>
            <div style={{flex:1}}>
              <div style={{fontWeight:600}}>{a.title || a.headline || a.name || a.url}</div>
              <div style={{fontSize:12, color:'#666'}}>{a.domain || a.hostname || ''} — {a.date || a.publish_date || ''}</div>
              <div style={{fontSize:12, color:'#444', marginTop:6, maxHeight:60, overflow:'hidden'}}>{a.news || a.body || a.content || ''}</div>
            </div>
            <div style={{display:'flex',flexDirection:'column',gap:6}}>
              <div>
                <button disabled={savingIdx===i} onClick={()=>sendFeedback(i, true)} style={{background: a.__reviewed === 'yes' ? '#c8f7d4' : undefined, padding:'6px 10px'}}>Yes</button>
                <button disabled={savingIdx===i} onClick={()=>sendFeedback(i, false)} style={{marginLeft:8, background: a.__reviewed === 'no' ? '#f7c8c8' : undefined, padding:'6px 10px'}}>No</button>
              </div>
              {a.__reviewed && <div style={{fontSize:12,color:'#333'}}>You marked: {a.__reviewed}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
