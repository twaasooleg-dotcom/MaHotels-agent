# MaHotels-agent current memory

## CURRENT REQUIREMENTS: THREE DAILY ARTICLES / NEWS ROUTE (2026-11-17)

Latest user request supersedes all two-article and old-hour settings below. Sole working folder: D:\MaHotels-agent.
- One run daily at 06:00 Africa/Cairo; exactly three articles and three 1024x1024 images per NEW batch.
- 12:00 and 18:00 Cairo: Blog category [7].
- 14:00 Cairo: Blog + News & Files categories [7,1710], matching https://mahotels.net/archives/43168.
- ID 1710 is a CATEGORY, not a tag. Both public REST and authenticated WordPress checks verified this. The example has categories [7,1710]. Keep tag_id=null; no tag API call for 1710.
- config: topics_per_cycle=3, cycle_days=1, publish_hours=[12,14,18], max_topic_candidates=18. publication_routes explicitly maps each hour to category_ids/tag_ids.
- publication_policy.py is required runtime code. New slot reservations atomically pin data.publication with the slot. Publish/recovery use that saved route, even after later config edits. Legacy already-reserved jobs without a route keep the old global category [7]. Identity checks each configured category once. Server confirmation must include the expected category.
- Existing posts 45246 and 45249, media 45247 and 45250, and November 18 noon/18:00 slots were preserved. Do not reopen that completed two-post batch or insert an unreviewed extra post. New routing starts with the next NEW batch; earliest publication is November 19 under the one-day-ahead queue.
- All 116 offline tests and pip check passed. Tests include three-post/image commit and idempotent recovery, Cairo DST, exact per-slot taxonomy, missing-news confirmation, pinned routes, completed two-post preservation and durable budgets.
- Live authenticated check: author 59; categories 7 and 1710; three minimal GETs, zero WP writes. Target=3 local migration changed only its marker: all jobs, cycles, provider counters/cooldowns and last_run_started remained identical.
- Actual task independently checked Ready, daily interval 1, next run 2026-11-18T06:00:00+02:00. Action and working directory target D:\MaHotels-agent. Trigger/action were read, not changed; the next process reads the updated config. The old live task description can still mention two; it does not control article count.
- No extra production run, quota reset, credential change, paid upgrade, or weakened source/text/vision gate. Provider caps and WP pacing/cap unchanged. Exhausted free quotas can defer completion; three is a target, not a guarantee.
- daily_migration.py defaults to target=3; its CLI reads the configured target. Historical tests explicitly request target=2 for their old scenarios.
- Backup: state/backups/before-news-route-20261117-134636-163856.zip and matching .sqlite snapshot.
- Audit: state/news-routing-verification.json. Original two-post live verification remains state/scheduling-verification.json. Updated Arabic operational instructions: README_AR.md.

Earlier entries below are historical wherever they conflict with this current section.

## VERIFIED SUCCESS — 2026-11-17

First two-article batch is actually scheduled and independently checked against WordPress:
- Post 45246 / featured media 45247: energy article, November 18 at 12:00 Cairo (10:00 UTC).
- Post 45249 / featured media 45250: direct-booking article, November 18 at 18:00 Cairo (16:00 UTC).
Both server posts are future, category [7], and point to the expected featured-media IDs. Local uploaded JPEGs are 1024x1024; media/static-header verification details are in state/scheduling-verification.json. The first nested _fields media-details query did not return media_details, so final verification used minimal per-item metadata and static image headers where available.
Both local jobs are scheduled, have real text/image approval flags, and genuine Cloudflare vision approval for current scene provenance. Energy now shows actual rooftop solar panels; the stale generic interior was archived rather than published.
WordPress admin Posts > Scheduled should show both now. Public pages appear at their scheduled times. Do not recreate the completed batch because its public URL is not live yet.
All 106 tests passed. Local Cloudflare reserved/settled guard usage was 9033, within its documented 10000/day free allocation; this is not an actual billed-usage claim. Primary provider counters/cooldowns/daily marker were preserved, no paid plan/model enabled. Cloudflare text/real vision is an explicit fallback to the exhausted primary routes.
Windows Task Scheduler independently verified: MaHotels-Agent is Ready, DaysInterval=1, next run 2026-11-18 at 06:00 Cairo, LastTaskResult=0, and action/working directory both target D:\MaHotels-agent. pip check reports no broken requirements. Remaining notes below are historical where they conflict with this verified result.



