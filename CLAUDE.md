@AGENTS.md

## Claude Code Adapter

The LLM adapter for Claude Code lives at `.claude/skills/<skill-name>/SKILL.md`. It contains
only the frontmatter (name, description, argument-hint) and a one-line instruction to read
the corresponding `skills/<skill-name>/prompt.md` file. When adding support for a new LLM,
create a parallel adapter in that tool's config directory that loads the same prompt.md.
