import React, { useState, useRef, useEffect } from 'react'
import TextField from '@mui/material/TextField'
import Autocomplete from '@mui/material/Autocomplete'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown'

export default function TagSelect({ options = [], initial = [], onChange, allowCreate = false }){
  const [value, setValue] = useState(initial || [])
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef(null)
  const [localOptions, setLocalOptions] = useState(options || [])

  // Keep localOptions in sync when options prop changes
  useEffect(()=>{
    setLocalOptions(Array.isArray(options) ? options : [])
  }, [options])

  // Reconcile incoming `initial` (or external value changes) with the
  // local option instances so Autocomplete can render chips that match
  // the option objects by identity/ids. This ensures that when the parent
  // updates `options` (e.g. when loading a new article), the selected
  // chips reflect those updated option objects.
  useEffect(()=>{
    try{
      const src = initial || []
      const mapped = (Array.isArray(src) ? src : []).map(item => {
        if (!item) return item
        // string short-form: find option by label
        if (typeof item === 'string'){
          const found = (localOptions || []).find(o => String(o.label) === String(item))
          if (found) return found
          const obj = { id: `new:${item.replace(/\s+/g,'_')}`, label: item }
          // ensure localOptions contains it
          if (!localOptions.find(o => o.id === obj.id)) setLocalOptions(prev => [...(prev||[]), obj])
          return obj
        }
        // object form: prefer the canonical instance from localOptions by id
        const found = (localOptions || []).find(o => String(o.id) === String(item.id))
        if (found) return found
        // If not found, ensure it's present in localOptions so it can be displayed
        if (item.id) {
          if (!localOptions.find(o => String(o.id) === String(item.id))) setLocalOptions(prev => [...(prev||[]), item])
        }
        return item
      })
      setValue(mapped)
    }catch(e){ /* ignore reconciliation errors */ }
  }, [initial, localOptions])

  // click-away handler scoped to this instance: close when clicking outside the wrapper
  useEffect(()=>{
    if(!open) return;
    const handler = (e)=>{
      try{
        const path = (typeof e.composedPath === 'function' && e.composedPath()) || (function(){ const p=[]; let el = e.target; while(el){ p.push(el); el = el.parentNode; } return p; })();
        // if click is inside our wrapper, ignore
        if(wrapperRef.current && path.includes(wrapperRef.current)) return;
        // if click is inside any MUI Autocomplete popper (the dropdown), ignore
        if(path.some(n=> n && n.classList && n.classList.contains && n.classList.contains('MuiAutocomplete-popper'))) return;
        setOpen(false);
      }catch(_){ /* ignore */ }
    }
    document.addEventListener('click', handler);
    return ()=> document.removeEventListener('click', handler);
  }, [open]);

  return (
    <Autocomplete
  multiple
    fullWidth
    options={localOptions}
    value={value}
    open={open}
    freeSolo={allowCreate}
  onOpen={()=>setOpen(true)}
  onClose={(event, reason) => {
    // Keep open when a selectOption action occurs — some internal focus/blur ordering
    // can cause a single-select click to close before value updates. We rely on
    // disableCloseOnSelect but proactively prevent closing on selectOption here.
    if (reason === 'selectOption') {
      setOpen(true);
      return;
    }
    setOpen(false);
  }}
      popupIcon={null}
  onChange={(e, newVal, reason) => {
        // Normalize any freeSolo string entries into option objects { id, label }
        const normalized = (newVal || []).map(item => {
          if (!item) return item
          if (typeof item === 'string'){
            const label = item.trim()
            const id = `new:${label.replace(/\s+/g,'_')}`
            const obj = { id, label }
            // add to local options so it appears in dropdown subsequently
            if (!localOptions.find(o => o.id === obj.id)) setLocalOptions(prev => [...prev, obj])
            return obj
          }
          return item
        })
        setValue(normalized); onChange?.(normalized); if (reason === 'selectOption') { setOpen(true); }
      }}
      getOptionLabel={(o) => o.label}
      isOptionEqualToValue={(option, value) => {
        // Compare by id so that objects with the same logical id match even
        // if they are different object instances (common when rehydrating from server)
        try {
          // support the case where value may be a string when freeSolo is enabled
          if (typeof value === 'string') return option?.label === value
          return option?.id === value?.id
        } catch (_) { return false; }
      }}
      renderTags={(tagValue, getTagProps) =>
        tagValue.map((option, index) => (
          <Chip key={option?.id || String(option)} label={option?.label || String(option)} {...getTagProps({ index })} />
        ))
      }
      renderInput={(params) => {
        const hasChips = (value && value.length > 0)
        return (
          <div ref={wrapperRef} className={`tag-select ${hasChips ? 'has-chips' : ''}`} style={{position:'relative', width:'100%'}}>
            <TextField
              {...params}
              variant="outlined"
              placeholder={hasChips ? '' : params.inputProps?.placeholder || ''}
              fullWidth
              inputProps={{
                ...params.inputProps,
                // When allowCreate is true, allow typing; otherwise keep readOnly behavior
                readOnly: !allowCreate,
                style: { cursor: allowCreate ? undefined : 'pointer', display: hasChips ? 'none' : undefined }
              }}
              InputProps={{
                ...params.InputProps,
                // Ensure any built-in endAdornment (popup indicator) is removed so we don't render
                // a second chevron; we rely on the anchored .chev-btn instead.
                endAdornment: null
              }}
            />

            {/* Anchor the chevron to the top-right of the cell; keep it keyboard-focusable */}
            <IconButton className="chev-btn" size="small" onClick={(ev)=>{ ev.stopPropagation(); setOpen(o=>!o)}} aria-label="Open options" tabIndex={0}>
              <ArrowDropDownIcon />
            </IconButton>
          </div>
        )
      }}
      disableCloseOnSelect
      autoHighlight
      componentsProps={{
        popper: {
          disablePortal: true,
          placement: 'bottom-start',
          modifiers: [
            { name: 'flip', enabled: false },
            { name: 'preventOverflow', enabled: false },
            { name: 'eventListeners', enabled: false },
            { name: 'computeStyles', options: { gpuAcceleration: true, adaptive: false } }
          ]
        }
      }}
    />
  )
}