## ACTIVE SETTINGS — TWO DAILY ARTICLES (2026-11-15)

Latest user request supersedes all previous three-article and 10/14/18 requirements below.
- Working folder D:\MaHotels-agent only.
- Run once daily at 06:00 Cairo; prepare two full Arabic articles and two 1024x1024 images.
- Publish at 12:00 noon and 18:00 Cairo, in one future day's slots after both articles/images pass.
- config: topics_per_cycle=2, cycle_days=1, publish_hours=[12,18], max_topic_candidates=12.
- Provider caps/cooldowns, 1500-2000-word rule, sources, editorial/vision, security and WP load gates remain enforced. Lower volume reduces demand but cannot guarantee free-provider capacity.
- Migration retained up to two compatible active jobs, favoring developed drafts; excess unpublished jobs remain in backlog with IDs, data, article parts/evidence/revisions intact. Target-aware migration does not skip an old target=3 marker. No live post/slot is reassigned.
- Backups: state\backups\before-two-daily-20261115-143537-267111.zip and matching .sqlite file.
- All 70 regression tests passed before migration, including two-post/two-image replay-safe scheduling at noon/18:00, <=13 commit calls and Cairo DST, prior-marker migration and completed-batch preservation.
- Existing MaHotels-Agent task retains its daily 06:00 trigger. Only its description needs the new two-article target. No extra production run or API call is launched by this update.
Older sections below are historical where they conflict with this specification.


Updated 2026-11-15, Africa/Cairo. **The user's latest instruction replaces the ten-day/30-article design with a daily/three-article design.** Historical details are in state/backups/cleanup-20261115-113130-009102.zip; do not restore its old cadence.

## Current requirements

- Project: D:\MaHotels-agent; site https://mahotels.net; WordPress username ma_news_agent.
- Publish in **category 7 «المدونة»**, tag_id=null. The user confirmed this after discovering that tag 7 does not exist. This is separate from the earlier resolved Application Password issue.
- **One scheduled run every day at 06:00 Cairo**, preparing **three final topics/articles and three 1024x1024 images** per active daily batch.
- Publish at **10:00, 14:00 and 18:00 Africa/Cairo**. Work is normally queued one day ahead after all three pass the gates, avoiding immediate/backdated publication and providing preparation time.
- The computer's actual Windows timezone was verified as **Egypt Standard Time (UTC+02:00 Cairo)**. The scheduler's 06:00 local wall time therefore follows Cairo/DST on this machine. Python publication conversion independently uses ZoneInfo('Africa/Cairo'). Recheck the task if the Windows timezone changes.
- “Three per request” means three final articles per daily invocation. Article parts, topic proposals, text review and image inspection still need multiple small provider API calls. One topic proposal is generated per bounded request; rejected candidates do not become extra published articles.
- Free plans only; no payment/plan upgrades, paid search, arbitrary model migration or quality bypasses. Groq, Gemini and Cloudflare have separate locally supplied credentials from ArabiaTrend.
- Keep WordPress resource use low. Generation, comparisons and reviews run locally/at AI providers. WP calls are sequential, >=3 seconds apart, <=100 per invocation, with minimal response fields. No WP generation plugin, code changes, background site monitoring or old-post rewriting.

## Pipeline and gates

config.json uses cycle_days=1, topics_per_cycle=3, publish_hours=[10,14,18], run_hour=6. core.validate_config enforces the daily design. Each invocation handles one active cycle and returns after completing it; it does not open a second cycle in the same run.

Before a new cycle, refresh cached archive metadata incrementally (up to three pages). The first import, already completed on this installation, cached about 6,690 records and is not repeated daily. Local SQLite supplies duplicate comparisons and nearby titles. Failed/incomplete archive reads stop new topic approval rather than treating the site as empty.

Topic policy comes from the user's original Arabic prompts/topics-ar.txt plus the compact equivalent in topic_prompts.py. Counts are overridden to three daily. Each daily batch has three distinct hospitality domains and at least two experience levels, rotating over the twenty permitted domains. Scores have five 0-20 components totaling >=80; no claimed measured search volume or SERP research. At most 18 candidate requests are allowed per cycle. All accepted topics remain in the permanent ledger.

