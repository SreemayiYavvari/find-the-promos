# Find the Promos

A Gemini-powered tool that finds and ranks continuous 20–60 second promo clips from timestamped screenplay TXT files. The result is one self-contained `report/report.html`: ranked cards with a hook, cliffhanger, rationale, and a conversation overlay. Click a card to read the clip's dialogue and action; close with the X, Escape, or the backdrop.

## 1. Process and ranking

The pipeline first establishes valid cut points, then evaluates how well each clip works as a promo.

### Parse the screenplay

Each dialogue/action/camera block becomes an entry with an episode ID, scene ID, speaker, start/end seconds, content, and source line. Concurrent tracks retain their timestamps: a camera shot and dialogue happening together do not add extra time. Missing end timestamps are estimated using 2.5 words per second and the next same-track start, and a warning is printed.

### Generate valid candidate clips

For each dialogue/action start, the segmenter considers later entry endpoints. A candidate must:

- Last 20–60 seconds, within the configured bounds.
- Stay inside one scene and episode.
- Avoid cutting through a dialogue line or splitting a continued sentence.
- Contain at least two speaker labels, unless an intensity rule permits solo dialogue/action.

Camera and sound entries remain available during parsing, but cannot create promo anchors. This version selects continuous clips; it does not assemble montages or join episodes.

### Shortlist with deterministic scores

Each valid candidate receives scores from 0–10:

| Score | Signals |
|---|---|
| Hook | Conflict words, punctuation, intense action, estimated speech density near the first three seconds |
| Cliffhanger | Questions, suspense words, interruptions and danger in the final completed beat |
| Coherence | Opening context, action cues, speaker diversity; penalties for ambiguous opening pronouns |

The composite score is:

```text
heuristic_score = 0.4 × hook + 0.4 × cliffhanger + 0.2 × coherence
```

Candidates are sorted by that score. The number sent to Gemini per episode is:

```text
min(max_candidates, ceil(valid_candidate_count × shortlist_fraction))
```

There is at least one shortlisted candidate when any valid candidate exists. Defaults are the top 15%, capped at four. This saves API calls but can miss a strong moment ranked poorly by the rules.

### Evaluate with Gemini

Gemini receives the candidate's dialogue/action, duration, speaker labels, and allowed hook/cliffhanger entry IDs. It returns:

- Exact hook and cliffhanger quotes with source entry IDs.
- An overall editorial score from 0–100.
- Whether the clip makes sense on its own.
- A concise explanation of why the unresolved moment may encourage continued viewing.

The request uses a JSON response schema. Python validates every returned field and checks the quotes against the original entries. Gemini does not generate or alter clip timestamps. Invalid quotes, malformed responses, blocked output, or truncated output fail explicitly; there is no offline fallback.

A hook/cliffhanger entry must intersect the respective first/last three seconds. Its complete quoted line can extend beyond that interval because the input has entry-level timing, not word-level alignment.

### Remove overlap and rank globally

Candidates marked non-standalone are excluded. The rest are sorted by Gemini score, with the heuristic score as a tie-breaker. Temporal non-maximum suppression (NMS) keeps the highest-ranked candidate and rejects another candidate in the same episode when:

```text
IoU = overlap_duration / union_duration
IoU > iou_threshold
```

The default threshold is 0.40. It permits some overlap, including a short clip nested in a much longer one. Use `--iou-threshold 0` to forbid all overlap. Up to three promos survive per episode by default; fewer is valid. Selected promos are then ranked across episodes by Gemini score, heuristic score, episode label, and start time.

Scores are editorial signals, not calibrated conversion probabilities. Keyword rules can overrate resolved questions or triumphant endings; Gemini quality also requires editor review. Script timings must be verified against footage. No audience-conversion benchmark is claimed.

## 2. Implementation

Everything needed to run the app is directly inside `code`:

```text
code/
├── main.py          # Environment loading, arguments, orchestration, final ranking
├── parser.py        # Screenplay entry parsing and timestamp normalization
├── engine.py        # Candidate generation, heuristic scoring, shortlisting, NMS
├── semantic.py      # Native Gemini REST requests and grounded response validation
├── report.py        # HTML/CSS, ranked cards, conversation modal
├── .env             # Your private Gemini API settings
├── .env.example     # Example environment configuration
├── .gitignore
├── README.md
└── report/
    └── report.html  # Only generated output
```

`python3 main.py` calls `main()`, which:

1. Loads `GEMINI_API_KEY` and optional `GEMINI_MODEL` from the adjacent `.env` without executing shell code. Already exported environment variables take precedence.
2. Uses `argparse` to parse terminal arguments into `args` and passes them to `run(args)`.
3. Validates arguments, finds the TXT files, and creates a Gemini evaluator.
4. Parses, generates, scores, shortlists, evaluates, and suppresses candidates episode by episode.
5. Sorts all selected candidates globally, assigns ranks, and embeds the cards and source conversations into one HTML file.

Gemini authentication uses the `x-goog-api-key` header. The key is never written to HTML or printed. The native `generateContent` endpoint is used; no other provider adapters remain. The program uses Python's standard library, so no pip installation or SDK is required.

