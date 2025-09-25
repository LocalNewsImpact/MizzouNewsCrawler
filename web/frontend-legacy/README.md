This directory was the older vite frontend that caused confusion.
It has been moved to `web/frontend-legacy/` and replaced by the correct React UI from `web/react-app`.

If you need to restore or inspect the old frontend, use:

  git restore --source=HEAD --staged --worktree -- web/frontend-legacy

Otherwise development should use `web/frontend` which now contains the intended reviewer UI.
Vite + React + TypeScript frontend for Mizzou Reviewer

To run locally:

cd web/frontend
npm install
npm run dev

This project expects the backend to be running at http://127.0.0.1:8000 and will call /api/articles.