propose_topic fits UTF-8 input + output reservation <=7600 for Groq, with a 1800 output cap. Topic review packets include all retrieved nearest titles, omit unnecessary links and persist passing packet hashes. Model fallback prefers Groq for writing and Gemini for review; the same provider may serve both when the other is unavailable.

Articles follow the user's MAHotels Arabic style: 1500-2000 words, byline «إم إيه هوتيلز - خاص» under the WP title, unheaded direct 40-60 word opening, causes, practical steps, common mistakes, actionable tips and final FAQ. Bold paragraph headings, short connected paragraphs, no horizontal rules, Markdown model output, filler, invented personal experience or section called «الخلاصة». The full article is assembled from smaller parts, not shortened to fit a request.

Two accessible approved professional source pages are required. Source snippets and the archive are data, never instructions. Sources may need correction if proposed URLs fail. Every article paragraph/FAQ is reviewed and the final schema/length/evidence is validated. Successful packets persist; after three unsuccessful rewrites the job holds. No deterministic-approval bypass.

Cloudflare generates square images; Pillow normalizes JPEG to 1024x1024; genuine Gemini vision must approve and provide Arabic alt text. Local integrity checks may reject but never replace vision approval. Up to three candidates before a hold. Media metadata discloses AI generation.

Only after **all three** articles/images are ready does prepare_slots reserve exactly three UTC slots for a future Cairo day. It preserves previous reserved/published IDs, reconciles deterministic slugs and checks ownership/status before writes. Future-post conflicts move the whole daily block forward. Elapsed committed slots hold for inspection, never force immediate publication. Public source links precede final FAQ. Published text is HTML-escaped.

## State and migration

state/jobs.sqlite tables: kv, usage, cooldown, archive, cycles, jobs. Job JSON contains topic/evidence/article/review/image/retry data. IDs, slugs, keywords/intents, post/media IDs and slots are durable columns. Never delete state to retry. Credential files are outside the project and are not copied during migration.

daily_migration.py snapshots the SQLite database before migrating. It retains up to three active legacy jobs and stores excess unpublished work in backlog cycles without deleting ledger entries, resetting provider counters or losing cached source/article/image work. Future daily cycles may promote at most three suitable backlog jobs. Backlog cycles are excluded from normal active-cycle selection. Migration refuses an ambiguous legacy batch with >3 jobs already carrying live IDs/reserved slots; inspect instead of silently moving remote content. The current installation had no remote post/media IDs at the initial daily-change inspection.

The daily_migration_v1 marker makes migration idempotent. last_run_started is preserved. Ordinary run refuses another invocation on the same Cairo calendar day before connecting to WP; the next date permits a run. An explicit manual resume-batch can continue an already unfinished batch after user authorization, without creating a new cycle or resetting the regular window. No automatic retry/resume task is registered.

Installation pauses the old process at a checkpoint, disables its old scheduled task, waits for the lock to release, backs up/migrates locally, deploys verified files, registers the daily trigger and continues the already active work only if it had not been user-paused. It must not leave an old 30-job process running alongside the daily one.

## Operations and security

Main task: MaHotels-Agent, one Daily trigger DaysInterval=1, next 06:00. No MaHotels-Agent-Resume task. run.ps1 launches only its own .venv interpreter and imports its own secure values. control.ps1 pause disables the task and writes PAUSE; enable removes PAUSE and enables the next daily trigger without an extra immediate run. Already scheduled WP content is unaffected.

The process budget is 240 minutes and task timeout adds 15 minutes; most work is outside WP and provider quotas can stop a run sooner. Failed/incomplete batches resume the next daily run before creating new work, avoiding uncontrolled backlog. Three publications/day is a target, not a promise when quotas, sources or reviews fail.

Secrets: %LOCALAPPDATA%\MaHotelsAgent\wordpress-credential.xml, api-secrets.xml, free-tier-confirmed.json, encrypted with Windows DPAPI. Never echo secrets, use ArabiaTrend files or store plaintext in the project. the local CHANGE-MAHOTELS-API-KEYS.ps1 (also launched by CHANGE-API-KEYS.cmd) provides a secure backed-up key editor without reinstalling/resetting the task.

