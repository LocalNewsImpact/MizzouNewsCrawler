import React from 'react'
import Slider from '@mui/material/Slider'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'

export default function SliderWithBubble({ value, onChange, min=0, max=10, step=1, label }){
  return (
    <Box sx={{display:'flex',alignItems:'center',gap:12,width:'100%'}}>
      {label && <Typography variant="body2" sx={{minWidth:90}}>{label}</Typography>}
      <Box sx={{flex:1, position:'relative', width:'100%'}}>
        <Slider
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e, v)=> onChange(v)}
          aria-label={label}
          sx={{width:'100%'}}
          valueLabelDisplay="on"
          valueLabelFormat={(v)=>String(v)}
        />
      </Box>
    </Box>
  )
}
