# Find the Promos

A Gemini-assisted tool that finds and ranks 20–60 second promo clips in timestamped microdrama screenplays. For each promo it returns the episode, exact start/end timestamps, the hook, the cliffhanger and a one-line reason, plus the full timestamped conversation so an editor can check it on footage.

You can use it two ways, both on the same backend:

- **Streamlit web app** (`app.py`): upload screenplays, click **Analyze**, browse ranked cards, download JSON/HTML.
- **Command line** (`main.py`): writes one self-contained `report/report.html`.

> Design rule: **the model judges, code decides the cut.** Gemini never writes a timestamp. Every hook and cliffhanger it returns is mapped to a real script entry.

---

## 1. Quick start

### Web app

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env            # add GEMINI_API_KEY (or paste it in the app sidebar)
nano .env
streamlit run app.py
```

1. Upload one or more screenplay `.txt` files, or a `.zip` of them (one episode per file).
2. Optionally adjust the sidebar settings.
3. Click **Analyze**, watch the progress bar, then browse the ranked cards.
4. Expand **View conversation** on any card; download one promo as JSON, all promos as JSON, or a standalone HTML report.

Tip: test on 1–2 episodes first (sidebar: *Max episodes*). A full 50-episode run made 204 Gemini attempts and took about 21 minutes (1,276 s) with the default 6 s request spacing; the browser tab must stay open.

### Command line

The CLI uses only the Python standard library.

```bash
# connection test: first episode, at most one Gemini call
python3 main.py --input /path/to/screenplays --limit-episodes 1 --max-candidates 1

# full run
python3 main.py --input /path/to/screenplays
xdg-open report/report.html      # or open the file in any browser
```

---

## 2. Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo (`.env` and `.streamlit/secrets.toml` are git-ignored).
2. At [share.streamlit.io](https://share.streamlit.io) choose **New app** → your repo → branch `main` → main file `app.py` (Python 3.10+).
3. Optional: **Advanced settings → Secrets**: `GEMINI_API_KEY = "your_key"`. Without it, each visitor pastes their own key in the sidebar.

Notes for a public deployment:

- A key pasted in the sidebar lives only in that visitor's session; it is never shared with other sessions.
- A shared secret key can be used by every visitor. Don't deploy it publicly with a key you can't afford to have used.
- Each screenplay file is limited to 5 MB (the app enforces this; `.streamlit/config.toml` allows uploads up to 50 MB per file, which covers a zip of a full show).
- Screenplay text is sent to Google Gemini. Keep confidential scripts and reports private.

---

## 3. Settings

| Setting (app sidebar / CLI flag) | Default | Effect |
|---|---|---|
| Gemini API key / `GEMINI_API_KEY` | none | Required. Sidebar, Streamlit secret, environment variable or `.env` |
| Gemini model / `--model` | `GEMINI_MODEL`, else `gemini-3.5-flash-lite` | Model used for evaluation |
| Max episodes / `--limit-episodes N` | all | Process only the first N files in filename order |
| Max candidates per episode / `--max-candidates N` | 4 | Cap on clips sent to Gemini per episode |
| Shortlist fraction / `--shortlist-fraction F` | 0.15 | Fraction of valid windows shortlisted before the cap; (0, 1] |
| Max promos per episode / `--promos-per-episode N` | 3 | Maximum kept per episode after rejection and overlap removal |
| Clip duration / `--min-duration`, `--max-duration` | 20–60 s | Minimum at least 20, maximum at most 60 |
| Overlap threshold / `--iou-threshold F` | 0.40 | Suppress clips above this overlap ratio; 0 forbids all overlap |
| Seconds between API calls / `--request-interval S` | 6 | Minimum gap between request starts; 0–60 |
| `--input PATH` (CLI) | — | One TXT file or a folder of episode TXT files |
| `--output DIR` (CLI) | `report` | Writes only `report.html` |

`.env` is loaded automatically (no `source` needed) and only reads `GEMINI_API_KEY` and `GEMINI_MODEL`; variables already exported take precedence.

---

## 4. How it works

| Step | Who | What happens |
|---|---|---|
| Parse | Code | Each dialogue/action/camera block becomes an entry with episode, scene, speaker, start/end and source line. Concurrent tracks keep their own timestamps: a camera shot and a line spoken together do not add time. A missing end time is estimated at 2.5 words per second, capped at the next same-track start, and a warning is reported. |
| Generate windows | Code | Every start/end pair that lasts 20–60 s, stays within one scene and episode, and has 2+ speakers (or intense action). Camera and sound entries cannot create anchors. |
| Cut checks | Code | No dialogue line may be split at either edge. The first spoken line must not open with an ellipsis/dash continuation, and the last must end in terminal punctuation and not be the first half of a split sentence. Camera, sound and action entries are not checked for being cut; they are included if they overlap the window. |
| Shortlist | Code (rules) | Each window scores 0–10 for hook (conflict words, punctuation, intense action, speech density in the first 3 s), cliffhanger (questions, suspense words, interruptions, danger in the final beat) and coherence (opening context, action cues, speaker mix, penalty for ambiguous opening pronouns). `heuristic = 0.4×hook + 0.4×cliffhanger + 0.2×coherence`. Per episode, `min(max_candidates, ceil(valid × fraction))` top windows go to Gemini. |
| Judge | Gemini | Per clip, a structured JSON reply: hook entry, cliffhanger entry, 0–100 editorial score, standalone yes/no, and a one-line reason. The prompt tells the model to treat script text as data. |
| Verify | Code | The hook/cliffhanger must be script entries that overlap the first/last 3 s of the clip (entry-level timing, so the line itself may run past 3 s). Matching ignores quote marks, case and spacing; a quote that equals or is part of (8+ characters) an allowed entry, or sits under a neighbouring entry ID, is replaced with that entry's exact text. Anything else is rejected, retried (3 attempts), then skipped in the app (the CLI aborts instead). Score range and field types are checked. The justification text is **not** checked against the script. |
| Dedupe + rank | Code | Non-standalone clips are dropped. Within an episode, a clip overlapping a higher-ranked one (IoU > threshold) is dropped. Survivors are ranked globally by Gemini score, then heuristic score, then episode and start time. |
| Review | Human | An editor opens the ranked cards, checks them on footage, and downloads the results. |

`IoU = overlap duration / union duration`. The default 0.40 permits some overlap, including a short clip nested in a longer one.

### Input format

One episode per TXT file, in the supplied pack's layout:

```text
EPISODE NUMBER: Episode 1
SCENE 01