Default models remain Groq openai/gpt-oss-120b, Gemini gemini-3.8-flash and Cloudflare @cf/black-forest-labs/flux-2-klein-4b. Local UTC-day caps remain Groq 150 requests/180000 reserved units, Gemini 50/200000, Cloudflare 30 images/requests. Reservations are conservative byte/output estimates, not billed token measurements; actual provider quotas may be lower. Reservations and cooldowns persist through failures and are never reset to evade quota.

truststore 0.10.5 was installed after both providers failed Requests' certificate-chain validation. The CLI injects the native Windows trust store before HTTP imports, keeping CERT_REQUIRED and hostname verification enabled. A live Groq topic preview subsequently passed. Do not disable TLS or install arbitrary roots. A previously declined native HEAD diagnostic is not needed or authorized to rerun merely because this code uses native trust.

TEST-TOPIC.cmd / run.ps1 test-topic performs one model preview with at most one fallback, uses cached metadata, makes zero WordPress/source-page requests, and writes state/topic-test.json without approval or changing the production run window. It does not load the WP password. Source pages are not verified by that preview. status is offline; while a run holds the process lock, follow state/agent.log rather than starting another CLI instance.

## Validation and history

The earlier 30-article system had 49 passing tests and one live candidate awaiting review after the TLS fix. The daily version has **54 passing tests**, including a full simulated three-article/image commit to exactly one day's 10/14/18 slots with <=19 WP requests, no duplicate replay, same-day run blocking/next-day allowance, bounded planning, safe migration/backlog promotion and preservation of cached archive, usage and run markers. The generic slot helper is also tested across Cairo DST boundaries. Tests mock providers/WP and do not prove live article accuracy or quotas.

Use README_AR.md for current daily instructions. state/backups/cleanup-20261115-113130-009102.zip is historical and contains superseded ten-day/30-article requirements. Read actual current logs/state/task metadata before claiming a run or publication succeeded.

## Source holds and repair (2026-11-15)

The daily migration succeeded on November 15: active cycle retained two compatible legacy topics and then approved a third; two additional legacy topics remain in a backlog cycle. All three active jobs held before writing because the models had supplied guessed/nonexistent URLs such as hospitalitynet.org/article/12345. WordPress identity/category and text-model discovery pass; this is a source-evidence failure, not proof of an API-key issue. Older November 11 TLS messages are historical. CLI check's last_error=null refers to that successful diagnostic; job-level held errors remain in state/status.json. No article/image had been scheduled at this inspection.

Ten replacement EHL HTML pages were found through web search and successfully fetched/extracted using the application's Sources implementation, covering guest AI/chatbots, renewable energy/ESG, direct bookings/distribution, revenue management and ML demand forecasting. source-replacements.json maps those editor-selected pages to the five existing job IDs, including backlog. This manifest is specific to this installation, not a universal mapping for new topics. Source text still must support each claim and pass editorial review; reachable HTML alone is not editorial approval.

repair_sources.py verifies all replacement pages before changing any job, snapshots SQLite, preserves IDs/slugs, provider counters and run markers, and resets only source-related holds on unpublished jobs without articles/evidence/live IDs. Other holds are rejected. Reapplying the manifest is a no-op for already repaired jobs. It uses no WordPress client or model credentials; only approved source domains are fetched and cached. Command: .venv\Scripts\python.exe -B -X utf8 .\repair_sources.py .\source-replacements.json. Do not repeatedly retry unchanged invalid URLs, clear state, rotate functioning keys or bypass evidence gates. Future invalid model URLs still require real verified replacement sources; there is no paid search integration or fabricated fallback.

providers.py now distinguishes source HTTP status from non-HTML responses. status() reports a future nominal daily 06:00 window even when the original run marker is old; it preserves that marker and does not change the real Windows task. Get-ScheduledTaskInfo gives the actual next trigger. Read logs with Get-Content -Encoding UTF8 to avoid Windows PowerShell mojibake. All **60 tests passed**, including atomic repair, idempotence, unchanged budgets/run markers, duplicate redirect rejection, preservation of unrelated holds/drafted work and the stale-window regression. Live Cloudflare generation is unproven until an image job succeeds.


## Sole working folder and cleanup (2026-11-15)

All future edits belong in D:\MaHotels-agent. Do not edit the other ArabiaTrend project or depend on its files. Four obsolete .mahotels-* staging copies, three parent-dependent INSTALL-MAHOTELS-* scripts and the old pre-daily root memory were archived and removed from the active layout. The overwritten root MEMORY.md contained ArabiaTrend context; this MaHotels memory restores the correct context.