Transient HTTP/network failures retry up to three attempts. Numeric `Retry-After` delays are honored up to 60 seconds, alongside request spacing. Invalid source quotes are rejected rather than silently repaired. The report is replaced atomically only after the run completes successfully; an unsuccessful run leaves any previous report intact. Rankings and evaluations are held in memory; no JSON/CSV, run logs, or disk caches are generated. Rerunning the pipeline makes fresh Gemini requests.

The HTML has no external assets or network requests. Source text is escaped before embedding. Its native modal dialog traps focus, supports keyboard opening, prevents background scrolling, and returns focus to the originating card when closed. Dialogue retains speaker labels and timestamps; action entries appear as scene context.

The parser expects one episode per TXT and the supplied pack's format:

```text
EPISODE NUMBER: Episode 1
SCENE 01

**JULIANA (Angry):**
Start: (00:15.30) | End: (00:18.00)
"I did not poison her!"
```

MM:SS.fraction and HH:MM:SS timestamps are supported. Other screenplay layouts need a parser adapter. Speaker aliases are not resolved into a character identity graph. Current per-window validation scans entries, so dense worst-case per-episode complexity is O(N³); larger catalogues would benefit from interval indexes.

## 3. Setup and run

### Requirements and API settings

Use Python 3.10+ and a Gemini API key with access to a structured-output model. Keep the supplied screenplay folder beside `code`, or pass another input location.

```bash
cd /home/bsric/Desktop/proj/code
```

If you do not already have `.env`, copy the example once:

```bash
cp .env.example .env
```

Edit `.env` locally:

```dotenv
GEMINI_API_KEY=your_actual_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Your existing `.env` is preserved during this refactor, with Gemini settings retained. There is no need to run `source .env`; `main.py` loads it automatically. `--model` overrides the model from `.env`. Model availability and quota depend on your Google project; use a supported model available to your key. Requests send shortlisted screenplay content to Google. Keep credentials, confidential screenplays, and derived reports private.

### Small connection test

Process the first episode and send at most one candidate to Gemini:

```bash
python3 main.py --limit-episodes 1 --max-candidates 1
```

A valid result can contain zero promos if Gemini rejects the candidate as non-standalone. That is different from an API failure, which prints `Error:` and exits with a nonzero status.

### Full run

```bash
python3 main.py
```

Defaults process all episode TXT files, shortlist at most four candidates per episode, and space API request starts by at least six seconds. For 50 episodes, that is at most 200 initial requests; retries can increase the count. Requests are sequential, so the complete run can take several minutes. The console prints per-candidate progress and final API/token totals.

Open the report:

```bash
xdg-open report/report.html
```

It also opens directly through your file manager; a web server is unnecessary.

### Custom input and ranking controls

```bash
python3 main.py \
  --input '/path/to/screenplays' \
  --output report \
  --model gemini-3.5-flash-lite \
  --max-candidates 6 \
  --shortlist-fraction 0.20 \
  --promos-per-episode 2 \
  --min-duration 25 \
  --max-duration 50 \
  --iou-threshold 0 \
  --request-interval 10
```

### Arguments passed to `main()` and `run(args)`

`main(argv=None)` accepts an optional list of CLI strings for programmatic use. When run in the terminal, `argv=None` makes `argparse` read the terminal arguments. It produces an `argparse.Namespace`, passed to `run(args)`.

| Argument | Default | Effect |
|---|---|---|
| `--input PATH` | Supplied sibling screenplay folder | One TXT file or folder containing episode TXT files |
| `--output DIR` | `code/report` | Destination directory; writes only `report.html` |
| `--model ID` | `GEMINI_MODEL`, otherwise `gemini-3.5-flash-lite` | Gemini model used for evaluation |
| `--limit-episodes N` | All files | Process the first N files in filename order; N must be positive |
| `--max-candidates N` | `4` | Cap shortlisted Gemini evaluations per episode; N must be positive |
| `--shortlist-fraction F` | `0.15` | Fraction shortlisted before applying the cap; must be in (0, 1] |
| `--promos-per-episode N` | `3` | Maximum selected promos per episode after semantic rejection and NMS |
| `--min-duration SECONDS` | `20` | Minimum candidate span; must be at least 20 |
| `--max-duration SECONDS` | `60` | Maximum candidate span; must be at most 60 and at least the minimum |
| `--iou-threshold F` | `0.40` | Suppress clips above this overlap ratio; [0, 1], with 0 forbidding overlap |
| `--request-interval SECONDS` | `6` | Minimum interval between API request starts; [0, 60] |
| `--help` | — | Show CLI usage and exit without making requests |

For example, `python3 main.py --limit-episodes 2 --max-candidates 1` gives `run(args)` `args.limit_episodes == 2` and `args.max_candidates == 1`; other fields keep their defaults.

### Troubleshooting

- **Missing API key:** check `GEMINI_API_KEY` in `code/.env` or the exported environment.
- **HTTP 400:** request/schema or selected model compatibility issue.
- **HTTP 401/403:** invalid key, permissions, or model access issue.
- **HTTP 404:** the selected model is unavailable; choose an accessible model with `--model`.
- **HTTP 429:** rate limit or quota exhausted. Longer request spacing can help rate limits; it cannot fix exhausted quota.
- **Invalid/blocked/incomplete model output:** the pipeline stops rather than fabricating a result. Inspect the candidate ID printed in the error.
- **No TXT files:** supply the correct folder/file with `--input`.
