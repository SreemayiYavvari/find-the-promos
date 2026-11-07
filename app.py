"""Streamlit front end for Find the Promos.

Reuses the existing backend unchanged: parser.parse_script, engine.generate/score/
shortlist/suppress, semantic.GeminiEvaluator, main.serialize and report.render_report.
The orchestration loop mirrors main.run() so rankings are identical to the CLI; it is
split into a cheap deterministic "prepare" pass and a Gemini "evaluate" pass so the UI
can show real progress.
"""
import html
import io
import json
import os
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import streamlit as st

from engine import generate, score, shortlist, suppress
from main import load_env, serialize
from parser import parse_script
from report import render_report
from semantic import GeminiEvaluator

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # per screenplay, a guard for public deployments
_ENV_LOCK = threading.Lock()

st.set_page_config(page_title="Find the Promos", page_icon="🎬", layout="centered")

try:  # local convenience only: reads code/.env, never overrides exported variables
    load_env()
except ValueError:
    pass


# --------------------------------------------------------------------------- helpers
def secret_key() -> str:
    try:
        value = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:  # no secrets file configured
        value = ""
    return value or ""


def make_evaluator(api_key: str, model: str, interval: float) -> GeminiEvaluator:
    """GeminiEvaluator reads the key from the environment. Set it only for the
    constructor call, under a lock, so one visitor's key can never leak to another."""
    with _ENV_LOCK:
        previous = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = api_key
        try:
            return GeminiEvaluator(model, request_interval=interval)
        finally:
            if previous is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous


def collect_files(uploads) -> list[tuple[str, bytes]]:
    """Flatten uploaded .txt / .zip files into [(filename, bytes)], sorted by name."""
    found = {}
    for up in uploads:
        data = up.getvalue()
        if up.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    name = Path(info.filename).name
                    if (info.is_dir() or not name.lower().endswith(".txt")
                            or name.startswith(("._", ".")) or "__MACOSX" in info.filename):
                        continue
                    if info.file_size > MAX_UPLOAD_BYTES:
                        raise ValueError(f"{name} in {up.name} is larger than 5 MB")
                    found[name] = zf.read(info)
        else:
            if len(data) > MAX_UPLOAD_BYTES:
                raise ValueError(f"{up.name} is larger than 5 MB")
            found[Path(up.name).name] = data
    return sorted(found.items())


def prepare(files, settings, workdir: Path):
    """Deterministic pass: parse, generate, score, shortlist (no API calls)."""
    prepared, warnings, seen = [], [], set()
    for name, data in files:
        path = workdir / name
        path.write_bytes(data)
        entries, warns = parse_script(path)
        episode = entries[0].episode_id
        if episode in seen:
            raise ValueError(f"Duplicate episode ID: {episode} ({name})")
        seen.add(episode)
        warnings += [f'{name}:{w["line"]}: {w["reason"]}' for w in warns]
        candidates = [score(c) for c in generate(entries, settings["min_duration"], settings["max_duration"])]
        chosen = shortlist(candidates, settings["shortlist_fraction"], settings["max_candidates"])
        prepared.append({"name": name, "episode": episode, "valid": len(candidates), "chosen": chosen})
    return prepared, warnings


def esc(text: str) -> str:
    """Escape Markdown/HTML so screenplay text renders literally."""
    out = html.escape(str(text), quote=False)
    for ch in "\\`*_{}[]()#+-!|~$":
        out = out.replace(ch, "\\" + ch)
    return out