The verified cleanup ZIP is state/backups/cleanup-20261115-113130-009102.zip. It includes every removed file, the previous memory/docs/setup and old test filename. State snapshots, logs, SQLite, prompts, the environment, credentials and the daily task are preserved. daily_migration.py remains required at runtime for promote_backlog; do not remove it just because the one-time migration finished.

New local shortcuts: TEST.cmd runs offline unittest discovery and pip check; CHANGE-API-KEYS.cmd opens the existing secure API-key editor. tests/test_ten_day_limits.py was renamed tests/test_daily_limits.py to reflect its daily tests. README_AR.md now describes this self-contained folder and UTF-8 logs. Setup's error message now says identity/taxonomy rather than tag.

At cleanup inspection: three active jobs are writing and two backlog jobs approved. No post/media IDs. The latest saved waits were Groq daily local budget reached and Gemini network/wait messages. The previous continuation exited after saving progress; do not claim the batch is still running or published. Do not reset provider counters; the next regular daily run can continue. status.json may lag until CLI completion.

All 60 tests and pip check passed before cleanup; verify after file changes. No production processing, WordPress/provider requests, task changes or credential changes are part of this cleanup.


## User folder correction: D drive (2026-11-15)

The user explicitly corrected the sole working folder to D:\MaHotels-agent. All future project edits must happen here. The previous C-drive folders are not active edit targets.
Applied the reviewed folder cleanup directly to this D-drive copy. Its own database, logs, prompts, article progress, credentials and quota counters were preserved; no C-drive production state was copied over.
Backed up removed/changed files and copied-environment launchers in state/backups/cleanup-20261115-113130-009102.zip. Updated project documentation, TEST.cmd and CHANGE-API-KEYS.cmd for the D-drive folder.
The copied environment's activation scripts and console launchers are corrected to use D:\MaHotels-agent\.venv; the base Python installation at C:\Python315 is still needed and is intentionally unchanged.
Before this change, the D-drive environment passed all 60 tests and pip check. The D-drive saved ledger had three writing jobs and two approved backlog jobs, with no post/media IDs. This does not prove current provider availability or completed publication.
The Windows task's action should target D:\MaHotels-agent\run.ps1; inspect the actual task verification, not historical C-drive notes. Retargeting preserves its daily trigger and enabled/disabled state and does not launch another batch.


## Windows process-lock correction (2026-11-15)

User reported PermissionError at handle.read(1) during setup/check, status and run. The lock ACL permits Modify; a recent run is recorded. The old implementation read byte zero before acquiring it. Windows mandatory byte locks make that read fail when another instance owns the lock. This is a local concurrency bug before WP/model discovery, not evidence of bad keys.

process_lock now acquires before reading/writing and initializes an empty file only after ownership. ProcessBusy is separate from LockAccessError; busy run/check returns code 3 and a clear message, without a traceback or second run. Setup reports this as busy rather than connection failure. status during a busy run reads a consistent SQLite mode=ro snapshot with no Agent initialization, provider calls, JSON exports or runtime-marker writes. It explicitly reports running=true. Do not delete run.lock or disable mutual exclusion. Closing the handle releases the lock after completion or errors. Existing running processes retain old imported code until exit; new commands use this fix.

Added real two-process contention/release tests, error-release/reusable-marker tests, access-denial classification and a busy-status nonmutation test. Prior code/memory backup: state\backups\before-lock-fix-20261115-121559-378189.zip. Validate the test result and live command separately; no production process is started by installation.

Live post-fix status confirmed running=true with three writing jobs, two backlog jobs and no post/media IDs; another real instance holds the lock. All 65 lock-era tests and pip check passed. Live status additionally exposed an oversized intro request and Gemini quota waits. Intro generation now uses the same compact ARTICLE_KERNEL already used for body/FAQ, keeping all evidence and correction messages plus the 1500-2000/40-60 constraints instead of duplicating the full 3160-byte Arabic system prompt. The canonical full prompt file is preserved. Added a regression for request size with evidence/corrections. This applies to newly launched processes; the current process retains its old imports. Do not shorten quota waits or launch another batch to apply it.

