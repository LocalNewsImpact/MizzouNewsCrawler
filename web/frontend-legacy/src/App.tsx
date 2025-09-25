import React, {useEffect, useState} from 'react'
import {Box, Container, Grid, List, ListItemButton, Paper, Typography, Button, TextField, Select, MenuItem, FormControl, InputLabel, Slider} from '@mui/material'

type Article = any

export default function App(){
  const [articles, setArticles] = useState<Article[]>([])
  const [current, setCurrent] = useState<number | null>(null)
  const [notes, setNotes] = useState('')
  const [primary, setPrimary] = useState(3)

  useEffect(()=>{ fetch('/api/articles?limit=200').then(r=>r.json()).then(d=>setArticles(d.results||[])) }, [])

  function show(i:number){ setCurrent(i); setNotes('') }

  async function save(){
    if (current===null) return
    const payload = { reviewer:'vite', rating: primary, tags: [], notes }
    await fetch(`/api/articles/${current}/reviews`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})
    alert('saved')
  }

  return (
    <Container maxWidth="xl" sx={{pt:3}}>
      <Typography variant="h5">Mizzou Reviewer (Vite)</Typography>
      <Grid container spacing={2} sx={{mt:2}}>
        <Grid item xs={3}>
          <Paper sx={{p:2}}>
            <Typography variant="subtitle1">Articles</Typography>
            <List>
              {articles.map((a:Article,i)=> (
                <ListItemButton key={i} onClick={()=>show(i)}>
                  <div>
                    <strong>{a.title||(a.headline)||`Article ${i}`}</strong>
                    <div style={{fontSize:12,color:'#666'}}>{a.domain || a.outlet || a.hostname} — {a.primary_location || a.primary_city || ''}</div>
                    <div style={{fontSize:11,color:'#888'}}>{a.predictedlabel1 || a.predicted_label || ''} {a.ALTpredictedlabel?` / ${a.ALTpredictedlabel}`:''}</div>
                  </div>
                </ListItemButton>
              ))}
            </List>
          </Paper>
        </Grid>
        <Grid item xs={9}>
          <Paper sx={{p:2}}>
            <Typography variant="h6">{current!==null?articles[current]?.title||articles[current]?.headline:'Select an article'}</Typography>
            <Grid container spacing={2} sx={{mt:1}}>
              <Grid item xs={8}>
                <TextField label="Headline" fullWidth value={articles[current]?.title||''} />
                <Box sx={{mt:1}}>
                  <Typography variant="caption">Body</Typography>
                  <Paper sx={{p:1,mt:0.5, height:220, overflow:'auto'}}>
                    <div style={{whiteSpace:'pre-wrap'}}>{articles[current]?.news || articles[current]?.inputtext || articles[current]?.content || ''}</div>
                    <div style={{marginTop:8, fontSize:12}}>
                      <div><strong>Outlet:</strong> {articles[current]?.domain || articles[current]?.outlet || articles[current]?.hostname}</div>
                      <div><strong>Wire:</strong> {String(articles[current]?.wire)}</div>
                      <div><strong>Primary location:</strong> {articles[current]?.primary_location || articles[current]?.primary_city || ''}</div>
                      <div><strong>Location mentions:</strong> {articles[current]?.locmentions || ''}</div>
                      <div><strong>Predicted label:</strong> {articles[current]?.predictedlabel1 || articles[current]?.predicted_label || ''}</div>
                      <div><strong>Alt label:</strong> {articles[current]?.ALTpredictedlabel || ''}</div>
                      <div><strong>Tags:</strong> {Array.isArray(articles[current]?.tags)?articles[current].tags.join(', '):articles[current]?.tags || articles[current]?.inferred_tags_set1 || ''}</div>
                    </div>
                  </Paper>
                </Box>
              </Grid>
              <Grid item xs={4}>
                <Typography variant="caption">Primary Classification</Typography>
                <Slider value={primary} min={1} max={5} onChange={(e,v)=>setPrimary(v as number)} aria-label="primary"/>
                <TextField label="Notes" multiline rows={6} value={notes} onChange={e=>setNotes(e.target.value)} fullWidth sx={{mt:2}} />
                <Button variant="contained" sx={{mt:2}} onClick={save}>Save</Button>
              </Grid>
            </Grid>
          </Paper>
        </Grid>
      </Grid>
    </Container>
  )
}
