# M0 A/B: stripping Claude Code's overhead from the summarize call

Run 2026-10-15. Protocol in `docs/PROPOSAL.md` §10.1. Harness and raw outputs were kept in the
session scratchpad, not the repo.

## Setup

Five videos with cached bundles: the four in `examples/`, plus `SpGKvIbiVWg` from W40. Each
arm ran twice per video, 30 calls in all, every call with `--output-format json
--no-session-persistence --effort high`.

| Arm | Model | Flags | cwd |
|---|---|---|---|
| **A** production | `opus` (= `claude-opus-5`, what `drain` used per the session logs) | `drain`'s `--disallowed-tools` list | repo root, so `CLAUDE.md` loads |
| **B** lean | `opus` | `--tools "" --setting-sources "" --strict-mcp-config --system-prompt <one line>` | empty dir |
| **D** lean | `sonnet` | as B | empty dir |

The production model was confirmed from the transcripts of earlier headless runs: the user
settings say `model: opus, effortLevel: high`, and `drain` inherited them. An earlier probe
that dropped settings silently fell back to Sonnet, so the A/B pins the model and effort
explicitly.

## Results

| Arm | Valid | Verdict = reference | Same verdict both runs | Fluff spread between runs | Timestamped claims | Words | Input tokens | Output tokens | API-eq $ / summary |
|---|---|---|---|---|---|---|---|---|---|
| A production (Opus) | 10/10 | 6/10 | 3/5 | 5.6 pts | 28 | 1,558 | 40,186 | 12,537 | 0.65 |
| **B lean (Opus)** | 10/10 | **8/10** | **4/5** | **2.6 pts** | **34** | 1,815 | **19,123** | 10,012 | **0.46** |
| D lean (Sonnet) | 10/10 | 6/10 | 2/5 | 3.8 pts | 27 | 1,290 | 19,191 | 12,016 | 0.21 |

Means per run. "Reference" means the verdicts in the README table and the committed W40
summary. Those are older runs, not ground truth, and the DW News reference ("Skip the video",
because the summary carries it) is a judgment call that every arm disagreed with. Excluding DW,
verdict agreement is A 6/8, **B 8/8**, D 6/8.

## Findings

1. **Lean Opus (B) is at least as good as production on every automatic measure.** Its
   verdicts were more accurate and more stable, its fluff estimates varied half as much
   between runs, and it cited more timestamped claims. Nothing in the data suggests that
   removing the Claude Code system prompt costs quality. If anything, the system prompt was
   adding noise.
2. **The saving is smaller than first estimated.** Input tokens fell 52% (40.2k → 19.1k), but
   output dominates the cost, mostly thinking (5–15k tokens per call). API-equivalent cost per
   summary fell 29%, from $0.65 to $0.46. The proposal's "~70%" figure came from a one-word
   probe and is corrected.
3. **Production's overhead varied run to run** (DW: 29.6k vs 65.0k input tokens for the same
   bundle). The lean arm was flat to within a few tokens. Lean is also more predictable, which
   the usage ceiling depends on.
4. **Sonnet (D) costs 54% less than lean Opus, but its judgment is weaker.** It had the least
   stable verdicts (2/5), drifted generous on "watchable" (DW at 17 of 18 min with "Watch the
   whole thing"; Sandeep at 14 of 19 min on one run), and its summaries were 30% shorter, with
   fewer claims. Its fluff estimate was the most accurate on the Paine lecture (1% vs a <1%
   reference).
5. **No transcripts persisted.** The count under `~/.claude/projects/` was 56 before and after
   the 30 runs.

## Status: shelved (2026-10-15)

The blind read was not done. Skimming the outputs, the owner judged that the summaries in all
three arms still leave something lacking. So the real question is the summarization engine
itself, not which flags it runs under. That question is deferred to milestone M5b in
`docs/PROPOSAL.md`, which runs after the rest of the service is built and **before any friend is
invited**.

**Decision until then: production stays as it is.** Same prompt, same model (Opus, high effort),
same flags. The worker adds only `--no-session-persistence` and `--output-format json`. Neither
changes the model's input, and they are required for privacy and for token accounting.

## Reusing this for M5b

- Harness: `tools/ab/run_one.sh <arm> <video_id> <run>` and `tools/ab/score.py <dir>`. Outputs
  go to `.cache/ab/` (gitignored).
- This run's outputs, the blind-read page and its key are in `.cache/ab/2026-10-15/`. `python3
  tools/ab/score.py .cache/ab/2026-10-15` reproduces the tables above.
- Carry forward: the lean flags are a free ~29% saving with no measured quality loss, worth
  folding into whatever engine M5b settles on. Pin model and effort explicitly in every arm.