Two-article follow-up: status counts exclude backlog cycles and report backlog_counts separately; CLI also shows daily_target=2 and publish_hours_cairo=[12,18]. Busy read-only status uses the same separation. All 70 tests passed, including a migrated active-two/backlog-one status regression. Existing provider counters and last-run marker were retained; no extra production run was launched.
Final verification: two daily articles at [12,18] Cairo; 70 tests, dependency and script syntax checks passed. Actual next task trigger: 2026-11-16T06:00:00.0000000. Actual task description: One daily batch of three articles. Publication: 10/14/18 Africa/Cairo.. No extra production run launched.


## Targeted writing repair (2026-11-17)

Both active articles held after three whole-draft rewrites: energy draft 1624 words failed intro grammar; booking draft 1214 words included a 43-word paragraph. No WP/media IDs or slots. Waiting cannot clear editorial holds. Added article_parts.py: generated openings/sections/FAQ are validated before commit, including actual 340-390-word body sections and the unchanged final 1500-2000-word rule. Invalid part attempts cap at three, persist through waits and never overwrite the previous valid draft. Structural repair expands only needed sections. revise() queues affected units, preserves saved article and content/policy-keyed passing review packets, retains the three-round editorial limit and full vision/validation gates. English professional sources may support faithful Arabic paraphrases; source_ids are the internal citation mapping; statistics or Arabic-only sources must not be invented as requirements. Unsupported claims/guarantees still fail. Any article change invalidates coherence approval. Starting any write removes stale text/image approval flags, including on deferred/invalid responses. Explicit retry_held preserves drafts, audits prior revision budgets, excludes backlog/live IDs/committed slots and leaves provider counters and run markers intact. New per-part word-count/progress logs and blocked_jobs make held work visible. All 78 tests passed. Code/database backup: state/backups/before-targeted-writing-20261117-104023-524876.zip and matching .sqlite. Live retry/repair/image/publication still require separate verification.
User-authorized targeted repair was rearmed only for active jobs e61ffa5d26c5d0d7e486679d (opening) and bfd18551a9e69d7e619a72c3 (three needed body sections). Original article data, provider usage and last-run marker were retained; fresh bounded part repair budget is audited. Hidden manual resume-batch PID 25024 started at 2026-11-17T12:42:29.7675747+02:00. Inspect logs and ledger before claiming success. Daily 06:00 trigger unchanged.

Live repair follow-up: energy opening corrected by provider; saved article now 1614 words and entering full review. Gemini intermittently returns HTTP503, with existing cooldowns/fallbacks respected. All 13 energy review packets were size-simulated and fit Groq (largest 6713 reserved units); no approval was persisted by that diagnostic. To reduce quota spent on regenerating booking content, the assistant authored four sourced conditional practical paragraphs (88/87/88/90 words) and replaced its deficient overclaiming paragraph. Saved booking draft passed unchanged deterministic schema/evidence/word checks at 1609 words; it is reviewing, not publication-approved. The prior draft is backed up in state\backups\before-booking-copyedit-20261117-105031-275568.sqlite. Existing text was retained, source IDs preserved, book text/image approvals and packet cache invalidated. Energy passing packets retained. No provider counters or daily markers reset.
Post-copyedit review continuation PID 25016 at 2026-11-17T12:50:31.8227631+02:00. The previous continuation stopped via PAUSE checkpoint, without forced termination. Daily task unchanged.

Final repair verification: both active drafts pass unchanged deterministic article validation: energy 1614 words, booking 1609 words. They remain reviewing, not approved/scheduled; live energy cache had seven passing packets at inspection, no live post/media IDs. New article_progress fields in regular/busy status report words, section count, FAQ readiness, passed review packets, pending repairs and text/image approvals. Future launched agents log each passing packet; the currently active process retains its imported code until completion. All 78 tests passed after progress instrumentation. No quota/cadence/quality bypass was made; provider waits/HTTP503 can still defer completion.

The corrected review policy caught genuine unsupported claims in energy tips section: 30% ventilation savings and >60% cost reduction after year seven, plus other absolute promises. The agent correctly queued only section index 3, preserving seven prior passing packets. The assistant replaced that one section with four 85/88/86/85-word conditional evidence-grounded paragraphs using IDs 2/3/6/1. New complete energy draft passes deterministic validation at 1607 words; no text/image/publication approval was set. Previous draft backup: state\backups\before-energy-fact-edit-20261117-105519-209591.sqlite. Review continues with unchanged provider counters/cooldowns and the daily marker.
Latest controlled continuation PID 16976 at 2026-11-17T12:55:19.7926711+02:00. Older continuations were checkpointed via PAUSE, never force-killed. Verify current state before claiming completion.