**JULIANA (Angry):**
Start: (00:15.30) | End: (00:18.00)
"I did not poison her!"
```

`MM:SS.fraction` and `HH:MM:SS` timestamps are supported. Other layouts need a parser adapter. Speaker aliases are not merged into one character.

---

## 5. Project layout

```text
.
├── app.py                 # Streamlit app: upload, progress, cards, downloads
├── main.py                # CLI: env loading, arguments, orchestration, serialization
├── parser.py              # Screenplay parsing and timestamp normalization
├── engine.py              # Windows, heuristic scores, shortlist, overlap removal
├── semantic.py            # Gemini REST calls, retries, quote grounding/validation
├── report.py              # Standalone HTML report (cards + conversation dialog)
├── requirements.txt       # streamlit (the CLI needs nothing beyond the standard library)
├── .env.example           # GEMINI_API_KEY / GEMINI_MODEL template
├── .gitignore
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

`app.py` reuses `parser.parse_script`, `engine.generate/score/shortlist/suppress`, `semantic.GeminiEvaluator`, `main.serialize` and `report.render_report` directly. Its loop mirrors `main.run()`, split into a deterministic prepare pass and a Gemini evaluate pass so progress can be shown.

### Output

Each promo in the JSON has: `rank`, `candidate_id`, `episode_id`, `duration_sec`, `viral_score` (Gemini 0–100, an editorial signal), `heuristic_scores`, `segments` (episode, source file, start/end timestamps), `hook.quote`, `cliffhanger.quote`, `justification`, and the timestamped `transcript`.

---

## 6. Limits and honest caveats

- **Continuous clips only.** Joined moments and cross-episode montages are not built.
- **Scores are editorial signals**, not conversion predictions, and tend to bunch (in the 50-episode run, 47 of 55 promos scored 85, 88 or 88.5).
- **Shortlisting is rule-based**, so only about 2% of windows (196 of 9,998 in that run) ever reach Gemini; a strong moment the rules score low is never seen. The keyword lists are tuned to this show and to English.
- **Weak cliffhangers, near-duplicates and unproven "standalone" quality** can slip through; see the solution note for examples from the real run.
- **Script timings are not checked against footage.** Verify before posting.
- **Estimated end times** (when a line has no end timestamp) can shift a clip's end and length.
- **Throughput:** requests are sequential and results live only in the session, so a failure partway (for example HTTP 429 quota) loses progress. There is no resume, cache or stored run.
- **Deterministic stage** scans entries per window; worst case per episode is O(N³). Fine for 50 episodes; larger catalogues need interval indexes.
- **No token or cost totals recorded in this write-up.** The app's *Run details* shows token usage per run.

---

## 7. Troubleshooting

- **Missing API key:** set it in the sidebar, the Streamlit secret, `.env`, or the environment.
- **HTTP 400:** request/schema rejected or the model is incompatible.
- **HTTP 401/403:** invalid key, permissions, or model access.
- **HTTP 404:** model unavailable; choose another in the sidebar or with `--model`.
- **HTTP 429:** rate limit or quota exhausted. Longer spacing helps rate limits, not exhausted daily quota; try fewer candidates per episode, a different model, or wait for the quota to reset.
- **Invalid, blocked or incomplete model output:** retried up to 3 times. The app then skips that clip and lists it under *Warnings and skipped clips*; the CLI stops with the candidate ID in the error.
- **No TXT files / bad zip:** check the upload; only `.txt` files (or a zip containing them) are read.
- **Parser error on a file:** it likely uses a different layout, or has several episodes in one file.
