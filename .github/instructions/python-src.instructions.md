---
applyTo: "src/**/*.py"
---

## Python Source Conventions

### Report Generator Pattern

Every report generator must follow this signature and return contract:

```python
def generate_<type>_report(save_name: str, ...) -> tuple[str, dict | None]:
    existing = find_existing_<type>_report(...)
    if existing:
        return existing, None   # cache hit — agent opens and stops

    # ... DB queries, HTML generation ...

    report_path.write_text(html)
    return str(report_path), data_dict  # agent writes placeholder, then opens
```

- `data_dict` contains the key stats needed for the agent's terminal summary
- Reports go to `PROJECT_ROOT / "reports" / "<type>/"` using `pathlib.Path`
- Cache check: compare report mtime against `saves.json` last-import timestamp

### SQL Query Pattern

```python
with engine.connect() as conn:
    rows = conn.execute(text("SELECT ... WHERE x = :x"), dict(x=val)).fetchall()
```

- Always use named params with `dict()` (never f-strings or `%` formatting in SQL)
- Use `.mappings().fetchone()` when you need dict-like column access
- Always filter `league_id = 203` for MLB queries

### Module Imports

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
```

### Logging Style

```python
print(f"✓ {table_name} ({row_count} rows)")
```