Booking review then correctly flagged unsupported real-time analytics/custom-pricing claims in its original opening. Assistant replaced only opening/excerpt with a 50-word grounded direct explanation, source_ids [1,5]. Full booking draft now validates at 1610 words; cache/content policy still requires independent re-review. Backup state\backups\before-booking-intro-edit-20261117-105656-219086.sqlite. No approvals or counter resets performed. Energy remains 1607 words. All current word-count/source-ID/schema failures have been corrected, while full semantic review and images may still reveal issues or be deferred by quota.
Latest review continuation PID 8048 at 2026-11-17T12:56:56.7659777+02:00. Only this process should be active; older own continuations checkpointed normally.


## Explicit free Cloudflare text/vision fallback (2026-11-17)

User insisted on fixing quota-blocked publication. Groq/Gemini daily local reservations were exhausted (177832/180000 and 197105/200000); actual Gemini also returned quota/503. Counters/cooldowns were not cleared or raised. Using the already-authorized Cloudflare account, added a declared fallback: @cf/openai/gpt-oss-120b for text, @cf/meta/llama-4-scout-17b-16e-instruct for genuine image review. Official Cloudflare docs list both under the daily free 10000-neuron allocation, not the paid-only model list. Shared durable cf_neurons table reserves at most 9000/day across text, vision and existing Flux klein 4b images before transport; failures retain reservations. Conservative UTF8 input bounds, full output caps and 16384 image tokens determine costs from documented rates. Existing images reserve 128 neurons each, seeded into the shared ledger if predating installation. Only verified models allowed; no paid upgrade, new account, key rotation, primary budget reset or local image acceptance. Text/vision per-provider request/token caps remain enforced. Publishing accepts only actual Gemini or Cloudflare remote vision markers with valid Arabic alt text; all editorial/source/word/ownership gates remain. The former Gemini-only image-review description is superseded by this real-vision fallback. Backlog is separated from active jobs in status to avoid old unrelated errors looking like current work. All 86 tests passed; live Cloudflare permissions, inference and final publication still need verification. Backup state\backups\before-cloudflare-fallback-20261117-110959-798507.zip.

Live Cloudflare probes succeeded: GPT-OSS rejected an unsupported 99% savings claim; Scout actually inspected attached pixels and identified blue background/red triangle. No WordPress call was made by probes. Migrated only job-level composite retry deadlines to the newly available route, preserving audited previous waits and all Groq/Gemini cooldowns, counters, attempts and last-run marker. This is not retrying a blocked provider. Full batch continuation is authorized by user; confirm actual WP/media IDs and scheduling before claiming completion.
Verified fallback continuation PID 23696 at 2026-11-17T13:13:29.1737126+02:00. Daily task still one 06:00 Cairo trigger; no new automatic resume task.

Live fallback passed energy review packets 8-11, then correctly requested a FAQ repair. Detected a new-part validator mismatch: 35-45-word generation guidance was enforced as a hard FAQ rule although core accepts 20-100. Aligned the part validator to the existing final rule; the user did not impose a narrower FAQ answer count. All source/schema/Arabic/final 1500-2000-word and semantic review gates remain. Retried only the queued FAQ unit with audit; primary counters/cooldowns untouched. Added consistency regression; all 87 tests passed. Live completion still requires verification.


## Final consistency/metering fix (2026-11-17)

Aligned generated-section validation with unchanged final rules (3-6 paragraphs, 45-120 words each). A 340-390-word section was guidance, not an independent user requirement; reject only genuinely invalid parts. Overall 1500-2000 remains mandatory. Underlength complete drafts now gain new validated paragraphs in available section slots, each adds real content monotonically, instead of repeatedly replacing whole sections assuming the model will reach a particular count. Append work stops once the minimum is met; final full checks still run. Each model part remains bounded to three attempts. New opening prompts prohibit copying schema placeholders and ask for a concrete relevant image scene.

