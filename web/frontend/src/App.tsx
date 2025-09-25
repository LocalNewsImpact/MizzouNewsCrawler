import React, { useEffect, useState } from 'react'
import { Container, Paper, Typography, Grid, List, ListItemButton, Button, TextField, Select, MenuItem, FormControl, InputLabel } from '@mui/material'

// Minimal, dependency-free router: render pages based on window.location.pathname
function Router() {
  const path = typeof window !== 'undefined' ? window.location.pathname : '/'
  if (path === '/domain-reports') return <DomainReportsPage />
  if (path === '/story-sniffer') return <StorySnifferPage />
  return <HomePage />
}

// Clean minimal App component with routes for Domain Reports and Story Sniffer.
export default function App() {
  return <Router />
}

function HomePage() {
  return (
    <Container maxWidth="xl" sx={{ pt: 3 }}>
      <Typography variant="h5">Mizzou Reviewer (Vite)</Typography>
      <div style={{ marginTop: 8 }}>
        <a href="/domain-reports">Domain Reports</a> &nbsp;|&nbsp; <a href="/story-sniffer">Story Sniffer</a>
      </div>
      <Paper sx={{ p: 2, mt: 2 }}>
        <Typography>Use the links above to open the Domain Reports or Story Sniffer tools.</Typography>
      </Paper>
    </Container>
  )
}

function DomainReportsPage() {
  const [domainIssues, setDomainIssues] = useState({})
  const [selectedHost, setSelectedHost] = useState('')
  const [feedback, setFeedback] = useState({ priority: 'low', notes: '' })

  useEffect(() => {
    fetch('/api/domain_issues')
      .then(r => r.json())
      .then(d => setDomainIssues(d || {}))
      .catch(() => setDomainIssues({}))
  }, [])

  async function saveHostFeedback() {
    if (!selectedHost) return
    await fetch(`/api/domain_feedback/${encodeURIComponent(selectedHost)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(feedback)
    })
    // optimistic: update local state
    setDomainIssues((prev: any) => ({ ...prev, [selectedHost]: { ...(prev as any)[selectedHost], feedback } }))
    alert('feedback saved')
  }

  return (
    <Container maxWidth="lg" sx={{ pt: 3 }}>
      <Typography variant="h5">Domain Reports</Typography>
      <Grid container spacing={2} sx={{ mt: 2 }}>
        <Grid item xs={4}>
          <Paper sx={{ p: 2 }}>
            <List>
              {Object.keys(domainIssues || {}).map((h) => (
                <ListItemButton key={h} onClick={() => { setSelectedHost(h); setFeedback(((domainIssues as any)[h] || {}).feedback || { priority: 'low', notes: '' }) }}>
                  <div>
                    <strong>{h}</strong>
                    <div style={{ fontSize: 12, color: '#666' }}>{(() => { const obj = (domainIssues as any)[h]?.issues || {}; const vals = Object.values(obj); return vals.reduce((a: number, b: any) => a + (Number(b) || 0), 0) })()} issue(s)</div>
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
                <pre style={{ fontSize: 12, maxHeight: 260, overflow: 'auto' }}>{JSON.stringify((domainIssues as any)[selectedHost], null, 2)}</pre>
                <FormControl fullWidth sx={{ mt: 1 }}>
                  <InputLabel>Priority</InputLabel>
                  <Select value={feedback.priority || 'low'} label="Priority" onChange={e => setFeedback({ ...feedback, priority: String((e.target as HTMLSelectElement).value) })}>
                    <MenuItem value={'low'}>Low</MenuItem>
                    <MenuItem value={'medium'}>Medium</MenuItem>
                    <MenuItem value={'high'}>High</MenuItem>
                  </Select>
                </FormControl>
                <FormControl fullWidth sx={{ mt: 1 }}>
                  <TextField label="Notes" multiline rows={4} value={feedback.notes || ''} onChange={e => setFeedback({ ...feedback, notes: e.target.value })} />
                </FormControl>
                <Button variant="contained" sx={{ mt: 1 }} onClick={saveHostFeedback}>Save feedback</Button>
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

function StorySnifferPage() {
  return (
    <Container maxWidth="lg" sx={{ pt: 3 }}>
      <Typography variant="h5">Story Sniffer (QA)</Typography>
      <Paper sx={{ p: 2, mt: 2 }}>
        <iframe title="storysniffer" src="/qa_storysniffer.html" style={{ width: '100%', height: 800, border: 0 }} />
      </Paper>
    </Container>
  )
}
