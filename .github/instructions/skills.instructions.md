---
applyTo: ".claude/skills/**"
---

## Skill File Conventions

### Fresh Agent Requirement (mandatory)

Every skill MUST include this block to prevent context bleedover between requests:

```
## IMPORTANT: Always use a fresh agent
Delegate this entire task to a fresh Agent (subagent_type: "general-purpose", model: "sonnet").
Do NOT do the work inline in the current conversation.
```

### CACHED:/GENERATED: Protocol

The Python entry point prints exactly one of:
```
CACHED:/absolute/path/to/report.html
GENERATED:/absolute/path/to/report.html
```

Agent behavior:
- On `CACHED:` — run `open <path>`, print one-liner summary, **STOP**. Do not re-analyze.
- On `GENERATED:` — read the file, replace the HTML placeholder comment with analysis HTML,
  write it back, then run `open <path>`, then print the terminal summary.

### HTML Placeholder Rule

The agent replaces **only** the placeholder comment. It never rewrites HTML structure, tables,
or CSS. Placeholder format: `<!-- PLACEHOLDER_NAME -->` (e.g. `<!-- BATTING_SUMMARY -->`).

### `open` Command Rules

- Always use the full absolute path — never a relative path or a `<placeholder>` string
- `open` must appear in **both** the CACHED branch and the GENERATED branch of the agent steps
- For new players/searches where the path isn't known in advance: instruct the agent to
  "open the path printed after GENERATED:" — make this explicit in the SKILL.md

### Terminal Summary

Every skill should end with a 2–3 line terminal summary and a cost estimate:
```
~8–15K in / ~3–5K out | est. 7–12¢
```