Added per-call Cloudflare metering receipts. Shared neuron reservations are settled once only from actual returned nonnegative complete prompt/completion usage, at verified model rates. Failed/unknown/historical calls keep reservations; no historical count reset or inferred refund. Duplicate/missing/negative usage cannot refund; an over-bound usage report fills the guard to stop further calls. Primary budgets/cooldowns/last-run marker remain unchanged. Old Cloudflare unreceipted reservations remain charged in full.

Editor corrected all known remaining unsupported legacy booking passages and five FAQs, replaced the energy FAQs with precise source-grounded answers, and replaced placeholder/graphical image prompts with actual solar-hotel/reception scenes. Fresh manual review budget is audited because the article content was substantially corrected, not automatically reset after a failed review. Existing source IDs and backups retained, no text/image/publication approvals set; all updated text passed deterministic validation. Backup state\backups\before-consistent-parts-metering-20261117-114514-218947.zip. Tests passed; live full review/actual image/WP scheduling still require verification.

Clarified semantic review of evidence-scoped limitations versus universal empirical claims, and allowed conditional operational inferences rather than demanding verbatim source wording. Previously passing stricter-policy packets are reused only for identical content/old-policy hash; new approvals require a scope-v2 key. Actual invented statistics/unsupported research/guarantees remain rejected. Removed the false-positive FAQ repair queue but did not set any approval; re-review required. Cloudflare completion budget now includes 512 reasoning tokens, fully reserved in tokens/neurons; incomplete outputs retry at their own existing cooldown only twice before an actionable hold on the third attempt. A terminal fallback error is no longer hidden behind a blocked primary provider until tomorrow. All 96 tests passed; live scheduling must still be confirmed.

Final length-completion bug fixed: a semantically corrected section reduced booking draft to 1479 words on its third review round, causing a hold instead of finishing that same revision. Word additions now run before full validation within the existing round; they are bounded by section paragraph capacity, actual word increments and three attempts per paragraph, stop at the required minimum and still require final validation/all semantic packets. This grants no additional semantic review round and no approval. Manually rearmed only that length-completion hold, keeping revisions=3. All 98 tests passed, including no-extra-revision and no-unneeded-append regressions.


## Exact-unit repair and visual provenance (2026-11-17)

Root semantic repair bug fixed: a failed paragraph previously rewrote its whole section, creating new claims and shortening other good material. Reviewer-local indices/headings now identify exact paragraphs/FAQ answers; unlocated failures repair only the visible packet. Each failed unit gets up to three semantic corrections; aggregate revisions remain an audit metric. Legacy aggregate limits migrate once with audit because the old article-wide three-count incorrectly exhausted on three unrelated units. All units must pass real reviews; no forced approval. Invalid model output still has its separate three-attempt bound. No provider counter/cooldown/daily-marker reset.

Actual ready energy image was inherited from an old placeholder brief (a generic interior). Image generation now hashes title+visual brief, archives stale local images reversibly, regenerates them and passes the English scene to genuine remote vision. Generic interiors cannot satisfy a solar/energy visual brief. publish() and slot allocation reject stale scene provenance; uncommitted ready jobs reroute to image stage. Remote-committed stale visuals hold for reconciliation. New brief versions get an audited fresh image attempt budget; the same brief retains its attempts. All 105 tests passed, including exact location mapping, per-unit exhaustion, unchanged neighboring text and stale-image refusal/regeneration.

Cloudflare fallback guard calibrated to 9500 neurons/day, below the documented 10000 free allocation; count/token safeguards are 80 requests/450000 conservative units for the new fallback only. All existing consumption remains charged. Genuine per-call usage settlement remains idempotent; unknown failures and historical estimates are never refunded. Groq/Gemini limits/counters remain unchanged. This provides room for actual reviews and image reservations within the free allocation; no paid model/plan activated. Backup state\backups\before-exact-unit-image-repair-20261117-120908-794758.zip. Live WP scheduling still must be verified.

Stale-ready visual deadlock fixed: a ready job without a slot previously skipped before checking image provenance, so it could never regenerate its stale image and therefore never reserve slots. The early skip now applies only to current-provenance visuals. Added a real run-loop regression; all 106 tests passed. Cloudflare shared admission guard now uses the documented full 10000-neuron free allocation; every conservative reservation/receipt remains intact, no consumption is reset, primary caps unchanged, and nothing can reserve beyond that limit. Earlier 9000/9500 values were extra internal buffers and caused false admission blocks on large conservative vision reservations even though measured actual usage remained below them.
