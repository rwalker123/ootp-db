---
name: free-agents
description: Search for free agents matching natural language criteria (position, age, stats, personality, injury risk). Invoke when the user asks to find, search, or list free agents. The user's message is the full search criteria in plain English.
---

Read `../../../skills/free-agents/prompt.md` and follow the instructions. Use the user's full message as the search criteria wherever the prompt references $ARGUMENTS. If no criteria were provided, treat $ARGUMENTS as blank and default to all free agents (no filters, ORDER BY rating_overall DESC) — do not ask for criteria.
