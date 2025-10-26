import React, { useEffect, useState, useCallback } from 'react'
import { Container, Paper, Typography, Grid, List, ListItemButton, Button, TextField, Select, MenuItem, FormControl, InputLabel } from '@mui/material'
import TagSelect from './components/TagSelect'
import SliderWithBubble from './components/SliderWithBubble'
import DedupeAudit from './DedupeAudit'
import WireReview from './WireReview'
import Dashboard from './Dashboard'
import CrawlIssues from './CrawlIssues'
import BylineReviewInterface from './BylineReviewInterface'
import VerificationReviewInterface from './VerificationReviewInterface'
import CodeReviewInterface from './CodeReviewInterface'
import GazetteerTelemetry from './GazetteerTelemetry'
import OperationsDashboard from './OperationsDashboard'

export default function App(){
  const [activeTab, setActiveTab] = useState('dashboard') // 'dashboard' | 'review' | 'dedupe' | 'wire' | 'domain-reports'
  // support domain-reports SPA tab

  // Test option fallbacks used when the backend returns no options (helps local UI testing)
  const TEST_BODY_OPTIONS = [
  { id: 'b1', label: 'Missing' },
  { id: 'b2', label: 'Incomplete' },
  { id: 'b3', label: 'Incorrect' },
  { id: 'b4', label: 'Wire Service' },
  { id: 'b5', label: 'HTML or JS' },
  { id: 'b6', label: 'Bad Characters' }
  ]
  const TEST_HEADLINE_OPTIONS = [
  { id: 'h1', label: 'Missing' },
  { id: 'h2', label: 'Incomplete' },
  { id: 'h3', label: 'Incorrect' },
  { id: 'h4', label: 'HTML or JS' },
  { id: 'h5', label: 'Bad Characters' }
  ]
  const TEST_AUTHOR_OPTIONS = [
  { id: 'a1', label: 'Missing' },
  { id: 'a2', label: 'Incomplete' },
  { id: 'a3', label: 'Incorrect' },
  { id: 'a4', label: 'HTML or JS' },
  { id: 'a5', label: 'Bad Characters' }
  ]
  const [bodyOptions, setBodyOptions] = useState([])
  const [headlineOptions, setHeadlineOptions] = useState([])
  const [authorOptions, setAuthorOptions] = useState([])

  const [articles, setArticles] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [article, setArticle] = useState(null)
  // Location select state (UI-only by default)
  const [locationOptions, setLocationOptions] = useState([]) // {id,label}
  const [selectedLocations, setSelectedLocations] = useState([]) // array of {id,label}
  const [locationInput, setLocationInput] = useState('')
  const [missingLocations, setMissingLocations] = useState([]) // manual entries to persist as missing_locations
  const [removedMentionLabels, setRemovedMentionLabels] = useState([]) // labels user removed
  // Inferred tags UI: chips similar to mentioned locations
  const [inferredTags, setInferredTags] = useState([]) // array of {id,label}
  const [missingTags, setMissingTags] = useState([]) // manual entries to persist as missing_tags
  const [removedTagLabels, setRemovedTagLabels] = useState([]) // labels user removed from inferred tags
  const [selectedChipLabels, setSelectedChipLabels] = useState([]) // currently selected/toggled chips

  const [selectedBody, setSelectedBody] = useState([])
  const [selectedHeadline, setSelectedHeadline] = useState([])
  const [selectedAuthor, setSelectedAuthor] = useState([])

  const [saveStatus, setSaveStatus] = useState('unsaved') // unsaved | saving | saved | edited | error
  const [error, setError] = useState(null)
  const saveTimerRef = React.useRef(null)
  const pendingPayloadRef = React.useRef(null)
  // map of article_idx -> saved review id (so we can update existing reviews)
  const savedReviewIdRef = React.useRef({})
  // per-article transient drafts (unsaved edits retained when navigating)
  const draftCacheRef = React.useRef({})
  // localStorage key for persisting drafts across reloads
  const DRAFTS_STORAGE_KEY = 'mizzou:drafts:v1'

  // load drafts from localStorage into draftCacheRef
  function loadDraftsFromLocalStorage(){
    try{
      const raw = window.localStorage.getItem(DRAFTS_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object') {
        // normalize modifiedAt
        Object.keys(parsed).forEach(k => { if (!parsed[k].modifiedAt) parsed[k].modifiedAt = 0 })
        draftCacheRef.current = parsed
      }
    }catch(e){ console.warn('failed to load drafts from localStorage', e) }
  }

  // persist draftCacheRef to localStorage
  function saveDraftsToLocalStorage(){
    try{
      window.localStorage.setItem(DRAFTS_STORAGE_KEY, JSON.stringify(draftCacheRef.current || {}))
    }catch(e){ console.warn('failed to save drafts to localStorage', e) }
  }
  // monotonically increasing version to avoid race conditions between saves and newer edits
  const saveVersionRef = React.useRef(0)
  const lastCommittedDefault = { body: [], headline: [], author: [], primary_rating: 3, secondary_rating: 3, notes: '' }
  const lastCommittedRef = React.useRef(lastCommittedDefault)

  const [primaryRating, setPrimaryRating] = useState(3)
  const [secondaryRating, setSecondaryRating] = useState(3)
  const [reviewer, setReviewer] = useState('local')
  const [notes, setNotes] = useState('')
  const [savedPayload, setSavedPayload] = useState(null)
  const savedHashRef = React.useRef(null)
  // per-article in-memory cache for recently saved canonical payloads { [article_idx]: { payload, hash, id } }
  const savedCacheRef = React.useRef({})
  // Guard flag used when applying server-authoritative canonical into the UI
  // to prevent checkAndSetSaved from running during intermediate state updates.
  const applyingServerCanonicalRef = React.useRef(false)
  // Tick state used to release the applyingServerCanonicalRef after React has
  // processed the state updates that were scheduled when applying canonical.
  const [applyCanonicalTick, setApplyCanonicalTick] = useState(0)

  // Shared style for the navigation count and reviewer input to visually
  // associate them with a darker grey container.
  const assocBoxStyle = {
    background: '#e6e7ea',
    padding: 10,
    borderRadius: 8,
    border: '1px solid #cfcfd1',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    minWidth: 220
  }

  // When applyCanonicalTick increments, release the guard and re-evaluate savedness.
  useEffect(()=>{
    if (!applyingServerCanonicalRef.current) return
    // Release guard now that React has processed the scheduled state updates
    applyingServerCanonicalRef.current = false
    try{ checkAndSetSaved() }catch(e){}
  }, [applyCanonicalTick])

  // helper: recompute canonical for current UI and set saveStatus -> 'saved' or 'edited'/'unsaved'
  function checkAndSetSaved(){
    try{
  // Skip saved-state checks while we're applying server canonical to avoid
  // transient mismatches between UI state updates and saved-cache/hash.
  if (applyingServerCanonicalRef.current) {
    console.debug('[checkAndSetSaved] skipped while applying server canonical')
    return
  }
  const currentCanonical = stableStringify(buildServerPayloadFromUI({ article_uid: article && (article.id || article.uid || article.host_id) ? (article.id || article.uid || article.host_id) : undefined }))
  // Prefer per-article cached canonical hash when available so navigation updates correctly
  const cached = savedCacheRef.current && savedCacheRef.current[String(currentIndex)]
  // If the per-article cache is not yet populated, fall back to the global savedHashRef
  // which is updated optimistically during saves. This prevents a race where
  // the UI flips to 'edited' before the optimistic saved hash has been applied
  // to the per-article cache.
  const savedHashForIndex = (cached && cached.hash) ? cached.hash : (savedHashRef.current || null)
  const hasSavedRecord = !!(savedReviewIdRef.current && savedReviewIdRef.current[String(currentIndex)])
  // Debugging: log canonical vs cached so we can trace why UI shows 'edited'
  try{ console.debug('[checkAndSetSaved] idx', currentIndex, 'currentCanonical', currentCanonical, 'savedHashForIndex', savedHashForIndex, 'hasSavedRecord', hasSavedRecord, 'cachedEntry', cached) }catch(e){}
  if (savedHashForIndex) {
    const isSaved = currentCanonical === savedHashForIndex
    setSaveStatus(isSaved ? 'saved' : 'edited')
  } else {
    // No cached canonical available. If the server indicates a saved record exists
    // for this article (we have an id), show 'saved' until we fetch/refresh the
    // canonical; otherwise show 'unsaved'. This avoids showing 'edited' due to
    // stale global savedHashRef from another article.
    setSaveStatus(hasSavedRecord ? 'saved' : 'unsaved')
  }
    }catch(e){ /* ignore */ }
  }


  const fetchJson = useCallback(async (url, opts) => {
  const res = await fetch(url, opts)
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`${res.status} ${res.statusText} - ${text}`)
    }
    return res.json().catch(()=>null)
  }, [])

  // Stable stringify that sorts object keys so we can compare payloads deterministically
  function stableStringify(obj){
    const type = Object.prototype.toString.call(obj)
    if (obj === null || typeof obj !== 'object') return JSON.stringify(obj)
    if (Array.isArray(obj)) return '[' + obj.map(v=>stableStringify(v)).join(',') + ']'
    const keys = Object.keys(obj).sort()
    return '{' + keys.map(k => JSON.stringify(k) + ':' + stableStringify(obj[k])).join(',') + '}'
  }

  function buildServerPayloadFromUI(override){
    const payload = override || {}
    const serverPayload = {
  // stable article identifier when available
  // allow caller to override article_uid (important for scheduled saves captured by UID)
  article_uid: (typeof payload.article_uid !== 'undefined') ? payload.article_uid : (article && (article.id || article.uid || article.host_id) ? (article.id || article.uid || article.host_id) : undefined),
  reviewer: (typeof payload.reviewer !== 'undefined') ? payload.reviewer : (payload.reviewer === '' ? '' : (reviewer || savedPayload?.reviewer || 'local')),
      primary_rating: (payload.primary_rating ?? payload.primary_rating ?? primaryRating) ?? primaryRating ?? 3,
      secondary_rating: (payload.secondary_rating ?? payload.secondary_rating ?? secondaryRating) ?? secondaryRating ?? 3,
      // include arrays of ids for body/headline/author to match server-stored columns
      body: Array.isArray(payload.body_errors) ? payload.body_errors.map(String) : selectedBody.map(o=>String(o.id)),
      headline: Array.isArray(payload.headline_errors) ? payload.headline_errors.map(String) : selectedHeadline.map(o=>String(o.id)),
      author: Array.isArray(payload.author_errors) ? payload.author_errors.map(String) : selectedAuthor.map(o=>String(o.id)),
      // Build tags from explicit payload arrays when provided, otherwise derive
      // them from the current selected UI values so canonical comparisons
      // remain consistent regardless of whether buildServerPayloadFromUI was
      // called with an override or not.
      tags: (
        ([...(Array.isArray(payload.body_errors) ? payload.body_errors.map(String) : selectedBody.map(o=>String(o.id)) || []),
        ...(Array.isArray(payload.headline_errors) ? payload.headline_errors.map(String) : selectedHeadline.map(o=>String(o.id)) || []),
        ...(Array.isArray(payload.author_errors) ? payload.author_errors.map(String) : selectedAuthor.map(o=>String(o.id)) || [])])
      ).filter(Boolean),
  notes: payload.notes ?? notes ?? '',
    // include mentioned locations as an array of labels (backend field: mentioned_locations)
  // Note: we no longer persist UI-selected chips for mentioned locations; frontend sends any explicit payload. Missing manual entries are sent in missing_locations below.
  mentioned_locations: Array.isArray(payload.mentioned_locations) ? payload.mentioned_locations.map(String) : [],
  // include manual additions in missing_locations (backend field: missing_locations)
  missing_locations: Array.isArray(payload.missing_locations) ? payload.missing_locations.map(String) : (Array.isArray(missingLocations) ? missingLocations.map(String) : []),
  // inferred tags mirror mentioned locations UI-wise; persist missing_tags separately
  inferred_tags: Array.isArray(payload.inferred_tags) ? payload.inferred_tags.map(String) : (Array.isArray(inferredTags) ? inferredTags.map(o=>String(o.label)) : []),
  missing_tags: Array.isArray(payload.missing_tags) ? payload.missing_tags.map(String) : (Array.isArray(missingTags) ? missingTags.map(String) : []),
    }
    // normalize tags order for deterministic comparison
    if (Array.isArray(serverPayload.tags)) {
      // normalize string form, dedupe, sort
      serverPayload.tags = Array.from(new Set(serverPayload.tags.map(String).filter(t => t !== 'NONE' && t !== 'None'))).sort()
    } else {
      serverPayload.tags = []
    }
    return serverPayload
  }

  // Convert server-side canonical payload (ids) into display-friendly objects
  // Enrich canonical payload (arrays of ids) into objects for the UI.
  // Accept optional pools so callers can supply the option lists they have
  // available at the time of enrichment (helps avoid label fallbacks when
  // options are being loaded asynchronously).
  function enrichServerPayload(p, pools = { body: bodyOptions, headline: headlineOptions, author: authorOptions }) {
    if (!p) return p
    const mapIds = (ids, pool) => (Array.isArray(ids) ? ids.map(id => (pool||[]).find(o=>String(o.id)===String(id)) || { id, label: String(id) }) : [])
    return {
      ...p,
      body: mapIds(p.body, pools.body),
      headline: mapIds(p.headline, pools.headline),
      author: mapIds(p.author, pools.author)
    }
  }
  // ensure saved-ness is re-evaluated after the UI state updates
  setTimeout(()=>{ try{ checkAndSetSaved() }catch(e){} }, 0)

  // Domain Reports SPA component (inlined from App.tsx)
  function DomainReports(){
    const [domainIssues, setDomainIssues] = useState({})
    const [selectedHost, setSelectedHost] = useState('')
    const [feedback, setFeedback] = useState({ priority: 'low', notes: '' })

    useEffect(()=>{
      fetch('/api/domain_issues')
        .then(r => r.json())
        .then(d => setDomainIssues(d || {}))
        .catch(()=> setDomainIssues({}))
    }, [])

    async function saveHostFeedback(){
      if (!selectedHost) return
      await fetch(`/api/domain_feedback/${encodeURIComponent(selectedHost)}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(feedback) })
      setDomainIssues(prev => ({ ...prev, [selectedHost]: { ...(prev)[selectedHost], feedback } }))
      // small UX hint
      try{ alert('feedback saved') }catch(e){}
    }

  // snapshots and candidates for the selected host
  const [snapshots, setSnapshots] = useState([])
  // candidates grouped per snapshot: { [snapshotId]: { snapshot, groupsByField: { field: [ groups ] }, rawCandidates: [] , html: string|null } }
  const [candidatesBySnapshot, setCandidatesBySnapshot] = useState(null)
  const [loadingCandidates, setLoadingCandidates] = useState(false)
  // ordered list of unique snapshot ids (most recent first) after dedup by missing-fields
  const [uniqueSnapshotOrder, setUniqueSnapshotOrder] = useState([])
  // currently active snapshot id shown in the story view
  const [activeSnapshotId, setActiveSnapshotId] = useState(null)

    useEffect(()=>{
      // clear previous snapshots/candidates when host changes
  setSnapshots([])
  setCandidatesBySnapshot(null)
  setUniqueSnapshotOrder([])
  setActiveSnapshotId(null)
      setLoadingCandidates(false)
      if (!selectedHost) return
      fetch(`/api/snapshots_by_host/${encodeURIComponent(selectedHost)}`)
        .then(r => r.json())
        .then(d => {
          const arr = Array.isArray(d) ? d : []
          setSnapshots(arr)
          // automatically load candidates for the newly fetched snapshots
          try{ loadCandidatesForHost(arr) }catch(e){}
        })
        .catch(()=> setSnapshots([]))
    }, [selectedHost])

    // Helpers for grouping and scoring (ported from legacy domain_reports.html)
    function normalizeText(t){ if(!t) return ''; return String(t).replace(/\s+/g,' ').trim().toLowerCase() }
    function tokenSet(t){ const s = normalizeText(t); if(!s) return new Set(); return new Set(s.split(/\W+/).filter(Boolean)) }
    function jaccard(a,b){ if(a.size===0 && b.size===0) return 1; const inter = [...a].filter(x=>b.has(x)).length; const union = new Set([...a,...b]).size; return union===0?0: inter/union }

    async function selectorDepthHeuristic(sel, htmlText){
      if(!sel) return 0
      // try DOM-aware depth if htmlText provided
      try{
        if(htmlText){
          try{
            const parser = new DOMParser()
            const doc = parser.parseFromString(htmlText, 'text/html')
            try{
              const nodes = Array.from(doc.querySelectorAll(sel))
              if(nodes.length===0) return 0
              function nodeDepth(n){ let d=0; let t=n; while(t && t.nodeType===1){ t=t.parentElement; d+=1 } return d }
              return Math.max(...nodes.map(nodeDepth))
            }catch(e){ /* fall back to string heuristic below */ }
          }catch(e){ /* fall back */ }
        }
      }catch(e){}
      try{
        const cleaned = String(sel).replace(/::?\w+(?:\([^)]*\))?/g,'').replace(/\[[^\]]+\]/g,'')
        const parts = cleaned.split(/\s+|>|\+|~/).map(s=>s.trim()).filter(Boolean)
        return parts.length
      }catch(e){ return 0 }
    }

    // score helper used when picking best selector inside a chosen group
    function scoreSelectorForPickMeta(m, candidateSnippet, htmlText){
      try{
        // id-based selectors get a huge boost
        if(/#\w+/.test(m.selector)) return 10000 + Number(m.score||0)
        // Prefer selectors that explicitly target the article body region
        // Common CMS class patterns include `field-name-body` or `body` within
        // the selector. Give a large boost so these are chosen as the "deepest"
        // canonical selector when present.
        try{
          const sel = String(m.selector || '')
          if(/(^|\\.|\\s)field-name-body(\\b|$)/i.test(sel) || /field[-_]?name[-_]body/i.test(sel) || /\\.body\\b/i.test(sel)){
            return 100000 + Number(m.score||0)
          }
        }catch(e){}
        const clsCount = (String(m.selector||'').match(/\./g)||[]).length
        const depth = selectorDepthHeuristic(m.selector || '', htmlText) || 0
        const words = Number(m.words || 0) || 0
        const depthBoost = depth * 80 // increase depth importance
        const wordPenalty = Math.min(words, 1000) * 0.15
        let base = clsCount*80 + Number(m.score||0) + depthBoost - wordPenalty
        // DOM-aware containment & similarity scoring if htmlText is available
        if(htmlText){
          try{
            const parser = new DOMParser()
            const doc = parser.parseFromString(htmlText, 'text/html')
            let nodes = []
            try{ nodes = Array.from(doc.querySelectorAll(m.selector)) }catch(e){ nodes = [] }
            if(nodes.length){
              const norm = t => (t||'').replace(/\s+/g,' ').trim().toLowerCase()
              const candNorm = norm(candidateSnippet || '')
              // compute token-based similarity between candidate snippet and node text
              const candTokens = new Set((candNorm||'').split(/\W+/).filter(Boolean))
              let bestNodeScore = 0
              let bestNodeDepth = 0
              let bestNodeIndex = -1
              for(let idx=0; idx<nodes.length; idx++){
                const n = nodes[idx]
                const text = norm(n.textContent || '')
                const depthN = (function(n2){ let d=0; let t=n2; while(t && t.nodeType===1){ t=t.parentElement; d+=1 } return d })(n)
                let s = 0
                if(candNorm && text.includes(candNorm)){
                  // exact containment is extremely strong; prefer deeper nodes and later occurrences
                  s = 300000 + depthN*400
                } else if(candNorm){
                  const a = candTokens
                  const b = new Set(text.split(/\W+/).filter(Boolean))
                  const inter = [...a].filter(x=>b.has(x)).length
                  const union = new Set([...a,...b]).size || 1
                  const sim = inter/union
                  // similarity contributes, strongly scaled by depth to prefer deeper, more specific matches
                  s = Math.round(sim*8000) + depthN*150
                }
                // if no strong similarity but selector is very deep, give a moderate boost
                if(s === 0 && depthN >= 6){
                  s = 2000 + depthN*100
                }
                // choose better node; when equal score prefer the later node (higher index)
                if(s > bestNodeScore || (s === bestNodeScore && idx > bestNodeIndex)){
                  bestNodeScore = s
                  bestNodeDepth = depthN
                  bestNodeIndex = idx
                }
              }
              if(bestNodeScore > 0){ base += bestNodeScore; base += bestNodeDepth*20 }
            }
          }catch(e){ /* ignore DOM errors */ }
        }
        return base
      }catch(e){ return Number(m.score||0) }
    }

    async function groupCandidatesForField(candidatesForField, htmlText){
      // Group strictly by exact snippet text (including character count). If
      // a candidate has no snippet, fall back to its selector string.
      const map = {}
      for(const c of candidatesForField){
        const key = (typeof c.snippet === 'string' && c.snippet.length) ? c.snippet : (c.selector || '')
        if(!Object.prototype.hasOwnProperty.call(map, key)) map[key] = { members: [] }
        map[key].members.push(c)
      }

      const groups = []
      for(const k of Object.keys(map)){
        const grp = map[k]
        grp.key = k
        // choose representative: prefer accepted, otherwise score members against
        // the group's exact snippet so selectors that actually extract that
        // text win.
        let rep = grp.members[0]
        const accepted = grp.members.find(m=> Number((m.accepted||0)) > 0)
        if(accepted) rep = accepted
        else {
          try{
            // Prefer selectors that actually contain the group's exact snippet
            // (normalized substring). Among those prefer the deepest selector.
            let best = null
            let bestScore = -Infinity
            let bestDepth = -1
            const normGroupKey = normalizeText(k || '')
            // Try DOM-aware containment check first when htmlText is available
            if(htmlText && normGroupKey){
              try{
                const parser = new DOMParser()
                const doc = parser.parseFromString(htmlText, 'text/html')
                for(const m of grp.members){
                  try{
                    const nodes = Array.from(doc.querySelectorAll(m.selector || ''))
                    let contains = false
                    let depthMax = 0
                    for(const n of nodes){
                      const txt = normalizeText(n.textContent || '')
                      if(txt && txt.includes(normGroupKey)){
                        contains = true
                        // compute depth for tie-breaking
                        let d = 0; let t = n; while(t && t.nodeType===1){ t = t.parentElement; d += 1 }
                        if(d > depthMax) depthMax = d
                      }
                    }
                    if(contains){
                      const scoreBoost = 100000 + depthMax*1000
                      if(best === null || scoreBoost > bestScore || (scoreBoost === bestScore && depthMax > bestDepth)){
                        best = m; bestScore = scoreBoost; bestDepth = depthMax
                      }
                    }
                  }catch(e){ /* ignore per-selector DOM errors */ }
                }
              }catch(e){ /* ignore DOM parsing errors and fall back to scoring below */ }
            }

            // If we didn't find any selector that contains the group's text, fall back
            // to the existing pick heuristic using scoreSelectorForPickMeta and depth.
            if(best === null){
              for(const m of grp.members){
                const depth = await selectorDepthHeuristic(m.selector || '', htmlText) || 0
                const pickScore = Number(await scoreSelectorForPickMeta(m, k, htmlText) || 0)
                if(best === null || pickScore > bestScore || (pickScore === bestScore && depth > bestDepth)){
                  best = m; bestScore = pickScore; bestDepth = depth
                }
              }
            }
            if(best) rep = best
          }catch(e){ /* ignore scoring failures and fall back to first member */ }
        }
        grp.rep = rep
        grp.members.sort((a,b)=>Number(b.score||0)-Number(a.score||0))
        groups.push(grp)
      }

      groups.sort((A,B)=>Number(B.rep.score||0)-Number(A.rep.score||0))
      return groups
    }

  async function loadCandidatesForHost(snapshotsList){
      if (!selectedHost) return
      setLoadingCandidates(true)
      const out = {}
      try{
  // Sort snapshots by created_at (newest first) and dedupe by missing-field set.
  const rawList = (snapshotsList || snapshots || []).slice(0,30)
  const toLoad = rawList.slice().sort((a,b)=> {
      try{ const ta = new Date(a.created_at||a.created || 0).getTime()||0; const tb = new Date(b.created_at||b.created || 0).getTime()||0; return tb - ta }catch(e){ return 0 }
    })
    const seenMissingSets = new Set()
    const order = []
    for(const s of toLoad){
          try{
            const sid = s.id
            const res = await fetch(`/api/snapshots/${encodeURIComponent(sid)}`)
            if (!res.ok) continue
            const snap = await res.json()
            const list = Array.isArray(snap.candidates) ? snap.candidates : []
            // try to fetch snapshot HTML to enable DOM-aware heuristics
            let htmlText = null
            try{
              const hres = await fetch(`/api/snapshots/${encodeURIComponent(sid)}/html`)
              if(hres.ok) htmlText = await hres.text()
            }catch(e){ /* ignore html fetch failures */ }
            // compute missing fields similar to legacy: check parsed_fields and model_confidence
            const parsed = snap.parsed_fields || snap.parsed || snap.parsed || {}
            const modelConf = snap.model_confidence || 0
            const fieldsToCheck = ['body','headline','author']
            const missing = []
            for(const f of fieldsToCheck){ const have = parsed && parsed[f]; if(!have || (modelConf && modelConf < 0.6)) missing.push(f) }
            // dedupe: create a canonical key for the missing-field set
            const missingKey = (Array.isArray(missing) ? missing.slice().sort().join('|') : '')
            if(seenMissingSets.has(missingKey)){
              // skip this snapshot because a newer snapshot with the same missing-fields set was already processed
              continue
            }
            seenMissingSets.add(missingKey)
            const groupedByField = {}
            for(const fld of missing){
              const candidatesForField = list.filter(c => (c.field||'unknown') === fld)
              if(candidatesForField.length===0){ groupedByField[fld] = [] } else {
                groupedByField[fld] = await groupCandidatesForField(candidatesForField, htmlText)
              }
            }
    out[sid] = { snapshot: s, groupedByField, rawCandidates: list, html: htmlText }
    order.push(sid)
          }catch(e){ /* continue on per-snapshot failure */ }
        }
      }catch(e){ /* ignore top-level */ }
  setCandidatesBySnapshot(out)
  setUniqueSnapshotOrder(order)
  setActiveSnapshotId(order && order.length ? order[0] : null)
      setLoadingCandidates(false)
    }

    // Format timestamp into MM/DD/YYYY HH:MM:SS for dropdown labels
    function formatTimestamp(ts){
      if(!ts) return ''
      try{
        const d = new Date(ts)
        if (isNaN(d.getTime())) return String(ts)
        const pad = n => String(n).padStart(2,'0')
        return `${pad(d.getMonth()+1)}/${pad(d.getDate())}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
      }catch(e){ return String(ts) }
    }

    // Precompute storyBlock to keep JSX simple and avoid nested IIFE parsing issues.
    const storyBlock = (() => {
      if(!candidatesBySnapshot) return null
      if(Object.keys(candidatesBySnapshot).length === 0) return (
        <div style={{fontSize:12, color:'#666', marginTop:8}}>No candidates found.</div>
      )
      const sids = uniqueSnapshotOrder && uniqueSnapshotOrder.length ? uniqueSnapshotOrder : Object.keys(candidatesBySnapshot)
      const sid = activeSnapshotId || (sids.length ? sids[0] : null)
      if(!sid) return null
      const info = candidatesBySnapshot[sid]
      const srec = info && info.snapshot ? info.snapshot : null
      const groupedByField = (info && info.groupedByField) || {}
      const multiple = (sids && sids.length > 1)
      return (
        <div>
          {multiple ? (
            <div style={{marginBottom:8, display:'flex', gap:8, alignItems:'center'}}>
              <div style={{fontSize:13, color:'#444'}}>Showing story:</div>
              <FormControl size="small" sx={{ minWidth: 300 }}>
                <Select value={sid || ''} onChange={(e)=>{ setActiveSnapshotId(e.target.value) }}>
                  {sids.map(skey => {
                    const srec2 = candidatesBySnapshot[skey] && candidatesBySnapshot[skey].snapshot ? candidatesBySnapshot[skey].snapshot : { url: skey, created_at: '' }
                    const label = formatTimestamp(srec2.created_at || srec2.created || srec2.created_at)
                    return (<MenuItem key={skey} value={skey}>{label}</MenuItem>)
                  })}
                </Select>
              </FormControl>
            </div>
          ) : null}
          <div key={sid} style={{marginBottom:18, padding:10, border:'1px solid #f2f2f2', borderRadius:6}}>
            <div style={{fontSize:13, marginBottom:6}}>
              <a href={srec && srec.url ? srec.url : '#'} target="_blank" rel="noreferrer">{srec && srec.url ? (srec.url.length>100 ? srec.url.slice(0,100)+'…' : srec.url) : sid}</a>
              <div style={{fontSize:11, color:'#666'}}>{srec && srec.created_at ? srec.created_at : ''}</div>
            </div>
            {Object.keys(groupedByField).length === 0 ? (
              <div style={{fontSize:12, color:'#666'}}>No grouped candidates for this snapshot.</div>
            ) : (
              <div>
                {Object.keys(groupedByField).map(fld => (
                  <div key={fld} style={{marginTop:8, paddingTop:6, borderTop:'1px dashed #eee'}}>
                    <div style={{fontSize:13, fontWeight:600}}>{fld} — {groupedByField[fld].length} group(s)</div>
                    <div style={{marginTop:6}}>
                      {groupedByField[fld].map((g, gi) => {
                        const snippetText = (typeof g.key === 'string' && g.key.length) ? g.key : (g.rep && g.rep.snippet ? g.rep.snippet : '')
                        // Prefer DOM-derived full extraction word count when HTML is available
                        let wordCount = 0
                        try{
                          if(info && info.html && g && g.rep && g.rep.selector){
                            try{
                              const parser = new DOMParser()
                              const doc = parser.parseFromString(info.html, 'text/html')
                              let nodes = []
                              try{ nodes = Array.from(doc.querySelectorAll(g.rep.selector)) }catch(e){ nodes = [] }
                              if(nodes.length){
                                const fullText = nodes.map(n => (n.textContent||'')).join(' ').trim()
                                wordCount = fullText ? fullText.split(/\s+/).filter(Boolean).length : 0
                              }
                            }catch(e){ /* fall back below */ }
                          }
                        }catch(e){ /* ignore DOM errors */ }
                        if(!wordCount){
                          // fallback to group's snippet text
                          wordCount = snippetText ? snippetText.trim().split(/\s+/).filter(Boolean).length : 0
                        }
                        return (
                        <div key={gi} style={{padding:8, borderRadius:6, marginBottom:10, background:'#fff', boxShadow:'inset 0 0 0 1px #f3f3f3'}} data-group-index={gi}>
                          <label style={{display:'flex', alignItems:'flex-start', gap:12, cursor:'pointer'}}>
                            <input type="radio" name={`sel_${sid}_${fld}`} id={`sel_${sid}_${fld}_group_${gi}`} defaultChecked={gi===0} value={`group:${gi}`} data-snippet={snippetText} style={{marginTop:6}} />
                            <div style={{flex:1}}>
                              <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
                                <div style={{fontSize:14, lineHeight:1.3, color:'#222'}}>
                                  {(snippetText && snippetText.length) ? (
                                    <div style={{whiteSpace:'pre-wrap', wordBreak:'break-word'}}>
                                      {snippetText.length>800 ? snippetText.slice(0,800)+'…' : snippetText}
                                      <span style={{fontSize:11, color:'#999', marginLeft:8}}>({wordCount} word{wordCount===1?'':'s'})</span>
                                    </div>
                                  ) : (
                                    <em style={{color:'#888'}}>no snippet</em>
                                  )}
                                </div>
                                <div style={{textAlign:'right', minWidth:80}}>
                                  <div style={{fontSize:12, color:'#666'}}>{g.members.length} selector{g.members.length===1?'':'s'}</div>
                                </div>
                              </div>
                            </div>
                          </label>
                        </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* submit button for this snapshot */}
            <div style={{marginTop:8}}>
              <Button size="small" variant="outlined" onClick={async ()=>{
                try{
                  const toCommit = []
                  for(const field of ['body','headline','author']){
                    const rs = Array.from(document.getElementsByName(`sel_${sid}_${field}`))
                    const checked = rs.filter(r=>r && r.checked)
                    if(checked.length===0) continue
                    const sel = checked[0]
                    const val = sel.value || ''
                    if(val.startsWith('group:')){
                      const gi = Number(val.split(':')[1])
                      const groups = (groupedByField && groupedByField[field]) || []
                      const meta = (groups[gi] && groups[gi].members) ? groups[gi].members.map(m=>({selector:m.selector,score:m.score,words:m.words,snippet:m.snippet,id:m.id, accepted: m.accepted})) : []
                      if(meta.length===0) continue
                      let bestMeta = meta[0]
                      let bestScore = await scoreSelectorForPickMeta(bestMeta, bestMeta.snippet || '', info && info.html)
                      for(const mm of meta.slice(1)){
                        const sc = await scoreSelectorForPickMeta(mm, mm.snippet || '', info && info.html)
                        if(sc > bestScore){ bestMeta = mm; bestScore = sc }
                      }
                      const groupKey = (groups[gi] && typeof groups[gi].key === 'string') ? groups[gi].key : ''
                      const chosenSnippet = groupKey || bestMeta.snippet || (sel && sel.getAttribute ? sel.getAttribute('data-snippet') : '') || ''
                      const acceptedInGroup = (groups[gi] && groups[gi].members && groups[gi].members.some && groups[gi].members.some(m => Number((m.accepted||0)) > 0)) ? true : false
                      toCommit.push({ field, selector: bestMeta.selector, snippet: chosenSnippet, accepted: acceptedInGroup })
                    } else {
                      toCommit.push({ field, selector: val, snippet: (sel && sel.getAttribute ? sel.getAttribute('data-snippet') : '') || '', accepted: false })
                    }
                  }
                  if(toCommit.length===0) return alert('No selectors chosen for this story')
                  for(const c of toCommit){
                    if(info && info.html){
                      const parser = new DOMParser()
                      const doc = parser.parseFromString(info.html, 'text/html')
                      let matched = []
                      try{ matched = Array.from(doc.querySelectorAll(c.selector)).map(el=>el.textContent || '') }catch(e){ matched = [] }
                      if(!c.accepted){
                        const canonicalFull = (c.snippet || '')
                        const candTokens = tokenSet(canonicalFull || '')
                        let bestJaccard = 0
                        let bestCoverage = 0
                        for(const mText of matched){
                          const text = (mText || '').trim()
                          const norm = t => normalizeText(t)
                          const normCand = norm(canonicalFull)
                          const normText = norm(text)
                          if(normCand && normText.includes(normCand)){
                            bestJaccard = 1; bestCoverage = 1; break
                          }
                          const sset = tokenSet(text)
                          const inter = [...sset].filter(x=>candTokens.has(x)).length
                          const cov = Math.min( inter / (candTokens.size || 1), inter / (sset.size || 1) )
                          const union = new Set([...sset,...candTokens]).size || 1
                          const jacc = inter / union
                          if(jacc > bestJaccard) bestJaccard = jacc
                          if(cov > bestCoverage) bestCoverage = cov
                        }
                        const bestSim = Math.max(bestJaccard, bestCoverage)
                        const coverage = bestCoverage || 0
                        if(coverage < 0.98){
                          let threshold = 0.6
                          try{ const selStr = String(c.selector || ''); const depth = await selectorDepthHeuristic(c.selector, info && info.html); const looksLikeBody = /(^|\.|\s)field-name-body(\b|$)/i.test(selStr) || /field[-_]?name[-_]body/i.test(selStr) || /\.body\b/i.test(selStr); if(looksLikeBody || (typeof depth === 'number' && depth >= 6)) threshold = 0.35 }catch(e){}
                          if(bestSim < threshold){ const ok = window.confirm(`Selector ${c.selector} extracted text that differs from the group's full text. Similarity=${bestSim.toFixed(2)} (jaccard=${bestJaccard.toFixed(2)}, coverage=${bestCoverage.toFixed(2)}). Commit anyway?`); if(!ok) throw new Error('user aborted commit') }
                        }
                      }
                    }
                    const commitBody = { host: selectedHost, field: c.field, selector: c.selector }
                    if(activeSnapshotId) commitBody.snapshot_id = activeSnapshotId
                    const commitResp = await fetch(`/api/site_rules/commit`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(commitBody) })
                    if(!commitResp.ok) throw new Error('commit failed')
                  }
                  const jr = await fetch(`/api/reextract_jobs`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ host: selectedHost }) })
                  if(!jr.ok) throw new Error('failed to start reextract job')
                  const jjson = await jr.json()
                  const jobId = jjson.job_id
                  alert('Selectors committed. Re-extract job started: ' + jobId)
                }catch(e){ console.error(e); alert('Failed to commit selectors: ' + (e && e.message ? e.message : String(e))) }
              }}>Commit selections for this story</Button>
            </div>
          </div>
        </div>
      )
    })()

    return (
      <Container maxWidth="lg" sx={{ pt: 3 }}>
        <Typography variant="h5">Domain Reports</Typography>
        <Grid container spacing={2} sx={{ mt: 2 }}>
          <Grid item xs={4}>
            <Paper sx={{ p: 2 }}>
              <List>
                {Object.keys(domainIssues || {}).map((h) => (
                  <ListItemButton key={h} onClick={() => { setSelectedHost(h); setFeedback(((domainIssues)[h] || {}).feedback || { priority: 'low', notes: '' }) }}>
                    <div>
                      <strong>{h}</strong>
                      <div style={{ fontSize: 12, color: '#666' }}>{(() => { const obj = (domainIssues[h]?.issues || {}); return Object.keys(obj||{}).filter(k => Number(obj[k]||0) > 0).length })()} missing field{(() => { const obj = (domainIssues[h]?.issues || {}); return Object.keys(obj||{}).filter(k => Number(obj[k]||0) > 0).length===1 ? '' : 's' })()}</div>
                    </div>
                  </ListItemButton>
                ))}
              </List>
            </Paper>
          </Grid>
          <Grid item xs={8}>
            <Paper sx={{ p: 2 }}>
              {selectedHost ? (
                <div>
                  <Typography variant="h6">{selectedHost}</Typography>
                  {/* show a concise summary instead of raw debug JSON */}
                  <div style={{marginTop:8, fontSize:13, color:'#444'}}>
                    {(() => {
                      const info = domainIssues[selectedHost] || { issues: {} }
                      const issues = info.issues || {}
                      const missingFields = Object.keys(issues).filter(k => Number(issues[k] || 0) > 0)
                      return `${missingFields.length} missing field${missingFields.length===1?'':'s'}`
                    })()}
                  </div>
                  <div style={{marginTop:12}}>
                    {/* we auto-load candidates when snapshots become available; no manual button needed */}
                    {loadingCandidates ? <div style={{fontSize:12, color:'#666'}}>Loading…</div> : null}
                  </div>

                  {storyBlock}
                  {/* Feedback fields temporarily removed (priority and notes) to simplify reviewer workflow */}
                </div>
              ) : (
                <div>Select a host to see details</div>
              )}
            </Paper>
          </Grid>
        </Grid>
      </Container>
    )
  }

  useEffect(()=>{
    async function init(){
      try{
        const [b,h,a] = await Promise.all([
          fetchJson('/api/options/bodyErrors'),
          fetchJson('/api/options/headlineErrors'),
          fetchJson('/api/options/authorErrors')
        ])
  setBodyOptions((b && b.length) ? b : TEST_BODY_OPTIONS)
  setHeadlineOptions((h && h.length) ? h : TEST_HEADLINE_OPTIONS)
  setAuthorOptions((a && a.length) ? a : TEST_AUTHOR_OPTIONS)

  const q = reviewer ? `?reviewer=${encodeURIComponent(reviewer)}` : ''
  const artsResp = await fetchJson('/api/articles' + q)
        // backend returns { count, results: [...] }
        const arts = (artsResp && artsResp.results) ? artsResp.results : []
        // restore any persisted drafts before populating the UI
        try{ loadDraftsFromLocalStorage() }catch(e){}
        setArticles(arts)
        // Light preload: fetch the canonical saved review for the first N articles
        // so the UI can show accurate Save button states immediately.
        try{
          const PRELOAD_N = 10
          const toPreload = Math.min(PRELOAD_N, arts.length)
          const preloadPromises = []
          for(let i=0;i<toPreload;i++){
            const art = arts[i]
            const articleUid = art && (art.id || art.uid || art.host_id) ? (art.id || art.uid || art.host_id) : null
            const url = articleUid ? `/api/reviews?article_uid=${encodeURIComponent(articleUid)}` : `/api/reviews?article_idx=${i}`
            preloadPromises.push(
              fetchJson(url).then(reviews => {
                if (Array.isArray(reviews) && reviews.length) {
                  const review = reviews[0]
                  try{
                    const srvPrimary = (typeof review.primary_rating !== 'undefined') ? review.primary_rating : (typeof review.rating !== 'undefined' ? review.rating : 3)
                    const srvSecondary = (typeof review.secondary_rating !== 'undefined') ? review.secondary_rating : 3
                    const canonical = buildServerPayloadFromUI({ article_uid: articleUid, reviewer: review.reviewer, primary_rating: srvPrimary, secondary_rating: srvSecondary, body_errors: (review.body_errors && review.body_errors.split) ? review.body_errors.split(',') : review.body_errors, headline_errors: (review.headline_errors && review.headline_errors.split) ? review.headline_errors.split(',') : review.headline_errors, author_errors: (review.author_errors && review.author_errors.split) ? review.author_errors.split(',') : review.author_errors, notes: review.notes })
                    const hash = stableStringify(canonical)
                    try{ savedCacheRef.current[String(i)] = { payload: canonical, hash, id: review.id } }catch(e){}
                    if (review.id) savedReviewIdRef.current[String(i)] = review.id
                  }catch(e){ /* ignore per-item errors */ }
                }
              }).catch(()=>{})
            )
          }
          await Promise.all(preloadPromises)
        }catch(e){ /* ignore preload failures */ }

        if (arts && arts.length) {
          await loadArticle(0, { body: b||[], headline: h||[], author: a||[] }, arts)
        }
      }catch(e){
        setError(e.message)
      }
    }
    init()
  }, [fetchJson])

  // Align right-column controls to the vertical center of the left-side text field
  useEffect(()=>{
    // skip rows that are marked static (we'll use CSS centering for those)
    const selector = '.row.align-to-field:not([data-static="true"])'

    function align(){
  // If an option dropdown is open, skip alignment to avoid moving the dropdown
  // (applying transforms to ancestors can create a new containing block for
  // fixed-position elements and cause popups to move/disappear during scroll).
  if (document.querySelector('.multi-dropdown.open')) return
      const rows = Array.from(document.querySelectorAll(selector))
      rows.forEach(row => {
        try{
          // If this row contains a scrollable body area, skip transforms so the
          // right-column tools remain stationary while the body scrolls.
          if (row.querySelector('.scroll-body')) return
          const left = row.querySelector('.input:first-child input, .input:first-child .scroll-body, .input:first-child textarea, .input:first-child .muted')
          const right = row.querySelector('.input:nth-child(2)')
          if (!left || !right) { if (right) { right.style.transform = ''; } return }

          // Compute the vertical center of the visible text inside the left field
          const leftRect = left.getBoundingClientRect()
          const rightRect = right.getBoundingClientRect()
          const cs = window.getComputedStyle(left)
          const paddingTop = parseFloat(cs.paddingTop) || 0
          const borderTop = parseFloat(cs.borderTopWidth) || 0
          // prefer numeric line-height, fallback to font-size
          let lineHeight = parseFloat(cs.lineHeight)
          if (!lineHeight || Number.isNaN(lineHeight)) lineHeight = parseFloat(cs.fontSize) || 16

          // For block elements that may contain rich text (scroll-body), try to measure the first text line if possible
          let textLineTop = null
          let textLineBottom = null
          try{
            if (left.nodeType === 1 && left.firstChild && left.firstChild.nodeType === 3) {
              const range = document.createRange()
              // first visible char
              range.setStart(left.firstChild, 0)
              range.setEnd(left.firstChild, Math.min(1, left.firstChild.length))
              const rrect = range.getBoundingClientRect()
              if (rrect && rrect.height) {
                textLineTop = rrect.top
                lineHeight = rrect.height
              }
              // try to find last visible line by measuring a char near the end
              try{
                const endRange = document.createRange()
                const lastIndex = Math.max(0, left.firstChild.length-1)
                endRange.setStart(left.firstChild, lastIndex)
                endRange.setEnd(left.firstChild, left.firstChild.length)
                const lend = endRange.getBoundingClientRect()
                if (lend && lend.height) textLineBottom = lend.bottom
              }catch(e){ }
            }
          }catch(e){ /* ignore range failures */ }

          const inputTextCenter = (textLineTop !== null)
            ? ((textLineBottom !== null) ? ((textLineTop + textLineBottom)/2) : (textLineTop + (lineHeight/2)))
            : (leftRect.top + paddingTop + borderTop + (lineHeight/2))

          const rightCenter = rightRect.top + rightRect.height/2
          let rowOffset = parseInt(row.dataset.offset || '0', 10) || 0
          if ((row.dataset.autoOffset || row.dataset.autoOffset === '') || row.dataset.autoOffset === 'half' || row.dataset['autoOffset'] === 'half'){
            // support data-auto-offset="half"
            const auto = row.dataset.autoOffset || row.dataset['autoOffset'] || row.getAttribute('data-auto-offset')
            if (auto === 'half'){
              const inputH = left.getBoundingClientRect().height || 0
              rowOffset += Math.round(-inputH/2)
            }
          }
          const delta = Math.round(inputTextCenter - rightCenter + rowOffset)
          right.style.transform = `translateY(${delta}px)`
        }catch(e){ /* ignore measurement errors */ }
      })
    }

    const ro = new ResizeObserver(align)
    // observe rows and potential left fields
    Array.from(document.querySelectorAll(selector)).forEach(r => {
      ro.observe(r)
      const left = r.querySelector('.input:first-child input, .input:first-child .scroll-body, .input:first-child textarea, .input:first-child .muted')
      if (left) ro.observe(left)
    })
    window.addEventListener('resize', align)
    window.addEventListener('scroll', align, true)
    // initial align after render
    setTimeout(align, 40)

    return ()=>{
      window.removeEventListener('resize', align)
      window.removeEventListener('scroll', align, true)
      ro.disconnect()
      Array.from(document.querySelectorAll(selector)).forEach(r=>{ const right = r.querySelector('.input:nth-child(2)'); if (right) right.style.transform = '' })
    }
  }, [article, bodyOptions, headlineOptions, authorOptions, selectedBody, selectedHeadline, selectedAuthor])

  async function loadArticle(index, opts = { body: bodyOptions, headline: headlineOptions, author: authorOptions }, arts = articles){
    const artList = arts.length ? arts : articles
    if (!artList || !artList.length) return
    const art = artList[index]
    setCurrentIndex(index)
    setArticle(art)
  // reset save version when switching articles to avoid cross-article races
  saveVersionRef.current = 0
  setSaveStatus('unsaved')
    setError(null)

    // First, consult in-memory cache so recently saved reviews appear immediately when navigating back
    const cacheEntry = savedCacheRef.current[String(index)]
    if (cacheEntry && cacheEntry.payload) {
      try{
  const p = cacheEntry.payload
        // map ids -> option objects
        const mapIds = (ids, pool) => (Array.isArray(ids) ? ids.filter(id => id !== 'None' && id !== 'NONE').map(id => (pool||[]).find(o=>String(o.id)===String(id)) || { id, label: String(id) }) : [])
        // Apply UI state first (React schedules these updates)
        setSelectedBody(mapIds(p.body, opts.body))
        setSelectedHeadline(mapIds(p.headline, opts.headline))
        setSelectedAuthor(mapIds(p.author, opts.author))
        // populate location options and selections from cache payload if present
        try{
          const cachedLocs = (p.mentioned_locations && Array.isArray(p.mentioned_locations)) ? p.mentioned_locations.map(String) : []
          if (cachedLocs.length) {
            const optsLoc = cachedLocs.map(l => ({ id: `loc:${l}`, label: l }))
            setLocationOptions(optsLoc)
            // keep missingLocations empty unless there are explicit missing_locations
            setSelectedLocations(optsLoc.map(o=>({ id: o.id, label: o.label })))
            setMissingLocations([])
          
          // Populate inferred tags and tag-related state from cached canonical if available
          try{
            const cachedInferred = Array.isArray(p.inferred_tags) ? p.inferred_tags.map(String) : (art && art.inferred_tags_set1 ? String(art.inferred_tags_set1).split(',').map(s=>s.trim()).filter(Boolean) : [])
            setInferredTags((cachedInferred||[]).map(l => ({ id: `tag:${l}`, label: l })))
            setMissingTags(Array.isArray(p.missing_tags) ? p.missing_tags.map(String) : [])
            setRemovedTagLabels(Array.isArray(p.incorrect_tags) ? p.incorrect_tags.map(String) : [])
          }catch(e){}
          } else {
            // fallback to parsing article locmentions to seed options
            const parsed = formatLocationMentions(art && art.locmentions)
            if (parsed && parsed.length){
              const optsLoc = parsed.map(l => ({ id: `loc:${l}`, label: l }))
              setLocationOptions(optsLoc)
              // only preselect if there is no prior selection
                if (!selectedLocations || selectedLocations.length === 0) setSelectedLocations(optsLoc.map(o=>({ id: o.id, label: o.label })))
                setMissingLocations([])
                // If no cached inferred tags, seed from article inferred_tags_set1
                try{
                  const parsedInferred = art && art.inferred_tags_set1 ? String(art.inferred_tags_set1).split(',').map(s=>s.trim()).filter(Boolean) : []
                  if (parsedInferred && parsedInferred.length) setInferredTags(parsedInferred.map(l=>({ id:`tag:${l}`, label:l })))
                }catch(e){}
            }
          }
        }catch(e){}
        setPrimaryRating(p.primary_rating ?? 3)
        setSecondaryRating(p.secondary_rating ?? 3)
  setNotes(p.notes ?? '')
  try{ if (typeof p.reviewer !== 'undefined') setReviewer(p.reviewer || 'local') }catch(e){}
        lastCommittedRef.current = { body: p.body || [], headline: p.headline || [], author: p.author || [], primary_rating: p.primary_rating ?? 3, secondary_rating: p.secondary_rating ?? 3, notes: p.notes ?? '' }
        if (cacheEntry.id) savedReviewIdRef.current[String(index)] = cacheEntry.id
        // Apply authoritative saved payload/hash after React state updates.
        // Set a guard to prevent checkAndSetSaved from running while we apply
        // the server canonical to avoid transient mismatches.
        try{
          applyingServerCanonicalRef.current = true
          setSavedPayload(enrichServerPayload(p, { body: opts.body, headline: opts.headline, author: opts.author }))
          savedHashRef.current = cacheEntry.hash
          setSaveStatus('saved')
          console.debug('[loadArticle] applied cacheEntry payload', { index, articleUid: art && (art.id||art.uid||art.host_id), cacheEntry })
        }catch(e){}
  // Allow React to settle by incrementing tick; useEffect will release guard
  setApplyCanonicalTick(t => t + 1)
      }catch(e){ /* ignore cache failures and fall back to server fetch below */ }
    }

    // still attempt a fresh server fetch to validate/refresh cache
    try{
      // Prefer querying by stable article uid if present
      const articleUid = art && (art.id || art.uid || art.host_id) ? (art.id || art.uid || art.host_id) : null
      const reviews = await fetchJson(articleUid ? `/api/reviews?article_uid=${encodeURIComponent(articleUid)}` : `/api/reviews?article_idx=${index}`) || []
      const review = Array.isArray(reviews) && reviews.length ? reviews[0] : null

      // If no review exists on server, only cold-start if we don't have a cached saved copy
      if (!review) {
        if (!cacheEntry) {
          // no server record and no cache -> cold start
          try{ delete savedReviewIdRef.current[String(index)] }catch(e){}
          setSelectedBody([])
          setSelectedHeadline([])
          setSelectedAuthor([])
          setPrimaryRating(3)
          setSecondaryRating(3)
          setNotes('')
          setSavedPayload(null)
          savedHashRef.current = null
          lastCommittedRef.current = { ...lastCommittedDefault }
          try{ delete savedCacheRef.current[String(index)] }catch(e){}
        } else {
          // server has no record but we have a recent cached save: keep the cached UI as-is
          // ensure cached id remains mapped
          if (cacheEntry.id) savedReviewIdRef.current[String(index)] = cacheEntry.id
        }
      } else {
        // populate from authoritative server record (refresh cache)
  if (review && review.id) savedReviewIdRef.current[String(index)] = review.id
        // compute server canonical and compare with cache (if any)
        let canonical = null
        try{
          const srvPrimary = (typeof review.primary_rating !== 'undefined') ? review.primary_rating : (typeof review.rating !== 'undefined' ? review.rating : 3)
          const srvSecondary = (typeof review.secondary_rating !== 'undefined') ? review.secondary_rating : 3
          // Use the article_uid from the server row when canonicalizing so we don't
          // accidentally capture the current global `article` (which may have
          // changed due to navigation while this async fetch completed).
          const serverArticleUid = review.article_uid || articleUid
          canonical = buildServerPayloadFromUI({ article_uid: serverArticleUid, reviewer: review.reviewer, primary_rating: srvPrimary, secondary_rating: srvSecondary, body_errors: review.body_errors?.split ? review.body_errors.split(',') : review.body_errors, headline_errors: review.headline_errors?.split ? review.headline_errors.split(',') : review.headline_errors, author_errors: review.author_errors?.split ? review.author_errors.split(',') : review.author_errors, notes: review.notes })
        }catch(e){ canonical = null }
        const canonicalHash = canonical ? stableStringify(canonical) : null

        // If we have a cache and it matches the server canonical, keep the cached UI to avoid flicker
          if (cacheEntry && cacheEntry.hash && canonicalHash && cacheEntry.hash === canonicalHash) {
          // ensure the saved id from server is recorded and update cache entry id if needed
          if (review.id) { savedReviewIdRef.current[String(index)] = review.id; savedCacheRef.current[String(index)].id = review.id }
          // no further UI changes needed
        } else {
          // server differs or no cache -> update UI from server
          try{
            const mapIds = (ids, pool) => (Array.isArray(ids) ? ids.filter(id => id !== 'None' && id !== 'NONE').map(id => (pool||[]).find(o=>String(o.id)===String(id)) || { id, label: String(id) }) : [])
            const bodySel = mapIds(review.body_errors?.split ? review.body_errors.split(',') : review.body_errors, opts.body)
            const headSel = mapIds(review.headline_errors?.split ? review.headline_errors.split(',') : review.headline_errors, opts.headline)
            const authSel = mapIds(review.author_errors?.split ? review.author_errors.split(',') : review.author_errors, opts.author)
            const primaryVal = (typeof review.primary_rating !== 'undefined') ? review.primary_rating : (typeof review.rating !== 'undefined' ? review.rating : 3)
            const secondaryVal = (typeof review.secondary_rating !== 'undefined') ? review.secondary_rating : 3

            // Apply selection and slider state first
            setSelectedBody(bodySel)
            setSelectedHeadline(headSel)
            setSelectedAuthor(authSel)
            // Apply mentioned locations from server review if present
            try{
              const serverLocs = review.mentioned_locations && Array.isArray(review.mentioned_locations) ? review.mentioned_locations.map(String) : []
              const serverMissing = review.missing_locations && Array.isArray(review.missing_locations) ? review.missing_locations.map(String) : []
              if (serverLocs.length) {
                const optsLoc = serverLocs.map(l => ({ id: `loc:${l}`, label: l }))
                setLocationOptions(optsLoc)
                setSelectedLocations(optsLoc.map(o=>({ id: o.id, label: o.label })))
                setMissingLocations(serverMissing)
              } else {
                // No locations on server: parse the article's locmentions to seed options
                const parsed = formatLocationMentions(art && art.locmentions)
                if (parsed && parsed.length) {
                  const optsLoc = parsed.map(l => ({ id: `loc:${l}`, label: l }))
                  setLocationOptions(optsLoc)
                  // preselect parsed options only if no saved selections exist
                  if (!selectedLocations || selectedLocations.length === 0) setSelectedLocations(optsLoc.map(o=>({ id: o.id, label: o.label })))
                  setMissingLocations(serverMissing)
                } else {
                  // clear locations if none found
                  setLocationOptions([])
                  setSelectedLocations([])
                  setMissingLocations(serverMissing)
                }
              }
            }catch(e){}
            // Populate inferred tags and tag-related state from server review or article fallback
            try{
              const serverInferred = Array.isArray(review.inferred_tags) ? review.inferred_tags.map(String) : (art && art.inferred_tags_set1 ? String(art.inferred_tags_set1).split(',').map(s=>s.trim()).filter(Boolean) : [])
              setInferredTags((serverInferred||[]).map(l => ({ id: `tag:${l}`, label: l })))
              setMissingTags(Array.isArray(review.missing_tags) ? review.missing_tags.map(String) : [])
              setRemovedTagLabels(Array.isArray(review.incorrect_tags) ? review.incorrect_tags.map(String) : [])
            }catch(e){}
            setPrimaryRating(primaryVal)
            setSecondaryRating(secondaryVal)
            setNotes(review.notes ?? '')
            try{ if (typeof review.reviewer !== 'undefined') setReviewer(review.reviewer || 'local') }catch(e){}
            lastCommittedRef.current = {
              body: bodySel.map(o=>o.id),
              headline: headSel.map(o=>o.id),
              author: authSel.map(o=>o.id),
              primary_rating: primaryVal,
              secondary_rating: secondaryVal,
              notes: review.notes ?? ''
            }
            // mark authoritative server commit time
            try{ lastCommittedRef.current.savedAt = Date.now() }catch(e){}

            // Apply canonical saved payload/hash/cache after React state updates.
            if (canonical) {
              try{
                applyingServerCanonicalRef.current = true
                setSavedPayload(enrichServerPayload(canonical, { body: opts.body, headline: opts.headline, author: opts.author }))
                  try{ if (typeof review?.reviewer !== 'undefined') setReviewer(review.reviewer || 'local') }catch(e){}
                savedHashRef.current = canonicalHash
                try{ savedCacheRef.current[String(index)] = { payload: canonical, hash: canonicalHash, id: review.id } }catch(e){}
                setSaveStatus('saved')
                console.debug('[loadArticle] applied server canonical', { index, articleUid: art && (art.id||art.uid||art.host_id), canonical, canonicalHash })
              }catch(e){ savedHashRef.current = null }
              // Allow React to settle by incrementing tick; useEffect will release guard
              setApplyCanonicalTick(t => t + 1)
            }
            // Use local values for logging so we don't accidentally read stale React state
            console.debug('[loadArticle] set ratings from server', { index, articleUid: art && (art.id||art.uid||art.host_id), primary_rating: primaryVal, secondary_rating: secondaryVal })
          }catch(e){ /* ignore */ }
        }
      }
    }catch(e){
      // On error, prefer the cached UI (if any) otherwise cold-start
      if (!savedCacheRef.current[String(index)]){
        setSelectedBody([])
        setSelectedHeadline([])
        setSelectedAuthor([])
        setPrimaryRating(3)
        setSecondaryRating(3)
        setNotes('')
        lastCommittedRef.current = { ...lastCommittedDefault }
        setSavedPayload(null)
        savedHashRef.current = null
      }
    }

  // apply any transient draft for this article (user edits not yet saved)
    try{
      const draft = draftCacheRef.current[String(index)]
        if(draft){
            const savedAt = (lastCommittedRef.current && lastCommittedRef.current.savedAt) ? lastCommittedRef.current.savedAt : 0
            const modifiedAt = draft.modifiedAt || 0
            // If we have no authoritative saved timestamp, prefer applying the draft.
            const shouldApply = (!savedAt) ? true : (modifiedAt > savedAt)
            if (shouldApply) {
              // map ids -> option objects using provided pools so labels resolve when available
              const mapIds = (ids, pool) => (Array.isArray(ids) ? ids.filter(id => id !== 'None' && id !== 'NONE').map(id => (pool||[]).find(o=>String(o.id)===String(id)) || { id, label: String(id) }) : [])
              if(draft.body) setSelectedBody(mapIds(draft.body, opts.body))
              if(draft.headline) setSelectedHeadline(mapIds(draft.headline, opts.headline))
              if(draft.author) setSelectedAuthor(mapIds(draft.author, opts.author))
              if(typeof draft.primary_rating !== 'undefined') setPrimaryRating(draft.primary_rating)
              if(typeof draft.secondary_rating !== 'undefined') setSecondaryRating(draft.secondary_rating)
              if(typeof draft.notes !== 'undefined') setNotes(draft.notes)
              try{ if (typeof draft.reviewer !== 'undefined') setReviewer(draft.reviewer || 'local') }catch(e){}
              // restore chip and location/tag related draft state if present
              try{ if (Array.isArray(draft.selected_locations) && draft.selected_locations.length) { const locs = draft.selected_locations.map(l => ({ id: `loc:${l}`, label: l })); setLocationOptions(locs); setSelectedLocations(locs) } }catch(e){}
              try{ if (Array.isArray(draft.missing_locations)) setMissingLocations(draft.missing_locations.map(String)) }catch(e){}
              try{ if (Array.isArray(draft.removed_mention_labels)) setRemovedMentionLabels(draft.removed_mention_labels.map(String)) }catch(e){}
              try{ if (Array.isArray(draft.selected_chip_labels)) setSelectedChipLabels(draft.selected_chip_labels.map(String)) }catch(e){}
              try{ if (Array.isArray(draft.inferred_tags) && draft.inferred_tags.length) setInferredTags(draft.inferred_tags.map(l=>({ id: `tag:${l}`, label: l }))) }catch(e){}
              try{ if (Array.isArray(draft.missing_tags)) setMissingTags(draft.missing_tags.map(String)) }catch(e){}
              try{ if (Array.isArray(draft.removed_tag_labels)) setRemovedTagLabels(draft.removed_tag_labels.map(String)) }catch(e){}
              console.debug('[loadArticle] applied draft', { index, articleUid: art && (art.id||art.uid||art.host_id), draft })
            } else {
              console.debug('[loadArticle] skipped draft (older than saved)', { index, articleUid: art && (art.id||art.uid||art.host_id), draft, savedAt })
            }
        }
    }catch(e){ console.warn('failed to apply draft',e) }
  // final sanity log of slider values after applying server/cached and draft
  // Read from the lastCommittedRef or drafts we applied to reflect the values we explicitly set
  const finalPrimary = lastCommittedRef.current.primary_rating ?? primaryRating
  const finalSecondary = lastCommittedRef.current.secondary_rating ?? secondaryRating
  console.debug('[loadArticle] final slider values', { index, articleUid: art && (art.id||art.uid||art.host_id), primaryRating: finalPrimary, secondaryRating: finalSecondary })
  }

  // Debounced save with optimistic update. If the POST fails, revert selections to last committed.
  function scheduleSave(payload, targetIndexOverride){
    return new Promise((resolve, reject) => {
      // bind this save to a specific article index (capture at call-time)
      const targetIndex = (typeof targetIndexOverride !== 'undefined') ? targetIndexOverride : currentIndex
      if (targetIndex === null || typeof targetIndex === 'undefined') return resolve({ ok: false, reason: 'no-target' })
      if (!article) return resolve({ ok: false, reason: 'no-article' })
      // capture the version for this scheduled save; only a matching version may set 'saved'
      const myVersion = saveVersionRef.current
      pendingPayloadRef.current = payload
      setSaveStatus('saving')
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      // capture article UID at schedule time so navigation doesn't change which article the save belongs to
      const capturedArticleUid = article && (article.id || article.uid || article.host_id) ? (article.id || article.uid || article.host_id) : null
      // schedule the actual network write after a short debounce (existing behavior)
      saveTimerRef.current = setTimeout(async ()=>{
        let handlerError = null
        try{
          // Map frontend payload into backend ReviewIn shape:
          // backend expects { reviewer: str, rating?: int, tags?: [str], notes?: str }
          // Prefer the existing reviewer from savedPayload (if any) so optimistic
          // canonical and server canonical use the same reviewer value. Falling
          // back to payload.reviewer then 'local'. This avoids a mismatch where
          // the UI's current reviewer differs from the optimistic saved reviewer
          // and would immediately mark the UI as 'edited'.
          const reviewerToUse = (payload && payload.reviewer) ? payload.reviewer : (savedPayload && savedPayload.reviewer) ? savedPayload.reviewer : 'local'
          const serverPayload = {
            reviewer: reviewerToUse,
            rating: payload.primary_rating ?? payload.rating ?? 3,
            secondary_rating: (typeof payload.secondary_rating !== 'undefined') ? payload.secondary_rating : (typeof payload.secondary_rating !== 'undefined' ? payload.secondary_rating : 3),
            tags: Array.isArray(payload.body_errors) || Array.isArray(payload.headline_errors) || Array.isArray(payload.author_errors)
              ? [
                  ...(payload.body_errors || []).map(String),
                  ...(payload.headline_errors || []).map(String),
                  ...(payload.author_errors || []).map(String)
                ].filter(Boolean)
              : (payload.tags || []),
            notes: payload.notes || ''
          }
          // include mentioned_locations: prefer explicit payload, otherwise use selectedLocations labels
          serverPayload.mentioned_locations = Array.isArray(payload.mentioned_locations) ? payload.mentioned_locations.map(String) : (Array.isArray(selectedLocations) ? selectedLocations.map(o=>String(o.label)) : [])
          // include missing_locations (manual add entries)
          serverPayload.missing_locations = Array.isArray(payload.missing_locations) ? payload.missing_locations.map(String) : (Array.isArray(missingLocations) ? missingLocations.map(String) : [])
          // Also include manual missingLocations into mentioned_locations so they are persisted as mentions in the saved payload
          if (Array.isArray(missingLocations) && missingLocations.length) {
            const existing = Array.isArray(serverPayload.mentioned_locations) ? serverPayload.mentioned_locations : []
            // append any missing entries not already present
            missingLocations.forEach(m => { if (!existing.map(String).includes(String(m))) existing.push(m) })
            serverPayload.mentioned_locations = existing
          }
          // also include explicit error arrays so backend can persist them separately
          serverPayload.body_errors = payload.body_errors || []
          serverPayload.headline_errors = payload.headline_errors || []
          serverPayload.author_errors = payload.author_errors || []
          // If there are no tag selections, send an empty array; server will
          // normalize storage as needed. Avoid client-side 'NONE' placeholders
          // which can create mismatches.
          if (!Array.isArray(serverPayload.tags) || serverPayload.tags.length === 0) {
            serverPayload.tags = []
          }
          // Use POST with article_uid so the backend can upsert by (article_uid, reviewer).
          // Relying on stored per-index IDs can be brittle if the article list/index
          // shifts while a debounced save is pending. POST+article_uid is safe.
          let resp = null
          if (capturedArticleUid) serverPayload.article_uid = capturedArticleUid
          resp = await fetchJson(`/api/articles/${targetIndex}/reviews`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(serverPayload)
          })
          // record created id if backend returned it
          if (resp && resp.id) savedReviewIdRef.current[String(targetIndex)] = resp.id
          // on success, update last committed snapshot (optimistic) and saved payload
          lastCommittedRef.current = {
            body: payload.body_errors || [],
            headline: payload.headline_errors || [],
            author: payload.author_errors || [],
            primary_rating: payload.primary_rating ?? lastCommittedRef.current.primary_rating,
            secondary_rating: payload.secondary_rating ?? lastCommittedRef.current.secondary_rating,
            notes: payload.notes ?? lastCommittedRef.current.notes
          }
          // record optimistic save timestamp
          try{ lastCommittedRef.current.savedAt = Date.now() }catch(e){}
          // record created id if backend returned it (already done above but ensure it's present)
          if (resp && resp.id) savedReviewIdRef.current[String(targetIndex)] = resp.id

          // Optimistically mark saved using our canonical form derived from the payload
          try{
            // Build optimistic canonical using the chosen reviewer (reviewerToUse)
            const optimisticCanonical = buildServerPayloadFromUI({ article_uid: capturedArticleUid, reviewer: reviewerToUse, primary_rating: serverPayload.rating ?? serverPayload.primary_rating, secondary_rating: serverPayload.secondary_rating, body_errors: serverPayload.body_errors || [], headline_errors: serverPayload.headline_errors || [], author_errors: serverPayload.author_errors || [], notes: serverPayload.notes || '' })
            const optimisticHash = stableStringify(optimisticCanonical)
            // Update saved payload/hash immediately so the UI can reflect a saved state.
            setSavedPayload(enrichServerPayload(optimisticCanonical, { body: bodyOptions, headline: headlineOptions, author: authorOptions }))
            savedHashRef.current = optimisticHash
            try{ savedCacheRef.current[String(targetIndex)] = { payload: optimisticCanonical, hash: optimisticHash, id: savedReviewIdRef.current[String(targetIndex)] || resp?.id } }catch(e){}
            // Set saved status so the button updates. We still keep versioning guards elsewhere
            setSaveStatus('saved')
            console.debug('[scheduleSave] optimistic saved', { targetIndex, capturedArticleUid, optimisticHash, optimisticCanonical })
            try{ checkAndSetSaved() }catch(e){}
          }catch(e){}

          // Filter out any labels the user explicitly removed so they won't be persisted
          if (Array.isArray(removedMentionLabels) && removedMentionLabels.length) {
            const removedSet = new Set(removedMentionLabels.map(String))
            serverPayload.mentioned_locations = (serverPayload.mentioned_locations || []).filter(l => !removedSet.has(String(l)))
            serverPayload.missing_locations = (serverPayload.missing_locations || []).filter(l => !removedSet.has(String(l)))
          }

          // Compute incorrect_locations: any prepopulated parsed labels the user removed
          try{
            const parsed = (formatLocationMentions(article?.locmentions) || '').split(',').map(s=>s.trim()).filter(Boolean)
            const removedSet = new Set((removedMentionLabels||[]).map(String))
            const incorrect = parsed.filter(p => removedSet.has(String(p)))
            if (incorrect && incorrect.length) serverPayload.incorrect_locations = incorrect
            else serverPayload.incorrect_locations = []
          }catch(e){ serverPayload.incorrect_locations = [] }

          // Try to verify persistence by fetching the latest review for this article.
          try{
            // AUTHORITATIVE-BY-ID: prefer fetching the exact review by id returned from POST/PUT
            const tryFetchById = async (id, timeoutMs = 4000) => {
              const url = `/api/reviews?id=${encodeURIComponent(id)}`
              // simple timeout wrapper
              const timer = new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), timeoutMs))
              // the fetchJson returns parsed JSON; if the endpoint returns an array, normalize
              const fetchPromise = fetchJson(url)
              const result = await Promise.race([fetchPromise, timer])
              return result
            }

            const capturedSaveId = resp && resp.id ? resp.id : null
            let latest = null
            // If the POST responded with a canonical saved row (not just an id), use that as authoritative
            // Backend now returns a normalized review object where fields like article_uid, tags,
            // body_errors/headline_errors/author_errors are already arrays. Prefer that to avoid
            // an extra by-id fetch and potential mismatch windows.
            let usedPostCanonical = false
            if (resp && (typeof resp.article_uid !== 'undefined' || typeof resp.tags !== 'undefined' || typeof resp.body_errors !== 'undefined')) {
              latest = resp
              usedPostCanonical = true
              console.debug('[scheduleSave] using POST response canonical as authoritative', { capturedSaveId, latest })
            }
            // compute the canonical UI snapshot for the capturedArticleUid (navigation-safe)
            const currentCanonicalCaptured = stableStringify(buildServerPayloadFromUI({ article_uid: capturedArticleUid }))
            if (capturedSaveId && !usedPostCanonical) {
              // attempt by-id fetch; if the returned row doesn't match our captured UI,
              // retry once after a short backoff before falling back to article_uid query.
              try{
                let attempt = 0
                let ok = false
                while(attempt < 2 && !ok){
                  try{
                    const byId = await tryFetchById(capturedSaveId, 4000)
                    if (Array.isArray(byId) && byId.length) latest = byId[0]
                    else if (byId && typeof byId === 'object' && byId.id) latest = byId
                    else latest = null
                    if (latest) {
                      // If the returned row is for a different article, don't retry by-id;
                      // this commonly happens when the DB returned a different recent
                      // row id and comparing by-id is futile — fall back to article_uid.
                      if (capturedArticleUid && latest.article_uid && String(latest.article_uid) !== String(capturedArticleUid)) {
                        console.debug('[scheduleSave] by-id returned row for different article; falling back to article_uid query', { capturedSaveId, latestArticleUid: latest.article_uid, capturedArticleUid })
                        latest = null
                        break
                      }
                      // quick canonical comparison using capturedArticleUid to avoid races
                      const tentativeCanonical = buildServerPayloadFromUI({ article_uid: latest.article_uid || capturedArticleUid, reviewer: latest.reviewer, primary_rating: latest.primary_rating ?? latest.rating, secondary_rating: latest.secondary_rating ?? latest.secondary_rating, body_errors: (latest.body_errors && latest.body_errors.split) ? latest.body_errors.split(',') : latest.body_errors, headline_errors: (latest.headline_errors && latest.headline_errors.split) ? latest.headline_errors.split(',') : latest.headline_errors, author_errors: (latest.author_errors && latest.author_errors.split) ? latest.author_errors.split(',') : latest.author_errors, notes: latest.notes })
                      const tentativeHash = stableStringify(tentativeCanonical)
                      if (tentativeHash === currentCanonicalCaptured) {
                        ok = true
                        console.debug('[scheduleSave] by-id verification matched current UI', { capturedSaveId, tentativeHash })
                        break
                      } else {
                        // mismatch: maybe the DB write hasn't fully propagated for id reads yet; retry once
                        console.debug('[scheduleSave] by-id verification mismatch, will retry once', { capturedSaveId, tentativeHash, currentCanonicalCaptured })
                        attempt++
                        if (attempt < 2) await new Promise(r => setTimeout(r, 300))
                        else break
                      }
                    } else {
                      // nothing returned by id
                      break
                    }
                  }catch(e){
                    // fetch error; allow one retry
                    attempt++
                    if (attempt < 2) await new Promise(r => setTimeout(r, 300))
                  }
                }
              }catch(e){ latest = null }
            }

            // fallback: query by article_uid if we couldn't fetch a matching-by-id row
            if (!latest) {
              console.debug('[scheduleSave] falling back to article_uid query for verification', { capturedArticleUid, capturedSaveId })
              const reviews = await fetchJson(capturedArticleUid ? `/api/reviews?article_uid=${encodeURIComponent(capturedArticleUid)}` : `/api/reviews?article_idx=${targetIndex}`) || []
              latest = Array.isArray(reviews) && reviews.length ? reviews[0] : null
            } else {
              console.debug('[scheduleSave] used by-id verification path', { capturedSaveId, latestId: latest.id })
            }

            // Compute canonical payload for the latest server row and compare via stable stringify
            const canonicalLatest = latest ? buildServerPayloadFromUI({ article_uid: latest.article_uid || capturedArticleUid, reviewer: latest.reviewer, primary_rating: latest.primary_rating ?? latest.rating, secondary_rating: latest.secondary_rating ?? latest.secondary_rating, body_errors: (latest.body_errors && latest.body_errors.split) ? latest.body_errors.split(',') : latest.body_errors, headline_errors: (latest.headline_errors && latest.headline_errors.split) ? latest.headline_errors.split(',') : latest.headline_errors, author_errors: (latest.author_errors && latest.author_errors.split) ? latest.author_errors.split(',') : latest.author_errors, notes: latest.notes }) : null
            const latestHash = canonicalLatest ? stableStringify(canonicalLatest) : null
            // mark saved only if the canonical representation matches our UI (and no newer edits happened)
            const currentCanonical = stableStringify(buildServerPayloadFromUI({ article_uid: article && (article.id || article.uid || article.host_id) ? (article.id || article.uid || article.host_id) : undefined }))
            if (saveVersionRef.current === myVersion && latestHash && currentCanonical === latestHash){
              setSaveStatus('saved')
              setSavedPayload(enrichServerPayload(canonicalLatest, { body: bodyOptions, headline: headlineOptions, author: authorOptions }))
              savedHashRef.current = latestHash
              try{ checkAndSetSaved() }catch(e){}
              // successful save: remove any transient draft for this article
              try{
                const dkey = String(targetIndex)
                const draft = draftCacheRef.current[dkey]
                // Only remove the draft if it matches the snapshot we just committed;
                // if the user edited after the save, keep the newer draft.
                if (draft) {
                  const equalArrays = (a,b) => {
                    if (!Array.isArray(a) && !Array.isArray(b)) return true
                    if (!Array.isArray(a) || !Array.isArray(b)) return false
                    if (a.length !== b.length) return false
                    for(let i=0;i<a.length;i++) if (String(a[i]) !== String(b[i])) return false
                    return true
                  }
                  const matches = equalArrays(draft.body, lastCommittedRef.current.body) && equalArrays(draft.headline, lastCommittedRef.current.headline) && equalArrays(draft.author, lastCommittedRef.current.author) && (String(draft.primary_rating) === String(lastCommittedRef.current.primary_rating)) && (String(draft.secondary_rating) === String(lastCommittedRef.current.secondary_rating)) && (String(draft.notes || '') === String(lastCommittedRef.current.notes || ''))
                  if (matches) { delete draftCacheRef.current[dkey]; saveDraftsToLocalStorage(); console.debug('[scheduleSave] removed draft after save', { targetIndex, dkey }) } else { console.debug('[scheduleSave] kept draft after save (user edited after save)', { targetIndex, dkey, draft, lastCommitted: lastCommittedRef.current }) }
                }
              }catch(e){}
              // update savedAt from server-verified row
              try{ lastCommittedRef.current.savedAt = Date.now() }catch(e){}
              console.debug('[scheduleSave] verified persisted', { targetIndex, capturedArticleUid, latestHash, currentCanonical })
            } else {
              // do not mark saved if the server copy differs from the current UI
              if (saveVersionRef.current === myVersion){
                // If our POST returned an id, treat this as a successful save from the
                // user's perspective even if the canonical representation differs.
                setSaveStatus((resp && resp.id) ? 'saved' : 'unsaved')
                // update saved payload/hash from server so UI shows last saved (server)
                // prefer canonicalLatest (id arrays); if missing, build canonical from the serverPayload shape
                const canonicalForCache = canonicalLatest || buildServerPayloadFromUI({
                  article_uid: capturedArticleUid,
                  body_errors: serverPayload.body_errors || [],
                  headline_errors: serverPayload.headline_errors || [],
                  author_errors: serverPayload.author_errors || [],
                  primary_rating: serverPayload.rating ?? serverPayload.primary_rating,
                  secondary_rating: serverPayload.secondary_rating,
                  notes: serverPayload.notes
                })
                setSavedPayload(enrichServerPayload(canonicalForCache, { body: bodyOptions, headline: headlineOptions, author: authorOptions }))
                savedHashRef.current = latestHash || stableStringify(canonicalForCache)
                try{ savedCacheRef.current[String(targetIndex)] = { payload: canonicalForCache, hash: savedHashRef.current, id: latest?.id || savedReviewIdRef.current[String(targetIndex)] || resp?.id } }catch(e){}
                console.debug('[scheduleSave] mismatch persisted vs UI', { targetIndex, capturedArticleUid, latestHash, currentCanonical, canonicalForCache })
                try{ lastCommittedRef.current.savedAt = Date.now() }catch(e){}
                try{ checkAndSetSaved() }catch(e){}
              }
            }
          }catch(e){
            // If verification fails, only mark saved if no newer edits
            if (saveVersionRef.current === myVersion) {
              setSaveStatus('saved')
              const canonicalForCacheFail = buildServerPayloadFromUI({
                body_errors: serverPayload.body_errors || [],
                headline_errors: serverPayload.headline_errors || [],
                author_errors: serverPayload.author_errors || [],
                primary_rating: serverPayload.rating ?? serverPayload.primary_rating,
                secondary_rating: serverPayload.secondary_rating,
                notes: serverPayload.notes
              })
              setSavedPayload(enrichServerPayload(canonicalForCacheFail, { body: bodyOptions, headline: headlineOptions, author: authorOptions }))
              try{ savedCacheRef.current[String(targetIndex)] = { payload: canonicalForCacheFail, hash: stableStringify(canonicalForCacheFail), id: resp?.id || savedReviewIdRef.current[String(targetIndex)] } }catch(e){}
              try{ checkAndSetSaved() }catch(e){}
              // remove persisted draft on optimistic success only if it matches the committed snapshot
              try{
                const dkey = String(targetIndex)
                const draft = draftCacheRef.current[dkey]
                if (draft) {
                  const equalArrays = (a,b) => {
                    if (!Array.isArray(a) && !Array.isArray(b)) return true
                    if (!Array.isArray(a) || !Array.isArray(b)) return false
                    if (a.length !== b.length) return false
                    for(let i=0;i<a.length;i++) if (String(a[i]) !== String(b[i])) return false
                    return true
                  }
                  const matches = equalArrays(draft.body, lastCommittedRef.current.body) && equalArrays(draft.headline, lastCommittedRef.current.headline) && equalArrays(draft.author, lastCommittedRef.current.author) && (String(draft.primary_rating) === String(lastCommittedRef.current.primary_rating)) && (String(draft.secondary_rating) === String(lastCommittedRef.current.secondary_rating)) && (String(draft.notes || '') === String(lastCommittedRef.current.notes || ''))
                  if (matches) { delete draftCacheRef.current[dkey]; saveDraftsToLocalStorage(); console.debug('[scheduleSave] removed optimistic draft after save', { targetIndex, dkey }) } else { console.debug('[scheduleSave] kept optimistic draft after save', { targetIndex, dkey, draft, lastCommitted: lastCommittedRef.current }) }
                }
              }catch(e){}
              try{ lastCommittedRef.current.savedAt = Date.now() }catch(e){}
            }
          }
        }catch(e){
          handlerError = e
          setSaveStatus('error')
          setError(e.message)
          // revert selections to last committed snapshot
          const restore = (ids, pool) => (Array.isArray(ids) ? ids.map(id => (pool||[]).find(o=>String(o.id)===String(id)) || { id, label: String(id) }) : [])
          setSelectedBody(restore(lastCommittedRef.current.body, bodyOptions))
          setSelectedHeadline(restore(lastCommittedRef.current.headline, headlineOptions))
          setSelectedAuthor(restore(lastCommittedRef.current.author, authorOptions))
          setPrimaryRating(lastCommittedRef.current.primary_rating ?? 5)
          setSecondaryRating(lastCommittedRef.current.secondary_rating ?? 5)
          setNotes(lastCommittedRef.current.notes ?? '')
        } finally {
          pendingPayloadRef.current = null
          saveTimerRef.current = null
          if (handlerError) return reject(handlerError)
          return resolve({ ok: true })
        }
      }, 600)
    })
  }

  // -------------------------
  // Debounced autosave helper
  // -------------------------
  const AUTOSAVE_DELAY_MS = 5000 // 5s
  const autosaveTimerRef = React.useRef(null)
  const pendingAutosaveFieldsRef = React.useRef(null)
  const [autosaveStatus, setAutosaveStatus] = React.useState('idle') // 'idle'|'pending'|'saving'|'saved'|'error'

  function buildMinimalPayloadFromFields(fields){
    // If no fields provided, return a full payload for explicit saves/flushes
    if (!fields || fields.length === 0) return buildServerPayloadFromUI()
    const p = {}
    for (const f of fields){
      if (f === 'notes') p.notes = notes
      else if (f === 'primary_rating') p.primary_rating = primaryRating
      else if (f === 'secondary_rating') p.secondary_rating = secondaryRating
      else if (f === 'mentioned_locations') p.mentioned_locations = Array.isArray(selectedLocations) ? selectedLocations.map(o=>String(o.label)) : []
      else if (f === 'missing_locations') p.missing_locations = Array.isArray(missingLocations) ? missingLocations.map(String) : []
      else if (f === 'tags') p.tags = Array.isArray(inferredTags) ? inferredTags.map(o=>String(o.label)) : []
      else if (f === 'body_errors') p.body_errors = Array.isArray(selectedBody) ? selectedBody.map(o=>o.id) : []
      else if (f === 'headline_errors') p.headline_errors = Array.isArray(selectedHeadline) ? selectedHeadline.map(o=>o.id) : []
      else if (f === 'author_errors') p.author_errors = Array.isArray(selectedAuthor) ? selectedAuthor.map(o=>o.id) : []
    }
    return p
  }

  function debouncedScheduleSave(fields){
    // store requested fields; only the latest set will be used when timer fires
    pendingAutosaveFieldsRef.current = fields
    // mark pending for UI
    try{ setAutosaveStatus('pending') }catch(e){}
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current)
    autosaveTimerRef.current = setTimeout(async ()=>{
      autosaveTimerRef.current = null
      const fld = pendingAutosaveFieldsRef.current || null
      pendingAutosaveFieldsRef.current = null
      try{
        setAutosaveStatus('saving')
        const payload = buildMinimalPayloadFromFields(fld)
        // reuse existing scheduleSave which already does optimistic update and verification
        try{
          await scheduleSave(payload)
          setAutosaveStatus('saved')
        }catch(e){
          console.debug('debouncedScheduleSave scheduleSave error', e)
          setAutosaveStatus('error')
        }
      }catch(e){ console.debug('debouncedScheduleSave error', e); setAutosaveStatus('error') }
    }, AUTOSAVE_DELAY_MS)
  }

  function flushAutosaveImmediate(){
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current)
      autosaveTimerRef.current = null
      const fld = pendingAutosaveFieldsRef.current || null
      pendingAutosaveFieldsRef.current = null
      try{ const payload = buildMinimalPayloadFromFields(fld); scheduleSave(payload) }catch(e){}
    }
  }

  // Send pending autosave via navigator.sendBeacon as a best-effort flush on unload/visibility change
  function sendPendingViaBeacon(){
    try{
      const fld = pendingAutosaveFieldsRef.current || null
      const payload = buildMinimalPayloadFromFields(fld)
      // attach article uid if possible
      try{ if (article && (article.id || article.uid || article.host_id)) payload.article_uid = article.id || article.uid || article.host_id }catch(e){}
      const url = `/api/articles/${currentIndex}/reviews`
      const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' })
      if (navigator && typeof navigator.sendBeacon === 'function') {
        navigator.sendBeacon(url, blob)
        return true
      }
    }catch(e){ console.debug('sendPendingViaBeacon failed', e) }
    return false
  }

  // Hook lifecycle events to flush pending autosave
  React.useEffect(()=>{
    const onBeforeUnload = (e) => {
      // try beacon, then flush immediate (best-effort)
      try{ sendPendingViaBeacon() }catch(e){}
      try{ flushAutosaveImmediate() }catch(e){}
      // allow default behavior; no need to cancel
    }
    const onVisibilityChange = () => {
      if (document.hidden) {
        try{ sendPendingViaBeacon() }catch(e){}
        try{ flushAutosaveImmediate() }catch(e){}
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [currentIndex, article])

  function onBodyChange(newVal){
  setSelectedBody(newVal)
  // entering new data clears saved state until it's persisted again and advances save version
  saveVersionRef.current = (saveVersionRef.current || 0) + 1
  // Recalculate saved-ness immediately (UI-only)
  // persist transient draft
  try{ draftCacheRef.current[String(currentIndex)] = { body: newVal.map(o=>o.id), headline: lastCommittedRef.current.headline, author: lastCommittedRef.current.author, primary_rating: primaryRating, secondary_rating: secondaryRating, notes, reviewer: reviewer, selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label) : [], missing_locations: Array.isArray(missingLocations)? missingLocations.map(String):[], removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], inferred_tags: Array.isArray(inferredTags)? inferredTags.map(t=>t.label):[], missing_tags: Array.isArray(missingTags)? missingTags.map(String):[], removed_tag_labels: Array.isArray(removedTagLabels)? removedTagLabels.map(String):[], modifiedAt: Date.now() } }catch(e){}
  try{ saveDraftsToLocalStorage() }catch(e){}
  checkAndSetSaved()
  }
  function onHeadlineChange(newVal){
  setSelectedHeadline(newVal)
  saveVersionRef.current = (saveVersionRef.current || 0) + 1
  try{ draftCacheRef.current[String(currentIndex)] = { body: lastCommittedRef.current.body, headline: newVal.map(o=>o.id), author: lastCommittedRef.current.author, primary_rating: primaryRating, secondary_rating: secondaryRating, notes, reviewer: reviewer, selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label) : [], missing_locations: Array.isArray(missingLocations)? missingLocations.map(String):[], removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], inferred_tags: Array.isArray(inferredTags)? inferredTags.map(t=>t.label):[], missing_tags: Array.isArray(missingTags)? missingTags.map(String):[], removed_tag_labels: Array.isArray(removedTagLabels)? removedTagLabels.map(String):[], modifiedAt: Date.now() } }catch(e){}
  try{ saveDraftsToLocalStorage() }catch(e){}
  checkAndSetSaved()
  }
  function onAuthorChange(newVal){
  setSelectedAuthor(newVal)
  saveVersionRef.current = (saveVersionRef.current || 0) + 1
  try{ draftCacheRef.current[String(currentIndex)] = { body: lastCommittedRef.current.body, headline: lastCommittedRef.current.headline, author: newVal.map(o=>o.id), primary_rating: primaryRating, secondary_rating: secondaryRating, notes, reviewer: reviewer, selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label) : [], missing_locations: Array.isArray(missingLocations)? missingLocations.map(String):[], removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], inferred_tags: Array.isArray(inferredTags)? inferredTags.map(t=>t.label):[], missing_tags: Array.isArray(missingTags)? missingTags.map(String):[], removed_tag_labels: Array.isArray(removedTagLabels)? removedTagLabels.map(String):[], modifiedAt: Date.now() } }catch(e){}
  try{ saveDraftsToLocalStorage() }catch(e){}
  checkAndSetSaved()
  }

  function onPrimaryRating(v){ saveVersionRef.current = (saveVersionRef.current || 0) + 1; setPrimaryRating(v); try{ draftCacheRef.current[String(currentIndex)] = { body: lastCommittedRef.current.body, headline: lastCommittedRef.current.headline, author: lastCommittedRef.current.author, primary_rating: v, secondary_rating: secondaryRating, notes, modifiedAt: Date.now() }; saveDraftsToLocalStorage(); }catch(e){}; checkAndSetSaved(); debouncedScheduleSave(['primary_rating']); }
  function onSecondaryRating(v){ saveVersionRef.current = (saveVersionRef.current || 0) + 1; setSecondaryRating(v); try{ draftCacheRef.current[String(currentIndex)] = { body: lastCommittedRef.current.body, headline: lastCommittedRef.current.headline, author: lastCommittedRef.current.author, primary_rating: primaryRating, secondary_rating: v, notes, reviewer: reviewer, modifiedAt: Date.now() }; saveDraftsToLocalStorage(); }catch(e){}; checkAndSetSaved(); debouncedScheduleSave(['secondary_rating']); }
  function onNotesChange(s){
    // update local state only; avoid autosaving on every keystroke
    setNotes(s)
  saveVersionRef.current = (saveVersionRef.current || 0) + 1
    try{ draftCacheRef.current[String(currentIndex)] = { body: lastCommittedRef.current.body, headline: lastCommittedRef.current.headline, author: lastCommittedRef.current.author, primary_rating: primaryRating, secondary_rating: secondaryRating, notes: s, reviewer: reviewer, modifiedAt: Date.now() } }catch(e){}
  // update saved indicator live while typing
  try{ saveDraftsToLocalStorage() }catch(e){}
  checkAndSetSaved()
  // debounce server autosave for notes
  debouncedScheduleSave(['notes'])
  }

  // Re-evaluate saved-ness whenever the main editable state changes (fallback)
  useEffect(()=>{ checkAndSetSaved() }, [selectedBody, selectedHeadline, selectedAuthor, primaryRating, secondaryRating, notes])

  function onNotesBlur(){
    // save when the user leaves the notes field
  const currentHash = stableStringify(buildServerPayloadFromUI({ notes, article_uid: article && (article.id || article.uid || article.host_id) ? (article.id || article.uid || article.host_id) : undefined }))
  setSaveStatus(currentHash === savedHashRef.current ? 'saved' : 'unsaved')
  // Do not autosave on blur; only update UI saved-state. Manual save via the Save button triggers persistence.
  }

  // Whenever article.locmentions changes, prepopulate locationOptions (UI only)
  useEffect(()=>{
    try{
      const raw = article?.locmentions
      if (!raw) { setLocationOptions([]); setSelectedLocations([]); return }
      const parsedStr = formatLocationMentions(raw)
      // formatLocationMentions returns a joined string; split by comma to get items
      const parts = parsedStr.split(',').map(p=>p.trim()).filter(Boolean)
      const items = parts.map(p => ({ id: `parsed:${p.replace(/\s+/g,'_')}`, label: p }))
      setLocationOptions(items)
      // Preselect parsed items as chips if there are no existing selections so the user
      // sees the parsed mentions and can de-select any they don't want.
      try{
        if (!selectedLocations || (Array.isArray(selectedLocations) && selectedLocations.length === 0)) {
          setSelectedLocations(items)
        }
      }catch(e){ /* ignore */ }
    }catch(e){ console.debug('failed to prepopulate location options', e) }
  }, [article?.locmentions])

  function addLocationFromInput(){
    try{
      const txt = (locationInput||'').trim()
      if (!txt) return
      const id = `new:${txt.replace(/\s+/g,'_')}`
      const obj = { id, label: txt }
      // ensure local options contains it
      setLocationOptions(prev => { if (prev.find(p=>p.id===obj.id)) return prev; return [...prev, obj] })
      // deterministically update missingLocations and use the new array for draft
      const prevMissing = Array.isArray(missingLocations) ? missingLocations : []
      if (!prevMissing.map(String).includes(String(txt))) {
        const newMissing = [...prevMissing, txt]
        setMissingLocations(newMissing)
        // If user previously removed this label, un-remove it (they re-added)
        setRemovedMentionLabels(prev => prev.filter(p => String(p) !== String(txt)))
        try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, missing_locations: newMissing.map(String), selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label):[], removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
      }
      setLocationInput('')
      // mark draft/save state change
      saveVersionRef.current = (saveVersionRef.current || 0) + 1
      try{ checkAndSetSaved() }catch(e){}
  // schedule autosave for mentioned/missing locations
  debouncedScheduleSave(['mentioned_locations','missing_locations'])
    }catch(e){ console.debug('failed to add location', e) }
  }

  function toggleChip(label){
    setSelectedChipLabels(prev => {
      const next = (prev && prev.map(String).includes(String(label))) ? prev.filter(p=>String(p)!==String(label)) : [...(prev||[]), label]
      try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, selected_chip_labels: Array.isArray(next)? next.map(String):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
      return next
    })
  }

  function removeChip(label){
    // add to removed list so it won't be included in saves
    setRemovedMentionLabels(prev => { if (prev && prev.map(String).includes(String(label))) return prev; return [...(prev||[]), label] })
    // also remove from missingLocations if present
    setMissingLocations(prev => (Array.isArray(prev) ? prev.filter(p=>String(p)!==String(label)) : prev))
    // ensure chip not left selected
    setSelectedChipLabels(prev => (Array.isArray(prev) ? prev.filter(p=>String(p)!==String(label)) : prev))
  // persist draft change (include chip state)
  try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, missing_locations: (Array.isArray(missingLocations) ? missingLocations.filter(p=>String(p)!==String(label)) : []), selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label):[], removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
  // schedule autosave to reflect removal
  debouncedScheduleSave(['mentioned_locations','missing_locations'])
  }

  // Format location mentions into grouped geographic levels: Countries, States, Cities
  function formatLocationMentions(locs){
    if (!locs) return ''
    const arr = Array.isArray(locs) ? locs : (typeof locs === 'string' ? (locs ? [locs] : []) : [])
    if (!arr.length) return ''

    // Minimal US states map (abbr -> full)
    const stateMap = {
      AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',CO:'Colorado',CT:'Connecticut',DE:'Delaware',FL:'Florida',GA:'Georgia',HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',MT:'Montana',NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming'
    }
    const stateFullSet = new Set(Object.values(stateMap).map(s=>s.toLowerCase()))
    const countryKeywords = ['united states','usa','canada','mexico','united kingdom','uk']

    const countries = []
    const states = []
    const counties = []
    const cities = []
    const others = []

    // Helper to push unique
    const pushUnique = (arr, val) => { if (!val) return; if (!arr.includes(val)) arr.push(val) }

    arr.forEach(item => {
      if (!item) return

      // If item is an object, try structured extraction first
      if (typeof item === 'object'){
        // common shapes: { city, state, county, abbr, country, name, label }
        const rawName = item.name || item.label || ''
        // include additional common city keys
        const city = (item.city || item.city_name || item.locality || item.municipality || item.town || item.place || item.village || '').toString().trim()
        const county = (item.county || item.county_name || item.countyname || '').toString().trim()
        const stateField = (item.state || item.region || item.admin1 || item.state_name || '').toString().trim()
        const abbr = (item.abbr || item.state_code || '').toString().trim()
        const country = (item.country || item.country_name || '').toString().trim()

        // If we have a country
        if (country){ pushUnique(countries, country); }

        // Resolve state from abbr or name
        let resolvedState = ''
        if (abbr && stateMap[abbr.toUpperCase()]) resolvedState = stateMap[abbr.toUpperCase()]
        else if (stateField){ resolvedState = stateField }
        // push county/state/city in an order that prefers higher-level first
        if (resolvedState) pushUnique(states, resolvedState)
        if (county) pushUnique(counties, county)
        if (city) pushUnique(cities, city)

        // if structured object had no clear fields but rawName looks useful, fall back
        if (!resolvedState && !city && !county && rawName){
          const name = String(rawName).replace(/mentioned[:\s-]*/i,'').trim()
          if (name) pushUnique(others, name)
        }

        return
      }

      // Normalize string values: strip quotes/brackets and 'mentioned' boilerplate
      let s = String(item).trim()
      s = s.replace(/^[["'\s]+|[\]"'\s]+$/g, '').trim()
      s = s.replace(/mentioned\s*[:\-]?\s*/i, '').trim()

      // If the string looks like a Python list-of-dicts (e.g. "[{'city': None, ...}, {...}]")
      if (s.startsWith('[') && s.includes('{')){
        const objRe = /\{[^}]*\}/g
        const matches = s.match(objRe) || []
        for(const objStr of matches){
          const parsed = {}
          const kvRe = /['"]?(\w+)['"]?\s*:\s*(\[[^\]]*\]|[^,}]+)/g
          let m
          while((m = kvRe.exec(objStr)) !== null){
            const key = m[1].trim().toLowerCase()
            let rawVal = m[2].trim()
            rawVal = rawVal.replace(/^[\s,]+|[\s,}]+$/g, '').trim()
            if (/^None$/i.test(rawVal) || /^null$/i.test(rawVal) || rawVal === ''){ parsed[key] = ''; continue }
            if (rawVal.startsWith('[') && rawVal.endsWith(']')){
              const inner = rawVal.slice(1,-1)
              const items = inner.split(',').map(it=>it.trim().replace(/^['\"]+|['\"]+$/g,'').trim()).filter(it=>it && !/^None$/i.test(it) && !/^null$/i.test(it))
              parsed[key] = items
            } else {
              parsed[key] = rawVal.replace(/^['\"]+|['\"]+$/g,'').trim()
            }
          }
          const pushParsed = (keyCandidates, bucket, mapAbbr=false) => {
            for(const k of keyCandidates){
              const v = parsed[k]
              if (!v) continue
              if (Array.isArray(v)) v.forEach(x => { if (mapAbbr && stateMap[String(x).toUpperCase()]) pushUnique(bucket, stateMap[String(x).toUpperCase()]); else pushUnique(bucket, x) })
              else { if (mapAbbr && stateMap[String(v).toUpperCase()]) pushUnique(bucket, stateMap[String(v).toUpperCase()]); else pushUnique(bucket, v) }
            }
          }
          pushParsed(['state','region','admin1','state_name'], states, true)
          if (!states.length) pushParsed(['abbr','state_code'], states, true)
          pushParsed(['county','county_name','countyname','counties'], counties)
          pushParsed(['city','city_name','locality','municipality','town','place','village','cities','places','locations'], cities)
        }
        return
      }

      // If the string contains multiple brace-delimited objects (e.g. "{...}, {...}") parse each separately
      const objRe = /\{[^}]*\}/g
      const objMatches = s.match(objRe) || []
      if (objMatches.length > 1) {
        for(const objStr of objMatches){
          const parsed = {}
          const kvRe = /['"]?(\w+)['"]?\s*:\s*(\[[^\]]*\]|[^,}]+)/g
          let m
          while((m = kvRe.exec(objStr)) !== null){
            const key = m[1].trim().toLowerCase()
            let rawVal = m[2].trim()
            rawVal = rawVal.replace(/^[\s,]+|[\s,}]+$/g, '').trim()
            if (/^None$/i.test(rawVal) || /^null$/i.test(rawVal) || rawVal === ''){ parsed[key] = ''; continue }
            if (rawVal.startsWith('[') && rawVal.endsWith(']')){
              const inner = rawVal.slice(1,-1)
              const items = inner.split(',').map(it=>it.trim().replace(/^['\"]+|['\"]+$/g,'').trim()).filter(it=>it && !/^None$/i.test(it) && !/^null$/i.test(it))
              parsed[key] = items
            } else {
              parsed[key] = rawVal.replace(/^['\"]+|['\"]+$/g,'').trim()
            }
          }
          const pushParsed = (keyCandidates, bucket, mapAbbr=false) => {
            for(const k of keyCandidates){
              const v = parsed[k]
              if (!v) continue
              if (Array.isArray(v)) v.forEach(x => { if (mapAbbr && stateMap[String(x).toUpperCase()]) pushUnique(bucket, stateMap[String(x).toUpperCase()]); else pushUnique(bucket, x) })
              else { if (mapAbbr && stateMap[String(v).toUpperCase()]) pushUnique(bucket, stateMap[String(v).toUpperCase()]); else pushUnique(bucket, v) }
            }
          }
          pushParsed(['state','region','admin1','state_name'], states, true)
          if (!states.length) pushParsed(['abbr','state_code'], states, true)
          pushParsed(['county','county_name','countyname','counties'], counties)
          pushParsed(['city','city_name','locality','municipality','town','place','village','cities','places','locations'], cities)
        }
        return
      }

      // If the string looks like a Python dict (e.g. "{'city': None, 'state': 'Missouri', 'abbr': 'MO'}"), try to extract structured fields
      if (s.startsWith('{') && /\b(city|state|abbr|county)\b/i.test(s)){
        // parse all key: value pairs (handles single-quoted or double-quoted keys/values and None/null)
        const parsed = {}
        // capture either bracketed lists or simple values
        const kvRe = /['"]?(\w+)['"]?\s*:\s*(\[[^\]]*\]|[^,}]+)/g
        let m
        while((m = kvRe.exec(s)) !== null){
          let key = m[1].trim().toLowerCase()
          let rawVal = m[2].trim()
          // strip trailing commas or braces for safety
          rawVal = rawVal.replace(/^[\s,]+|[\s,}]+$/g, '').trim()
          if (/^None$/i.test(rawVal) || /^null$/i.test(rawVal) || rawVal === ''){
            parsed[key] = ''
            continue
          }
          // If it's a bracketed list, split items inside and normalize each
          if (rawVal.startsWith('[') && rawVal.endsWith(']')){
            const inner = rawVal.slice(1, -1)
            const items = inner.split(',').map(it => it.trim().replace(/^['\"]+|['\"]+$/g,'').trim()).filter(it => it && !/^None$/i.test(it) && !/^null$/i.test(it))
            parsed[key] = items
          } else {
            // single scalar value
            const v = rawVal.replace(/^['\"]+|['\"]+$/g, '').trim()
            parsed[key] = v
          }
        }
        // helper to push either scalar or array values into bucket
        const pushParsed = (keyCandidates, bucket, mapAbbr=false) => {
          for(const k of keyCandidates){
            const v = parsed[k]
            if (!v) continue
            if (Array.isArray(v)){
              v.forEach(x => { if (mapAbbr && stateMap[String(x).toUpperCase()]) pushUnique(bucket, stateMap[String(x).toUpperCase()]); else pushUnique(bucket, x) })
            } else {
              if (mapAbbr && stateMap[String(v).toUpperCase()]) pushUnique(bucket, stateMap[String(v).toUpperCase()])
              else pushUnique(bucket, v)
            }
          }
        }
        // push states (allow abbrs)
        pushParsed(['state','region','admin1','state_name'], states, true)
        // also map potential state_code/abbr if state not already present
        if (!states.length) pushParsed(['abbr','state_code'], states, true)
        // push counties and cities (plural keys too)
        pushParsed(['county','county_name','countyname','counties'], counties)
        pushParsed(['city','city_name','locality','municipality','town','place','village','cities','places','locations'], cities)
        return
      }
      const lower = s.toLowerCase()

      // country detection
      if (countryKeywords.some(k => lower.includes(k))) { pushUnique(countries, s); return }

      // comma-separated like 'City, ST' or 'City, State' or 'County, State'
      const parts = s.split(',').map(p=>p.trim()).filter(Boolean)
      if (parts.length >= 2){
        const last = parts[parts.length-1]
        const lastUpper = last.toUpperCase()
        // If any non-last part looks like a county, pull it out as county and treat earlier part(s) as city
        const countyIndex = parts.slice(0, parts.length-1).findIndex(p => /\bcounty\b/i.test(p))
        if (countyIndex >= 0){
          const countyName = parts[countyIndex]
          // city is everything before the county part (if any)
          const cityName = parts.slice(0, countyIndex).join(', ')
          if (cityName) pushUnique(cities, cityName)
          pushUnique(counties, countyName)
          // last part may be a state
          if (stateMap[lastUpper]) pushUnique(states, stateMap[lastUpper])
          else if (stateFullSet.has(last.toLowerCase())) pushUnique(states, last)
          return
        }

        if (stateMap[lastUpper]){
          // treat as city + state; add state and city
          const stateName = stateMap[lastUpper]
          pushUnique(states, stateName)
          const cityName = parts.slice(0,parts.length-1).join(', ')
          // if the cityName itself contains the word 'County', treat that portion as county instead
          if (/\bcounty\b/i.test(cityName)) {
            pushUnique(counties, cityName)
          } else {
            pushUnique(cities, cityName)
          }
          return
        }
        // full state name
        if (stateFullSet.has(last.toLowerCase())){
          const stateName = parts[parts.length-1]
          pushUnique(states, stateName)
          const cityName = parts.slice(0,parts.length-1).join(', ')
          if (/\bcounty\b/i.test(cityName)) {
            pushUnique(counties, cityName)
          } else {
            pushUnique(cities, cityName)
          }
          return
        }
        // if ends with 'County' treat as county (e.g. "Some Place County")
        if (/\bcounty\b/i.test(last)){
          const countyName = parts.join(', ')
          pushUnique(counties, countyName)
          return
        }
      }

      // standalone state abbreviation
      const up = s.toUpperCase()
      if (stateMap[up]){ pushUnique(states, stateMap[up]); return }
      // full state name
      if (stateFullSet.has(lower)) { pushUnique(states, s); return }
      // county detection: if string ends with 'County' or contains ' county'
      if (/\bcounty\b/i.test(s)) { pushUnique(counties, s); return }
      // otherwise treat as city-like
      pushUnique(cities, s)
    })

    // Build ordered list: Countries, States, Counties, Cities, Others
    const out = []
    if (countries.length) out.push(...countries)
    if (states.length) out.push(...states)
    if (counties.length) out.push(...counties)
    if (cities.length) out.push(...cities)
    if (others.length) out.push(...others)

    return out.join(', ')
  }

  // clear timer on unmount
  React.useEffect(()=>{
    return ()=>{ if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [])

  function prev(){ if (currentIndex>0) loadArticle(currentIndex-1) }
  function next(){ if (articles && currentIndex < articles.length-1) loadArticle(currentIndex+1) }

  // Precompute parsed + missing mention labels for render to avoid inline IIFE in JSX
  const parsedMentionLabels = (formatLocationMentions(article?.locmentions) || '').split(',').map(s=>s.trim()).filter(Boolean)
  const combinedMentionLabels = [...parsedMentionLabels]
  ;(missingLocations||[]).forEach(m => { if (!combinedMentionLabels.map(String).includes(String(m))) combinedMentionLabels.push(m) })

  return (
    <div className="page root">
      <div className="card">
  
        
        {error && <div style={{color: 'crimson', marginBottom: 8}}>Error: {error}</div>}

        {/* Simple top tabs */}
        <div style={{display:'flex', gap:8, marginBottom:12}}>
          <button onClick={()=>setActiveTab('dashboard')} style={{padding:8, background: activeTab==='dashboard' ? '#ddd' : 'transparent'}}>Dashboard</button>
          <button onClick={()=>setActiveTab('operations')} style={{padding:8, background: activeTab==='operations' ? '#ddd' : 'transparent'}}>🚀 Operations</button>
          <button onClick={()=>setActiveTab('crawl')} style={{padding:8, background: activeTab==='crawl' ? '#ddd' : 'transparent'}}>Crawl</button>
          <button onClick={()=>setActiveTab('domain-reports')} style={{padding:8, background: activeTab==='domain-reports' ? '#ddd' : 'transparent'}}>Extraction</button>
          <button onClick={()=>setActiveTab('dedupe')} style={{padding:8, background: activeTab==='dedupe' ? '#ddd' : 'transparent'}}>Deduplication</button>
          <button onClick={()=>setActiveTab('wire')} style={{padding:8, background: activeTab==='wire' ? '#ddd' : 'transparent'}}>Wire</button>
          <button onClick={()=>setActiveTab('byline-review')} style={{padding:8, background: activeTab==='byline-review' ? '#ddd' : 'transparent'}}>Byline Review</button>
          <button onClick={()=>setActiveTab('verification-review')} style={{padding:8, background: activeTab==='verification-review' ? '#ddd' : 'transparent'}}>URL Review</button>
          <button onClick={()=>setActiveTab('code-review')} style={{padding:8, background: activeTab==='code-review' ? '#ddd' : 'transparent'}}>Code Review</button>
          <button onClick={()=>setActiveTab('gazetteer')} style={{padding:8, background: activeTab==='gazetteer' ? '#ddd' : 'transparent'}}>Gazetteer</button>
          <button onClick={()=>setActiveTab('review')} style={{padding:8, background: activeTab==='review' ? '#ddd' : 'transparent'}}>Review</button>
        </div>

        {activeTab === 'dashboard' ? (
          <Dashboard onOpen={(tab)=>setActiveTab(tab)} />
        ) : activeTab === 'operations' ? (
          <OperationsDashboard />
        ) : activeTab === 'domain-reports' ? (
          <DomainReports />
        ) : activeTab === 'dedupe' ? (
          <DedupeAudit />
        ) : activeTab === 'wire' ? (
          <WireReview />
        ) : activeTab === 'crawl' ? (
          <CrawlIssues />
        ) : activeTab === 'byline-review' ? (
          <BylineReviewInterface />
        ) : activeTab === 'verification-review' ? (
          <VerificationReviewInterface />
        ) : activeTab === 'code-review' ? (
          <CodeReviewInterface />
        ) : activeTab === 'gazetteer' ? (
          <GazetteerTelemetry />
        ) : ( <>

  {/* Publication row (mapped fields from articleslabelledgeo_8.csv) */}
  <div className="row tight-between">
          <div className="input" style={{flex: '0 0 60%'}}>
            <div style={{display: 'flex', gap: 12}}>
              <div style={{flex: 1}}>
                <div className="label">Publication</div>
                <input type="text" value={article?.name || article?.domain || (article?.url ? (new URL(article.url).hostname.replace(/^www\./,'')) : '')} readOnly />
              </div>
              <div style={{flex: 1}}>
                <div className="label">Publication Date</div>
                <input type="text" value={article?.date || article?.publish_date || ''} readOnly />
              </div>
            </div>
          </div>
          <div className="input" style={{flex: '0 0 40%', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'flex-start'}}>
            <div style={assocBoxStyle}>
              <div style={{display:'flex',alignItems:'center',gap:12, justifyContent:'center', width: '100%'}}>
                <div style={{flex: '0 0 36px', display: 'flex', justifyContent: 'center'}}>
                  <button onClick={prev} className="nav-btn" aria-label="Previous article">◀</button>
                </div>
                <div className="title" style={{flex: 1, textAlign: 'center'}}>{article ? `${currentIndex+1} of ${articles.length}` : 'No articles'}</div>
                <div style={{flex: '0 0 36px', display: 'flex', justifyContent: 'center'}}>
                  <button onClick={next} className="nav-btn" aria-label="Next article">▶</button>
                </div>
              </div>
            </div>
            {/* space above the assessment tools */}
          </div>
        </div>

        {/* URL row */}
        <div className="row">
          <div className="input">
            <div className="label">Article URL</div>
            {article?.url ? (
              <a href={article.url} target="_blank" rel="noopener noreferrer" className="link-field">{article.url}</a>
            ) : (
              <input type="text" value={article?.url || ''} readOnly />
            )}
          </div>
          <div className="input">
            <div style={{...assocBoxStyle, flexDirection: 'column', alignItems: 'flex-start'}}>
              <div className="label" style={{fontSize:12}}>Reviewer</div>
              <input type="text" value={reviewer} onChange={e=>{ const v = e.target.value; setReviewer(v); try{ draftCacheRef.current[String(currentIndex)] = { ...(draftCacheRef.current[String(currentIndex)] || {}), reviewer: v, modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(err){}; try{ checkAndSetSaved() }catch(e){} }} style={{padding:'6px 8px', minWidth:180}} />
            </div>
          </div>
        </div>

  {/* Headline row */}
  <div className="row align-to-field" data-auto-offset="half" data-static="true">
          <div className="input">
            <div className="label">Headline</div>
            <input type="text" value={article?.headline || article?.title || ''} readOnly />
          </div>
          <div className="input">
            <TagSelect options={headlineOptions} initial={selectedHeadline} onChange={onHeadlineChange} />
          </div>
        </div>

  {/* Author row */}
  <div className="row align-to-field" data-auto-offset="half" data-static="true">
          <div className="input">
            <div className="label">Author</div>
            <input type="text" value={article?.author || article?.authors || ''} readOnly />
          </div>
          <div className="input">
            <TagSelect options={authorOptions} initial={selectedAuthor} onChange={onAuthorChange} />
          </div>
        </div>

  {/* Body row */}
  <div className="row align-to-field">
          <div className="input">
            <div className="label">Body</div>
            <div className="scroll-body">{article?.news || article?.body || article?.content || ''}</div>
          </div>
          <div className="input">
            <TagSelect options={bodyOptions} initial={selectedBody} onChange={onBodyChange} />
          </div>
        </div>

  {/* Primary classification */}
  <div className="row align-to-field" data-static="true">
          <div className="input">
            <div className="label">Primary Classification</div>
            <input type="text" value={article?.predictedlabel1 || (Array.isArray(article?.ml_labels) ? (article.ml_labels[0]?.label || article.ml_labels[0]) : '') || ''} readOnly />
          </div>
          <div className="input">
              <div className="slider-wrapper">
                <SliderWithBubble value={primaryRating} onChange={onPrimaryRating} min={1} max={5} step={1} />
              </div>
          </div>
        </div>

  {/* Secondary classification */}
  <div className="row align-to-field" data-static="true">
          <div className="input">
            <div className="label">Secondary Classification</div>
            <input type="text" value={article?.ALTpredictedlabel || (Array.isArray(article?.ml_labels) ? (article.ml_labels[1]?.label || article.ml_labels[1]) : '') || ''} readOnly />
          </div>
          <div className="input">
            <div className="slider-wrapper">
              <SliderWithBubble value={secondaryRating} onChange={onSecondaryRating} min={1} max={5} step={1} />
            </div>
          </div>
        </div>

        {/* Location mentions (parsed/ordered) - new row above Notes */}
        <div className="row">
          <div className="input">
            <div className="label">Mentioned locations</div>
            <div className="scroll-body" style={{maxHeight:40}}>
              <div style={{display:'flex', flexWrap:'wrap', gap:8}}>
                {combinedMentionLabels.map((label, i) => {
                  const isRemoved = (removedMentionLabels||[]).map(String).includes(String(label))
                  const isSelected = (selectedChipLabels||[]).map(String).includes(String(label))
                  return (
                    <div key={`chip-${i}`} style={{display:'inline-flex', alignItems:'center', background: isRemoved ? '#f5f5f5' : (Array.isArray(missingLocations) && missingLocations.map(String).includes(String(label)) ? '#e0f7f1' : '#f0f0f0'), color: isRemoved ? '#999' : '#222', padding:'4px 8px', borderRadius:14, marginRight:6, marginBottom:6, cursor:'pointer', boxShadow: isSelected ? '0 0 0 2px rgba(0,150,136,0.15)' : 'none' }} onClick={() => {
                      if (isRemoved) {
                        // Reinstate a removed mention when clicked
                        setRemovedMentionLabels(prev => (Array.isArray(prev) ? prev.filter(p=>String(p)!==String(label)) : []))
                        setSelectedChipLabels(prev => (prev && prev.map(String).includes(String(label))) ? prev : [...(prev||[]), label])
                        try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, removed_mention_labels: Array.isArray(removedMentionLabels)? removedMentionLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], selected_locations: Array.isArray(selectedLocations)? selectedLocations.map(o=>o.label):[], missing_locations: Array.isArray(missingLocations)? missingLocations.map(String):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
                      } else {
                        toggleChip(label)
                      }
                    }}>
                      <span style={{fontSize:12, marginRight:8}}>{label}</span>
                      {!isRemoved && (
                        <button onClick={(e)=>{ e.stopPropagation(); removeChip(label) }} style={{border:'none', background:'transparent', cursor:'pointer', padding:0, color:'#666'}}>×</button>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
            {/* debug display removed */}
          </div>
          <div className="input">
            <div style={{width:'100%', display:'flex', justifyContent:'center'}}>
              <div style={{width:320}}>
                <div style={{display:'flex', gap:8, marginTop:8}}>
                  <input type="text" value={locationInput} onChange={e=>setLocationInput(e.target.value)} placeholder="Add location..." style={{flex:1, padding:'6px 8px'}} />
                  <button onClick={addLocationFromInput} style={{padding:'6px 10px'}}>Add</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Inferred tags (chips) - mirrors mentioned locations UI */}
        <div className="row">
          <div className="input">
            <div className="label">Inferred tags</div>
            <div className="scroll-body" style={{maxHeight:40}}>
              <div style={{display:'flex', flexWrap:'wrap', gap:8}}>
                {(
                  (inferredTags && inferredTags.length) ? inferredTags : ((article && article.inferred_tags_set1) ? String(article.inferred_tags_set1).split(',').map(s=>s.trim()).filter(Boolean).map(l=>({ id:`tag:${l}`, label: l })) : [])
                ).map((t, i) => {
                  const label = t.label || String(t)
                  const isRemoved = (removedTagLabels||[]).map(String).includes(String(label))
                  const isSelected = (selectedChipLabels||[]).map(String).includes(String(label))
                  return (
                    <div key={`tagchip-${i}`} style={{display:'inline-flex', alignItems:'center', background: isRemoved ? '#f5f5f5' : '#f0f0f0', color: isRemoved ? '#999' : '#222', padding:'4px 8px', borderRadius:14, marginRight:6, marginBottom:6, cursor:'pointer', boxShadow: isSelected ? '0 0 0 2px rgba(0,150,136,0.15)' : 'none' }} onClick={() => {
                      if (isRemoved) {
                        // Reinstate removed tag when clicked
                        setRemovedTagLabels(prev => (Array.isArray(prev) ? prev.filter(p=>String(p)!==String(label)) : []))
                        setSelectedChipLabels(prev => (prev && prev.map(String).includes(String(label))) ? prev : [...(prev||[]), label])
                        try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, removed_tag_labels: Array.isArray(removedTagLabels)? removedTagLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], missing_tags: Array.isArray(missingTags)? missingTags.map(String):[], inferred_tags: Array.isArray(inferredTags)? inferredTags.map(t=>t.label):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
                      } else {
                        toggleChip(label)
                      }
                    }}>
                      <span style={{fontSize:12, marginRight:8}}>{label}</span>
                      {!isRemoved && (
                        <button onClick={(e)=>{ e.stopPropagation(); // mark removed tag
                            setRemovedTagLabels(prev => Array.from(new Set([...(prev||[]), String(label)])))
                            // persist draft change for tags
                            try{ draftCacheRef.current[String(currentIndex)] = { ...draftCacheRef.current[String(currentIndex)] || {}, removed_tag_labels: Array.isArray(removedTagLabels)? removedTagLabels.map(String):[], selected_chip_labels: Array.isArray(selectedChipLabels)? selectedChipLabels.map(String):[], missing_tags: Array.isArray(missingTags)? missingTags.map(String):[], inferred_tags: Array.isArray(inferredTags)? inferredTags.map(t=>t.label):[], modifiedAt: Date.now() }; saveDraftsToLocalStorage() }catch(e){}
                            // schedule a debounced autosave for tags
                            try{ debouncedScheduleSave(['tags']) }catch(err){ console.debug('debouncedScheduleSave(tags) error', err) }
                        }} style={{border:'none', background:'transparent', cursor:'pointer', padding:0, color:'#666'}}>×</button>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
          <div className="input">
            <div style={{width:'100%', display:'flex', justifyContent:'center'}}>
              <div style={{width:320}}>
                <div style={{display:'flex', gap:8, marginTop:8}}>
                  <input type="text" value={''} onChange={()=>{}} placeholder="Add tag..." style={{flex:1, padding:'6px 8px'}} onKeyDown={(e)=>{ if (e.key==='Enter'){ const v = e.target.value.trim(); if (v){ setMissingTags(prev=>[...(prev||[]), v]); e.target.value=''; } } }} />
                  <button onClick={()=>{ /* noop: Enter handles add */ }} style={{padding:'6px 10px'}}>Add</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Notes + Save */}
        <div className="row notes-row">
          <div className="input">
            <div className="label">Notes</div>
            <textarea value={notes} onChange={e=>onNotesChange(e.target.value)} onBlur={onNotesBlur} placeholder="Add reviewer notes..." />
          </div>
          <div className="input" style={{display:'flex',flexDirection:'column',justifyContent:'flex-end',alignItems:'stretch'}}>
              <div style={{flex:1}}></div>
            <div style={{display:'flex',flexDirection:'column',gap:8,alignItems:'stretch'}}>
              <div style={{display:'flex',justifyContent:'flex-end',alignItems:'center',gap:8}}>
                <div style={{fontSize:12, color: autosaveStatus === 'error' ? '#d9534f' : (autosaveStatus === 'saving' || autosaveStatus === 'pending' ? '#f0ad4e' : (autosaveStatus === 'saved' ? '#5cb85c' : '#666'))}}>
                  {autosaveStatus === 'pending' ? 'Autosave pending…' : (autosaveStatus === 'saving' ? 'Autosaving…' : (autosaveStatus === 'saved' ? 'Autosaved' : (autosaveStatus === 'error' ? 'Autosave failed' : '')))}
                </div>
                <button id="save" className={saveStatus==='saved' ? 'btn-saved' : (saveStatus==='edited' ? 'btn-edited' : (saveStatus==='saving' ? 'btn-saving' : (saveStatus==='error' ? 'btn-error' : 'btn-unsaved')))} onClick={async ()=>{ 
                 // clear any legacy saveTimer
                 if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
                 // clear pending autosave debounce to avoid duplicate/overlapping saves
                 try{ if (autosaveTimerRef.current) { clearTimeout(autosaveTimerRef.current); autosaveTimerRef.current = null; pendingAutosaveFieldsRef.current = null } }catch(e){}
                 // explicit full save: update autosave UI and await the Promise-returning scheduleSave
                 try{ setAutosaveStatus('saving') }catch(e){}
                 try{
                   await scheduleSave({ body_errors: selectedBody.map(o=>o.id), headline_errors: selectedHeadline.map(o=>o.id), author_errors: selectedAuthor.map(o=>o.id), primary_rating: primaryRating, secondary_rating: secondaryRating, notes }, currentIndex)
                   try{ setAutosaveStatus('saved') }catch(e){}
                   // auto-clear the 'saved' indicator after a short delay so UI doesn't stay sticky
                   try{ setTimeout(()=>{ try{ setAutosaveStatus('idle') }catch(e){} }, 3000) }catch(e){}
                 }catch(e){ console.debug('explicit save error', e); try{ setAutosaveStatus('error') }catch(e){} }
               }}>
                 {saveStatus === 'saved' ? 'Saved' : (saveStatus === 'edited' ? 'Edited' : (saveStatus === 'saving' ? 'Saving…' : (saveStatus === 'error' ? 'Save Error' : 'Not saved')))}
               </button>
              </div>
            </div>
          </div>
        </div>

          {/* debug output removed: Selected (client) / Last saved (server) */}
  {/* additional mapped fields removed (debug) */}
      </>
      )}
      </div>
    </div>
  )
}
