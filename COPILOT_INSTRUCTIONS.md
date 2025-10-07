# Copilot Instructions for MizzouNewsCrawler

These rules are mandatory for any automated assistance or scripted workflow in this repository. Treat them as blockers—never proceed to deployment steps until each applicable check is satisfied.

1. **Run pre-deployment validation before ANY deploy.**
   - **ALWAYS** run `./scripts/pre-deploy-validation.sh [service]` before triggering any deployment.
   - This validates: tests pass, YAML config is correct, changes are committed/pushed.
   - If validation fails, fix the issues before deploying.
   - **This would have prevented the PYTHONPATH bug and hours of wasted time.**

1. **Commit & push before deploy suggestions.**
   - Always inspect `git status`.
   - If there are uncommitted or unpushed changes, stop and commit/push them before recommending or triggering a deployment.
   - Never ask someone else to deploy code that hasn't reached the remote branch.

1. **Use Cloud Build/Deploy triggers for releases.**
   - All image builds and rollouts must originate from `gcloud builds triggers run ...` and the associated Cloud Deploy pipeline.
   - Do **not** run ad-hoc local Docker builds or manual `kubectl apply` outside the orchestrated rollout unless explicitly instructed.

1. **Guard test coverage for new code.**
   - For every change, ensure there is automated test coverage. Write or update unit/integration tests as part of the change.
   - Run the relevant test suites before recommending a deployment. Capture the command and result.
   - **Write integration tests that simulate the deployment environment** (e.g., PYTHONPATH, container structure).

1. **Surface coverage gaps proactively.**
   - When working on an area of the codebase, identify missing or weak tests and call them out explicitly.
   - Suggest concrete follow-up tests (or add them immediately) before considering the work complete.
   - **Test deployment configuration, not just application code.**

Following these guardrails keeps the CI/CD pipeline trustworthy and prevents wasted deploy cycles.
