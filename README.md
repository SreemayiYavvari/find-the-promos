# Find the Promos — Streamlit app

Upload timestamped screenplay `.txt` files (or a `.zip` of them), click **Analyze**, and get ranked
20–60 s promo clips with hook, cliffhanger, rationale, the full conversation, and JSON downloads.

`app.py` is a thin UI over the unchanged backend (`parser.py`, `engine.py`, `semantic.py`, plus
`main.serialize` and `report.render_report`). Pipeline details and CLI usage: [CLI_README.md](CLI_README.md).

## Run locally
```bash
pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY (or paste it in the sidebar)
streamlit run app.py
```
The CLI still works: `python main.py --limit-episodes 1 --max-candidates 1`.

## Deploy on Streamlit Community Cloud
1. Push this folder to a GitHub repo (`.env` and `secrets.toml` are git-ignored).
2. At share.streamlit.io choose **New app** → your repo → branch `main` → main file `app.py`.
3. **Advanced settings → Secrets**: `GEMINI_API_KEY = "your_key"` (optional; visitors can also paste their own key in the sidebar). Python 3.10+.

## Notes
- Gemini calls are sequential and spaced (default 6 s), so a full 50-episode run at 4 candidates/episode takes ~20 min and keeps the browser tab busy. Test on 1–2 episodes first (sidebar: *Max episodes*).
- A failed Gemini call stops the run with an error (same fail-fast behavior as the CLI); nothing is fabricated.
- Results live in the session only; use the JSON / HTML downloads to keep them.
- Screenplay text is sent to Google Gemini. Do not deploy publicly with a shared key you cannot afford to have used.
