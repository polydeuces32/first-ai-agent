# EvidenceOS — Launch Playbook

> Positioning: **"No evidence, no answer."** An AI that refuses to make things up.
> Every answer is a verified citation from your document — or no answer at all.
> Local-first, no signup, zero per-query cost.

The shareable hook is the **abstention moment**: a screenshot/clip of the AI *refusing
to answer* because it found no evidence. That's the thing people forward.

---

## 0. Go-live checklist (≈30–45 min)

1. **Push to GitHub** (public repo helps virality — see "open source loop" below).
2. **Render Blueprint** → New + → Blueprint → point at `render.yaml`.
   - It provisions the web service + managed Postgres automatically.
   - Set dashboard env vars: `PUBLIC_SITE_URL=https://<your-domain>` and
     `ALLOWED_ORIGINS=https://<your-domain>`.
3. **Domain**: buy something punchy (`evidenceos.ai`, `noevidence.ai`, `citedby.ai`).
   Point it at the Render service. The bare domain serves the landing page (browsers
   get HTML, API clients get JSON).
4. **Smoke test live**: `/health`, `/try`, ask a question, copy the share link, open it
   in an incognito tab, confirm the link unfurls in iMessage/Slack/X.
5. (Optional) Cloudflare Pages frontend via the existing `functions/api/[[path]].js`
   proxy if you want the static edge path.

Pre-flight already done in this repo:
- Public demo endpoints, share permalinks, and landing page are built and tested.
- No new dependencies (stdlib only). `ShareCard` table auto-creates on startup.
- All 14 backend tests pass.

---

## 1. Hacker News — "Show HN"

**Title:**
`Show HN: EvidenceOS – an AI that refuses to answer without a citation`

**Body:**
> I got tired of AI tools confidently making things up, so I built the opposite.
>
> EvidenceOS answers questions about a document by returning the *actual source
> sentences* as the answer, each one a verified citation. If it can't find supporting
> evidence, it refuses to answer instead of guessing. The rule is literally: no
> evidence, no answer.
>
> It's extractive, not generative — so there's nothing to hallucinate. It runs
> fully locally (no external LLM API), which also means the public demo costs me
> nothing per query and your documents never leave the box.
>
> Try it (no signup): <URL>/try — there's a "Watch it refuse" example that shows the
> abstention behavior. Paste your own contract/paper/policy too.
>
> Happy to talk about the retrieval approach, the local-first tradeoffs, and where an
> optional generative layer would/wouldn't make sense. Feedback welcome.

**Tips:** Post Tue–Thu ~8–10am ET. Reply to every comment fast in the first 2 hours.
Don't ask for upvotes. Lead with the honesty/anti-hallucination angle, not features.

---

## 2. Product Hunt

**Name:** EvidenceOS
**Tagline:** `The AI that refuses to make things up`
**Description:**
> EvidenceOS answers questions about your documents using only verified citations —
> every sentence traces back to the source. If there's no evidence, it says so instead
> of hallucinating. Local-first, no signup, your data never leaves your machine.

**First comment (maker):**
> Hey PH 👋 I built EvidenceOS because "confidently wrong" AI is dangerous in the places
> that matter most — contracts, research, compliance. So I inverted it: the answer *is*
> the cited evidence, and when there's no evidence it refuses. Try the no-signup demo and
> tell me where it should (or shouldn't) draw the line.

**Assets:** landing screenshot, a 15s screen recording of the "refuse" moment, and a
share-card screenshot.

---

## 3. Reddit

### r/LocalLLaMA  (strongest fit — privacy + local-first crowd)
**Title:** `Built a local-first doc Q&A that refuses to answer without a citation (no API, no cloud)`
> No external LLM, no API keys, nothing leaves your machine. It's extractive: the answer is
> the verified source text, so it can't hallucinate. When there's no supporting evidence it
> abstains. Free demo (no signup): <URL>/try. Curious what this sub thinks about extractive
> vs generative for high-stakes docs.

### r/selfhosted
**Title:** `EvidenceOS – self-hostable document intelligence, Docker + one render.yaml`
> Single FastAPI app, SQLite or Postgres, one-command Docker deploy. Cited answers only;
> refuses to guess. Repo + deploy blueprint included.

**Subreddit rules:** read each sub's self-promotion rules; lead with value, link last,
reply to comments.

---

## 4. X / Twitter thread

1/ Most AI tools are confidently wrong. I built one that refuses to be.
Meet EvidenceOS: it answers ONLY with verified citations from your document — and when
there's no evidence, it says nothing. 🧵

2/ The trick: it's extractive, not generative. The answer *is* the source sentence,
quoted and cited. There's literally nothing to hallucinate.

3/ Watch it refuse 👇 [clip of the abstention moment]
No matching evidence → no answer. That's the whole point.

4/ It runs fully locally. No external LLM API, no keys, your docs never leave the box.
(That also means the public demo is free to run.)

5/ Try it right now, no signup: <URL>/try
Paste a contract, a paper, a policy — then ask it something the doc *doesn't* cover and
watch it stay honest.

**Then:** quote-tweet a screenshot of your own shared `/s/<id>` card. Tag people in
legal-AI / RAG / local-LLM circles.

---

## 5. Built-in viral loops (already shipped)

- **Share cards**: every answer produces a `/s/<id>` permalink with OG tags → unfurls in
  X/Slack/iMessage/LinkedIn → each share links back to `/try`.
- **The "refuse" example**: the landing has a one-click "Watch it refuse" demo — the most
  screenshot-worthy moment.
- **Open-source loop** (recommended): public repo + a Render "Deploy to Render" button in
  the README. Self-hosters deploying it = free distribution.

## 6. Next growth levers (not yet built)

- Dynamic per-share OG **image** (right now shares use text OG tags + a default image).
- "Verified by EvidenceOS" embeddable badge/widget for other sites.
- Browser extension: highlight any text on the web → "is this actually supported?"
- A weekly "AI caught hallucinating" example account that always ends with a cited
  EvidenceOS answer.
