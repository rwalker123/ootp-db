---
name: draft-targets
description: Search for draft prospects or IFA signings matching natural language criteria (position, age, ceiling, tools, personality, college/HS, nation). Invoke when the user asks about draft targets, prospects, or IFA candidates. The user's message is the full search criteria in plain English.
---

Read `../../../skills/draft-targets/prompt.md` and follow the instructions. Use the user's full message as the search criteria wherever the prompt references $ARGUMENTS. If no criteria were provided, treat $ARGUMENTS as blank and default to "top prospects" (no filters, ORDER BY rating_overall DESC) — do not ask for criteria.
