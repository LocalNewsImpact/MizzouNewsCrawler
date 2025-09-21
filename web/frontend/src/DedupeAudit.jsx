import React, { useState, useEffect } from 'react'

export default function DedupeAudit(){
  const [rows, setRows] = useState([])
  const [articleUid, setArticleUid] = useState('')
  const [host, setHost] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [count, setCount] = useState(0)

  async function fetchPage(){
    setLoading(true)
    try{
      const q = new URLSearchParams()
      if (articleUid) q.set('article_uid', articleUid)
      if (host) q.set('host', host)
      q.set('limit', String(limit))
      q.set('offset', String(offset))
      const resp = await fetch(`/api/dedupe_records?${q.toString()}`)
      if (!resp.ok) throw new Error(await resp.text())
      const json = await resp.json()
      setRows(json.results || [])
      setCount(json.count || (json.results ? json.results.length : 0))
    }catch(e){
      console.error('Failed to load dedupe records', e)
      setRows([])
      setCount(0)
    }finally{ setLoading(false) }
  }

  useEffect(()=>{ fetchPage() }, [articleUid, host, limit, offset])

  return (
    <div style={{padding:20}}>
      <h2>Dedupe Audit</h2>
      <div style={{display:'flex', gap:8, marginBottom:12}}>
        <input placeholder="article_uid" value={articleUid} onChange={e=>{ setArticleUid(e.target.value); setOffset(0) }} />
        <input placeholder="host" value={host} onChange={e=>{ setHost(e.target.value); setOffset(0) }} />
        <button onClick={()=>{ setOffset(0); fetchPage() }}>Refresh</button>
        <div style={{marginLeft:'auto'}}>Count: {count}</div>
      </div>

      {loading ? <div>Loading...</div> : (
        <table style={{width:'100%', borderCollapse:'collapse'}}>
          <thead>
            <tr>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>id</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>article_uid</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>neighbor_uid</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>host</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>similarity</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>dedupe_flag</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>stage</th>
              <th style={{textAlign:'left', borderBottom:'1px solid #ddd'}}>created_at</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r=> (
              <tr key={r.id} style={{borderBottom:'1px solid #f0f0f0'}}>
                <td>{r.id}</td>
                <td style={{maxWidth:200, overflow:'hidden', textOverflow:'ellipsis'}} title={r.article_uid}>{r.article_uid}</td>
                <td style={{maxWidth:200, overflow:'hidden', textOverflow:'ellipsis'}} title={r.neighbor_uid}>{r.neighbor_uid}</td>
                <td>{r.host}</td>
                <td>{r.similarity}</td>
                <td>{r.dedupe_flag}</td>
                <td>{r.stage}</td>
                <td>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{display:'flex', gap:8, marginTop:12}}>
        <button onClick={()=>{ setOffset(Math.max(0, offset - limit)) }}>Prev</button>
        <button onClick={()=>{ setOffset(offset + limit) }}>Next</button>
        <select value={limit} onChange={e=>{ setLimit(Number(e.target.value)); setOffset(0) }}>
          <option value={10}>10</option>
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
      </div>
    </div>
  )
}
