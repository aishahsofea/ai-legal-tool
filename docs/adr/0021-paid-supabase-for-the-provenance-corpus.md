# Production's database moves to a paid Supabase plan

Date: 2026-09-26

ADR 0006 put all three layers on free tiers. That held until the corpus grew. `#157` measured the
gap. The provenance rows need about 1.4 GB, the legacy rows another 0.4 GB. A free Supabase project
goes read-only past 500 MB, and production already holds 411 MB of that. So the corpus cannot load,
and `#156` cannot show a receipt in production until this is settled.

Two pressures, not one. The corpus does not fit at all. Chat now writes to the same database: the
LangGraph checkpointer and store moved there on 2026-09-25 (`agent/graph.py:319-333`). 57
conversations took 5,056 kB, so roughly a thousand conversations would consume the remaining 89 MB.
Past 500 MB every checkpoint write fails with Postgres's read-only-transaction error.

The free plan has already cost an outage. On 2026-09-25 the project had paused after a week idle,
the pooler answered `FATAL: (ENOTFOUND) tenant/user … not found`, and chat could not answer until
someone resumed it by hand.

This supersedes ADR 0006 for the database layer only. Vercel and Railway are untouched. That
includes Railway's sleep-after-inactivity limit: ADR 0006 flagged it, and it is still open.
ADR 0006 stays unedited. Its title says all free tier, and that was true when it was written.

`#157` names six requirements and weighs three options against them. This ADR uses its numbering.
Requirement 3 is no pause when idle. Requirement 6 is enough RAM to keep the HNSW index cached.

## Decisions

- **Supabase Pro, same project, same URL, no data move.** Pro meets five requirements outright:

  1. 8,192 MB of included disk against 1,802 MB used, with allocated disk auto-expanding into it
  2. pgvector 0.8.2, with the HNSW index already built
  3. no pause when idle
  4. one `DATABASE_URL`, already shared by psycopg2 (`agent/retrieval/search.py:17`,
     `corpus/db.py:9`) and psycopg 3 (`agent/graph.py:324-332`)
  5. AWS `ap-southeast-1`, the same city as Railway's `asia-southeast1-eqsg3a`

  Nothing in the repo changes. No rows move. It is the only option that cannot break production
  while fixing it.

- **`ai-legal-tool` becomes the only unpaused project in its organization.** Supabase bills Pro per
  organization and grants the US$10 compute credit once per organization. Compute itself is billed
  per project, and in a paid organization Nano compute is billed at the Micro price. So the price is
  `$25 + (unpaused - 1) x $10`, and a paused project is free. Organization `aishahsofea` holds five
  projects. All five unpaused would be US$65 a month. The Free plan allows two active projects, so at
  least three were already paused on 2026-09-26, and pausing the one other active project brings this
  to US$25. That pausing is a step of this upgrade, not a state it already had. Read the upgrade
  dialog's monthly estimate before confirming. It also settles whether the organization is already
  paid; `supabase orgs list` does not report that.

- **Resizing is a separate step, so it is part of this upgrade.** Supabase does not auto-upgrade
  compute size, because it would force downtime. A project left on Nano after the upgrade runs on
  0.5 GB of RAM at the Micro price. Raising `ai-legal-tool` to Micro restarts the database.

- **Micro first, and requirement 6 stays open until the corpus is loaded.** Micro's 1 GB of RAM
  against a 612 MB provenance HNSW index fits on paper and leaves little for heap pages. A latency
  number taken before `#156` loads the corpus would mean nothing, so requirement 6 is recorded as
  not measured, not as met. After `#156`, measure `semantic_search` p50 and p95 on production. If it
  is slow, Small compute doubles the RAM for US$15 in place of Micro's US$10, with no data move.
  Do not pre-buy it. Micro is already twice the RAM production runs on today.

- **A plan's disk limit belongs next to the size it holds.** A limit kept only in a dashboard goes
  stale silently and is then discovered as an outage, which is exactly what happened here.
  `CONTRIBUTING.md` is where it belongs, next to the operator detail it already owns. `#157` carries
  that edit alongside the upgrade; this ADR only fixes where the number lives.

## Considered options

