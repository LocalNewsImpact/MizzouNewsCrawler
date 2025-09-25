import React, { useEffect, useState } from 'react'

export default function TelemetryQueue(){
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(()=>{
    let mounted = true
    let timer = null
    async function fetchOnce(){
      try{
        const res = await fetch('/api/telemetry/queue')
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
        const j = await res.json()
        if (mounted) setData(j)
      }catch(e){ if (mounted) setError(e.message) }
      timer = setTimeout(fetchOnce, 5000)
    }
    fetchOnce()
    return ()=>{ mounted = false; if (timer) clearTimeout(timer) }
  }, [])

  if (error) return <div style={{color:'crimson'}}>Telemetry error: {error}</div>
  if (!data) return <div>Telemetry: loading…</div>

  return (
    <div style={{padding:12, border:'1px solid #eee', borderRadius:6}}>
      <div style={{fontSize:12, color:'#666'}}>Snapshot queue</div>
      <div style={{fontSize:20, fontWeight:600, marginTop:6}}>{data.queue_size}</div>
      <div style={{fontSize:12, color: data.worker_alive ? 'green' : 'crimson', marginTop:6}}>{data.worker_alive ? 'worker: alive' : 'worker: stopped'}</div>
    </div>
  )
}
