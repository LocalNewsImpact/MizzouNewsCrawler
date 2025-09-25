import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

// Runtime diagnostic & aggressive suppression for duplicate chevrons / legacy pseudo-elements
// This runs when the React bundle loads (helps when the app is served from the React entrypoint).
;(function runChevronDiagnostic(){
  try{
    // Delay slightly to ensure DOM from React mount exists
    setTimeout(()=>{
      try{
        // Insert a runtime style tag with highest-priority rules to hide any ::before/::after
        // caret glyphs inside tag-select if they are coming from late-loaded stylesheets.
        const STYLE_ID = 'chev-suppressor-runtime';
        if(!document.getElementById(STYLE_ID)){
          const s = document.createElement('style');
          s.id = STYLE_ID;
          s.textContent = `
            /* Runtime suppression: hide pseudo-element carets inside our tag-select scope */
            .tag-select *::before,
            .tag-select *::after,
            .tag-select .multi-toggle,
            .tag-select .multi-toggle::before,
            .tag-select .multi-toggle::after { content: none !important; display: none !important; }
          `;
          document.head.appendChild(s);
          console.log('diagnostic: injected runtime chev-suppressor style');
        }

        // Report any remaining legacy nodes
        const legacy = Array.from(document.querySelectorAll('.multi-toggle'));
        console.log('diagnostic: runtime found .multi-toggle nodes count=', legacy.length, legacy);

        // Check for pseudo-element content inside tag-select descendants
        const tagSelects = Array.from(document.querySelectorAll('.tag-select'));
        tagSelects.forEach((ts, idx)=>{
          const elems = Array.from(ts.querySelectorAll('*'));
          const hasPseudo = [];
          elems.forEach(el=>{
            try{
              const before = window.getComputedStyle(el, '::before').getPropertyValue('content');
              const after = window.getComputedStyle(el, '::after').getPropertyValue('content');
              if(before && before !== 'none' && before !== '""' && before !== '') hasPseudo.push({el, pseudo:'::before', content: before});
              if(after && after !== 'none' && after !== '""' && after !== '') hasPseudo.push({el, pseudo:'::after', content: after});
            }catch(_){ }
          });
          console.log(`diagnostic: runtime tag-select[${idx}] pseudo-content count=`, hasPseudo.length, hasPseudo.map(h=>({tag: h.el.tagName, pseudo: h.pseudo, content: h.content})) );
          // best-effort hide any found elements
          hasPseudo.forEach(h=>{ try{ h.el.style.setProperty('display','none','important'); }catch(e){} });
        });

        // Also log how many React chevrons are present (so we can see duplicates)
        const chevElems = Array.from(document.querySelectorAll('.chev-btn'));
        console.log('diagnostic: found chev-btn elements count=', chevElems.length, chevElems);

      }catch(e){ console.warn('diagnostic runtime error', e); }
    }, 120);
  }catch(e){ /* silent */ }
})();