- **Move to Railway's own Postgres, in the project where the API already runs.** Rejected, and it
  was the close one. Volume storage is US$0.15 per GB, so about US$0.45 a month for 3 GB, and it
  drops the pooler hop entirely. But its memory is metered at US$10 per GB a month with no spend
  cap, so a 2 GB working set costs about what Pro costs. Against that: the 23,941 legacy rows must
  be copied before production chat has any corpus at all, HNSW must be rebuilt, `DATABASE_URL` must
  change, and there is no managed point-in-time recovery at this size. A latency gain should be
  bought with a measurement on a loaded corpus, not with a migration performed before the corpus
  exists. Revisit if the `semantic_search` numbers taken after `#156` are bad and Small compute does
  not fix them.

- **Move to Neon.** Rejected. Singapore exists as `aws-ap-southeast-1`. But requirement 3 forces
  scale-to-zero off, and an always-on 1 CU compute is about US$77 a month at US$0.106 per CU-hour —
  three times Pro, for less RAM than Small. Its storage is also a network page service, and HNSW
  search is random reads, so its storage is the wrong fit for the workload.

- **Stay free and load a subset of Acts.** Rejected on requirement 3 alone: free projects pause for
  any subset, which is the outage described above. Size does not save it either. Dropping the HNSW
  index and moving to `halfvec` together give 5.6 KB a row, measured on 20,000 rows, so all 87,715
  provenance rows come to 476 MB. That is inside 500 MB by 24 MB, with nothing left for checkpoints
  or for the 411 MB of legacy rows, and it costs the index that makes retrieval work. A subset also
  narrows the corpus-wide receipts ADR 0016 set up, and needs a written rule for which Acts a
  practitioner can and cannot get a receipt for. That is a product regression priced as a cost
  saving.

- **Cut row size with `halfvec` instead of buying disk.** Not one of `#157`'s three options, and not
  rejected. Measured on 20,000 provenance rows, `halfvec(1536)` halves both the stored vector and
  the HNSW index exactly, cutting 17.38 KB a row to 9.29 KB. That is worth having: it is the
  cheapest route to a comfortable requirement 6. But it is a schema change with its own recall
  question, and it does not fix the pause. It needs its own issue. Buying disk is what unblocks
  `#156` this week.

## Consequences

- Production costs US$25 a month where it cost nothing. ADR 0006's consequences anticipated exactly
  this: upgrade tiers before a public write-up if needed.
- The pause is gone, so that outage cannot recur from idleness. Railway's own sleep limit can still
  cause its own.
- No code, no rows, and no `DATABASE_URL` move, so there is nothing to roll back. Reverting means
  downgrading a plan.
- Requirement 6 is deliberately unresolved, and "Micro first" was never claimed to be verified.
  `#156` inherits the measurement, and the fix for a bad number is a compute setting, not a
  migration.
- Disk is not provisioned at 8,192 MB up front. It auto-expands into that allowance at 90% full, in
  50% steps, capped at four resizes in a rolling 24 hours. That is slower than a bulk import, and
  Supabase puts a database into read-only mode when an upload exceeds 1.5x its current storage.
  Production holds 411 MB, and `#156` takes it to about 1,802 MB, which is 4.4x. So `#156` must raise
  disk by hand before it loads anything. Inside 8,192 MB this costs nothing; only the disk beyond it
  bills at US$0.125 per GB.
- Supabase's spend cap is on by default on Pro. Leave it on. It converts a surprise bill into a
  surprise read-only database, which is the failure this project can actually notice. Compute is
  excluded from the cap, as something deliberately opted into. The cap covers disk past 8,192 MB,
  egress and monthly active users, never the US$10 per unpaused project. Only the project count and
  the compute size control that.
- Un-pausing one of the four, or creating a sixth project in this organization, each add about
  US$10 a month.
- The four paused projects are restorable for 90 days under the Free plan's rule, after which
  Supabase replaces restore with a download of the last logical backup. Paid projects get a year.
  The upgrade may extend the window for these four; this ADR does not rely on it.

## Related

- ADR 0006 — chose free tiers for all three layers. Superseded here for the database layer only,
  and left unedited, the same way ADR 0002 stayed unedited under ADR 0018.
- ADR 0016 — immutable corpus provenance for PDF receipts. This ADR buys the disk its corpus-wide
  guarantee needs; a subset of Acts would have narrowed it.
- `#157` — the issue this decision belongs to, with the measurements and the per-requirement verdicts.
- `#156` — loads and activates the corpus, and inherits the requirement 6 measurement.
- `#57` — the receipt criteria unblocked once `#156` lands.
- `#41` — retrieval quality and embedding dimensions. The `halfvec` figures here are about size only.
