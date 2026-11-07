# find-the-promos

Detects and ranks promotional moments in microdrama-style screenplay text.

## Usage

```python
from promo_detection import detect_and_rank_promos

results = detect_and_rank_promos(screenplay_text, top_k=3)
for match in results:
    print(match.score, match.segment)
```

## Run tests

```bash
python -m unittest -v
```