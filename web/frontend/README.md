Mizzou Reviewer React demo

Run locally (when npm is available):

```bash
cd web/react-app
npm install
npm run dev
```

This small demo shows a MUI Autocomplete multiselect (chips) component. Adapt `src/components/TagSelect.jsx` to map options to your backend shape and call your FastAPI endpoints.

API notes
- GET /api/options/bodyErrors -> returns an array of option objects: [{id,label,meta?}, ...]
- GET /api/articles -> returns list of articles (each article must have `id`)
- GET /api/articles/{id}/reviews -> returns review object with `body_errors` array of ids (optional)
- POST /api/articles/{id}/reviews -> accepts { body_errors: [id,...] } and returns 200 on success

Run locally (when npm is available):

```bash
cd web/react-app
npm install
npm run dev
```
