# Filming & capture notes — read before shooting

Accuracy and capture guidance for anyone recording the live site for marketing video. The site is honest threat-intelligence — keep the footage honest too, and capture it in its best state.

## Accuracy caveats (don't misrepresent these on camera)

- **The `/feed` attack-replay is a *conceptual* animation, not a live transcript.** The "model response" shown in the attack-replay (`attack-replay.tsx`) is heuristically synthesized to illustrate how an attack plays out — it is not a captured response from a live target. Film it as the explainer beat ("here's how a jailbreak escalates"), and never caption it as "real model output." Everything else on `/feed` and `/matrix` (breach rates, confidence intervals, payloads, provenance, the breach drawer) is real data from the breach DB.
- **Only the `/feed` ticker is truly real-time.** The live attack ticker (`live-attack-ticker.tsx`, its own SSE connection on `/api/sse/feed`) is the one genuinely live element — new attacks slide in with a green flash. That is the authentic "it's alive" shot. Every other "live" number on the site (hero stat trio, mini-matrix, matrix heatmap, how-it-thinks metrics) is served through a **5-minute ISR cache** — real data, but it won't visibly tick while you film. Don't stage a "watch the number climb" shot on anything except the `/feed` ticker (or the in-scan progress poller, below).
- **`/analytics` is a static published snapshot** (`frontend/public/analytics.json`, refreshed via `publish_analytics.sh`), not a live API read — it can lag the live pages. Re-publish it before filming if you want it consistent with `/matrix`/`/feed`.
- **The in-scan progress poller IS live during a scan.** On `/scans/{scanId}` the breach counter, current-attack line, spend, and ETA update every ~2s while a real scan runs — that is a legitimate live-climbing shot (just run a real scan to capture it).

## Capture guidance (get the best state on screen)

- **Replay the 16-second intro on demand:** append `?intro` to the landing URL (`/?intro`) to force-replay the storyboarded intro overlay — it's effectively a pre-built mini-trailer (4 panels: problem → harvest → test → brief). Strong cold-open source.
- **Get a fresh, rich data state before shooting** the threat-intel pages — the hero counts, matrix density, and feed activity reflect whatever the DB holds at capture time. A recent harvest/reproduce run makes the matrix and feed look fullest and most alive.
- **For a great report shot, run a scan that actually breaches** — point a scan at a soft target (or use a mode/pack likely to produce findings) so the report lands on a high RiskHeadline with several severity-grouped findings, remediation, and the "breached" evidence flag visible. A `0/100 — low` report is honest but undramatic.
- **Vertical/social cuts:** the dashboard and the report view are content-dense; the matrix heatmap, the report RiskHeadline, and the `/feed` ticker crop best to 9:16. The landing hero is built for 16:9.
- **Two orphaned-but-filmable assets exist in code** (built, not currently wired into a page): `pipeline-flow.tsx` (an animated SVG harvest→reproduce→defend pipeline) and `augmentation-headlines.tsx` (a worst-case strip). If you want either as B-roll, they'd need to be temporarily mounted on a page — flag it to engineering.

## The honest pitch posture

ROGUE's whole credibility is that the numbers are real and independently judged. The strongest marketing move is to lean into that: show the live ticker, open a real breach drawer with its confidence intervals, run a real scan to a real report. Reserve the synthesized/illustrative beats (attack-replay, the intro overlay) for *explaining* the mechanism, clearly framed as such.
