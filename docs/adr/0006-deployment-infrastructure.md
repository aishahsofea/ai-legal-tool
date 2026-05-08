# Deploy on Vercel + Railway + Supabase (all free tier)

Three-layer deployment on free-tier managed services, chosen to minimise ops work on a solo project with a hard June 2026 deadline.

- **Vercel** — Next.js frontend. Git-push deploys, zero config.
- **Railway** — Python FastAPI + LangGraph agent backend. Native Python support, straightforward env var management.
- **Supabase** — pgvector database. Managed Postgres with pgvector extension on the free tier, no infrastructure work.

No existing cloud infrastructure to migrate from — starting fresh.

## Consequences

- All three services have free-tier limits. Monitor usage as pilot users onboard; upgrade tiers before public write-up if needed.
- Railway free tier sleeps after inactivity — acceptable for a pilot, needs an upgrade or a keep-alive strategy before public launch.