def analyze(files, settings, api_key):
    """Full pipeline with live progress. Raises on any failure, like main.run()."""
    with st.status("Analyzing screenplays…", expanded=True) as status:
        bar = st.progress(0.0, text="Parsing and generating candidate clips…")
        log = st.empty()
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            prepared, warnings = prepare(files, settings, Path(tmp))
        total = sum(len(p["chosen"]) for p in prepared)
        valid = sum(p["valid"] for p in prepared)
        st.write(f"Parsed **{len(prepared)}** episode(s) → **{valid}** valid clip windows → "
                 f"**{total}** shortlisted for Gemini.")
        if total == 0:
            raise ValueError("No valid 20–60 s clip windows were found in these files.")
        evaluator = make_evaluator(api_key, settings["model"], settings["request_interval"])
        selected, done, skipped = [], 0, []
        for item in prepared:
            for index, cand in enumerate(item["chosen"], 1):
                bar.progress(done / total, text=f"{item['episode']}: evaluating {index}/{len(item['chosen'])} "
                                                f"with {evaluator.model} ({done}/{total} done)")
                try:
                    cand.evaluation = evaluator.evaluate(cand)
                except (ValueError, KeyError, TypeError) as exc:
                    # Bad model output after retries: skip this one clip, keep the run alive.
                    skipped.append(f"{cand.candidate_id}: {exc}")
                except RuntimeError as exc:  # HTTP/auth/quota/network: stop, like the CLI
                    raise RuntimeError(f"{cand.candidate_id}: {exc}") from None
                done += 1
            evaluated = [c for c in item["chosen"] if c.evaluation]
            picks = suppress(evaluated, settings["iou_threshold"], settings["promos_per_episode"])
            selected.extend((c, item["name"]) for c in picks)
            log.caption(f"Last finished: {item['episode']} — {item['valid']} valid windows, {len(picks)} promos kept")
        bar.progress(1.0, text=f"Evaluated {total}/{total} candidates")
        selected.sort(key=lambda it: (-it[0].evaluation["viral_score"], -it[0].scores["raw"],
                                      it[0].episode_id, it[0].start_sec))
        promos = [serialize(c, src, rank) for rank, (c, src) in enumerate(selected, 1)]
        stats = {"episodes": len(prepared), "valid_windows": valid, "evaluated": total,
                 "api_attempts": evaluator.calls, "seconds": round(time.perf_counter() - started, 1),
                 "tokens": dict(evaluator.usage), "model": evaluator.model, "skipped_candidates": len(skipped)}
        status.update(label=f"Done — {len(promos)} ranked promos", state="complete", expanded=False)
    return promos, warnings + [f"SKIPPED (invalid Gemini output) {m}" for m in skipped], stats


def report_html(promos) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        render_report(Path(tmp), promos)
        return (Path(tmp) / "report.html").read_bytes()


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def render_transcript(promo):
    lead = next((e["speaker"] for e in promo["transcript"] if e["kind"] == "dialogue"), "")
    for e in promo["transcript"]:
        stamp = f'`{e["start_timestamp"]} – {e["end_timestamp"]}`'
        if e["kind"] == "action":
            st.markdown(f"*{esc(e['content'])}*  \n{stamp}")
        else:
            with st.chat_message("user" if e["speaker"] == lead else "assistant", avatar=None):
                st.markdown(f"**{esc(e['speaker'])}** {stamp}  \n{esc(e['content'])}")


def render_card(promo):
    seg = promo["segments"][0]
    with st.container(border=True):
        left, right = st.columns([4, 1])
        left.subheader(f"#{promo['rank']} · {promo['episode_id']}")
        right.metric("Score", f"{promo['viral_score']:g}/100", label_visibility="collapsed")
        st.caption(f"⏱ {seg['start_timestamp']} – {seg['end_timestamp']}  ·  {promo['duration_sec']:.1f}s  ·  "
                   f"source: {seg['source_file']}")
        st.markdown("**🪝 Hook**")
        st.markdown(f"> {esc(promo['hook']['quote'])}")
        st.markdown("**⛓ Cliffhanger**")
        st.markdown(f"> {esc(promo['cliffhanger']['quote'])}")
        st.markdown(f"**Why it works:** {esc(promo['justification'])}")
        h = promo["heuristic_scores"]
        st.caption(f"Rule scores — hook {h['hook']:.1f} · cliffhanger {h['cliffhanger']:.1f} · "
                   f"coherence {h['coherence']:g}")
        with st.expander("View conversation"):
            render_transcript(promo)
        st.download_button("⬇ Download this promo (JSON)", dumps(promo), f"promo_{promo['rank']:02d}_{promo['candidate_id']}.json",
                           "application/json", key=f"dl_{promo['candidate_id']}")


# --------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API key", type="password", value="",
                            placeholder="Using deployment secret" if (secret_key() or os.environ.get("GEMINI_API_KEY")) else "Paste your key",
                            help="Kept only in this session. Falls back to the GEMINI_API_KEY secret / environment variable.")
    model = st.text_input("Gemini model", value=os.environ.get("GEMINI_MODEL") or GeminiEvaluator.default_model)
    st.subheader("Ranking controls")
    limit_eps = st.number_input("Max episodes (0 = all)", 0, 500, 0)
    max_candidates = st.number_input("Max candidates per episode", 1, 20, 4)
    promos_per_episode = st.number_input("Max promos per episode", 1, 10, 3)
    shortlist_fraction = st.slider("Shortlist fraction", 0.05, 1.0, 0.15, 0.05)
    min_d, max_d = st.slider("Clip duration (s)", 20, 60, (20, 60))
    iou = st.slider("Overlap threshold (IoU)", 0.0, 1.0, 0.40, 0.05, help="0 forbids any overlap")
    interval = st.slider("Seconds between API calls", 0, 60, 6,
                         help="Raise if you hit HTTP 429 rate limits; lower on a paid quota.")
    st.caption("Requests send shortlisted screenplay text to Google Gemini.")

settings = {"model": model.strip(), "max_candidates": int(max_candidates),
            "promos_per_episode": int(promos_per_episode), "shortlist_fraction": float(shortlist_fraction),
            "min_duration": float(min_d), "max_duration": float(max_d),
            "iou_threshold": float(iou), "request_interval": float(interval)}

# --------------------------------------------------------------------------- main page
st.title("🎬 Find the Promos")
st.write("Upload timestamped screenplay `.txt` files (one episode each, or a `.zip` of them). "
         "Get ranked 20–60 s promo clips with hook, cliffhanger and rationale.")

uploads = st.file_uploader("Screenplay files", type=["txt", "zip"], accept_multiple_files=True)

try:
    files = collect_files(uploads) if uploads else []
except (ValueError, zipfile.BadZipFile) as exc:
    files = []
    st.error(f"Could not read upload: {exc}")
if limit_eps:
    files = files[:int(limit_eps)]
if files:
    st.caption(f"{len(files)} episode file(s) ready: {files[0][0]}" + (f" … {files[-1][0]}" if len(files) > 1 else ""))
    if len(files) * settings["max_candidates"] * max(settings["request_interval"], 1) > 600:
        est = len(files) * settings["max_candidates"] * settings["request_interval"] / 60
        st.info(f"Up to {len(files) * settings['max_candidates']} Gemini calls, roughly {est:.0f}+ min at the current spacing. "
                "Tip: try 1–2 episodes first.")

if st.button("Analyze", type="primary", disabled=not files):
    key = api_key.strip() or secret_key() or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        st.error("Add a Gemini API key in the sidebar (or set the GEMINI_API_KEY secret).")
    else:
        try:
            promos, warnings, stats = analyze(files, settings, key)
            st.session_state["result"] = {"promos": promos, "warnings": warnings, "stats": stats}
        except (ValueError, RuntimeError, OSError) as exc:
            st.session_state.pop("result", None)
            st.error(f"Error: {exc}")

result = st.session_state.get("result")
if result:
    promos, stats = result["promos"], result["stats"]
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Promos", len(promos))
    c2.metric("Episodes", stats["episodes"])
    c3.metric("Gemini calls", stats["api_attempts"])
    c4.metric("Time", f'{stats["seconds"]}s')
    d1, d2 = st.columns(2)
    d1.download_button("⬇ All promos (JSON)", dumps(promos), "promos.json", "application/json", use_container_width=True)
    d2.download_button("⬇ Standalone report (HTML)", report_html(promos), "report.html", "text/html", use_container_width=True)
    if result["warnings"]:
        with st.expander(f"Warnings and skipped clips ({len(result['warnings'])})"):
            st.code("\n".join(result["warnings"]))
    with st.expander("Run details"):
        st.json(stats)
    if stats.get("skipped_candidates"):
        st.warning(f"{stats['skipped_candidates']} candidate clip(s) were skipped because Gemini kept returning "
                   "quotes that could not be matched to the script. Details are under Warnings.")
    if not promos:
        st.warning("No standalone promos met the selection rules. Try raising max candidates or the shortlist fraction.")
    for promo in promos:
        render_card(promo)
    st.caption("Scores are editorial signals, not conversion predictions. Verify timings against footage.")
