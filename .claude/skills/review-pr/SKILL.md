---
name: review-pr
description: Fetch GitHub PR review comments from Copilot and Claude, analyze them, and fix valid issues. Use when the user wants to process code review feedback on a pull request.
disable-model-invocation: true
user-invocable: true
argument-hint: [pr-number]
---

# PR Review Comment Processor

Process code review comments from GitHub Copilot and Claude on a pull request.
Analyze each comment, generate a report, and fix valid issues.

## Arguments

- `$ARGUMENTS` — optional PR number. If omitted, detect from the current branch.

## Step 1: Identify the PR

If a PR number was provided, use it. Otherwise, detect from the current branch:

```bash
gh pr view --json number,headRefName,url --jq '{number, headRefName, url}'
```

Store the PR number and repo info for subsequent API calls.

## Step 2: Get repo owner/name

```bash
gh repo view --json owner,name --jq '.owner.login + "/" + .name'
```

Use this for all `gh api` calls (as `repos/:owner/:repo` shorthand works too).

## Step 3: Fetch all review comments

### 3a: Copilot inline review comments

Fetch paginated inline review comments (these come from Copilot and human reviewers):

```bash
gh api repos/:owner/:repo/pulls/{PR_NUMBER}/comments --paginate --jq '.[] | {id, node_id, user: .user.login, path, line, original_line, body, created_at, in_reply_to_id, pull_request_review_id}'
```

Filter to comments from `copilot-pull-request-reviewer` or `Copilot` user.
Also collect any human reviewer comments.

**Check for already-processed comments**: For each comment, check if it has an `eyes` reaction.

NOTE on reaction API paths — these differ by comment type:
- **PR review comments** (Copilot inline): `repos/:owner/:repo/pulls/comments/{COMMENT_ID}/reactions`
- **Issue comments** (Claude flat): `repos/:owner/:repo/issues/comments/{COMMENT_ID}/reactions`

Do NOT include the PR number in the reactions path — it's `pulls/comments/{ID}` not `pulls/{PR}/comments/{ID}`.

```bash
gh api repos/:owner/:repo/pulls/comments/{COMMENT_ID}/reactions --jq '[.[] | select(.content == "eyes")] | length'
```

Skip comments that already have an `eyes` reaction — they were processed in a previous run.

### 3b: Claude issue comments

Fetch issue comments (Claude posts flat review comments here):

```bash
gh api repos/:owner/:repo/issues/{PR_NUMBER}/comments --jq '.[] | select(.user.login == "claude[bot]") | {id, node_id, body, created_at}'
```

**Check for already-processed Claude comments**: Same `eyes` reaction check (note: issue comment path):

```bash
gh api repos/:owner/:repo/issues/comments/{COMMENT_ID}/reactions --jq '[.[] | select(.content == "eyes")] | length'
```

Skip Claude comments that already have an `eyes` reaction.

### 3c: Parse Claude's flat markdown into individual findings

Claude's comments are structured as markdown with numbered findings grouped under severity headers (### Critical, ### Important, ### Code Quality / Nice-to-have).

For each Claude comment body, parse out individual findings. Each finding typically has:
- A **numbered bold title** (e.g., `**1. Title here**`)
- A description mentioning file paths (e.g., `In \`golfStatsService.ts\``) and line numbers (e.g., `(line 958)` or `(lines 118-134)`)
- A severity level from the parent `###` header

Extract from each finding:
- `severity`: Critical / Important / Code Quality
- `title`: The bold title text
- `description`: The full finding text
- `file_path`: Extract the file path mentioned (look for backtick-wrapped paths, resolve relative to repo root)
- `line`: Extract the primary line number mentioned
- `source`: "claude"

## Step 4: Convert Claude findings to inline PR review comments

For each parsed Claude finding that has a valid `file_path` and `line`:

1. Verify the file exists in the PR diff:
   ```bash
   gh pr diff {PR_NUMBER} --name-only
   ```

2. Create an inline review comment on the PR so it becomes a resolvable conversation thread:
   ```bash
   gh api repos/:owner/:repo/pulls/{PR_NUMBER}/comments \
     -f body="**[Claude Review — {SEVERITY}]** {FINDING_TITLE}

   {FINDING_DESCRIPTION}

   _Converted from Claude's flat review comment for tracking._" \
     -f path="{FILE_PATH}" \
     -F line={LINE_NUMBER} \
     -f commit_id="{HEAD_SHA}"
   ```

   Get the HEAD SHA with:
   ```bash
   gh pr view {PR_NUMBER} --json headRefOid --jq '.headRefOid'
   ```

3. After converting ALL findings from a Claude comment, mark the original issue comment as processed with an `eyes` reaction:
   ```bash
   gh api repos/:owner/:repo/issues/comments/{COMMENT_ID}/reactions -f content=eyes
   ```

For Claude findings that DON'T have a clear file/line reference (e.g., architectural concerns), keep them in the report but don't create inline comments.

## Step 5: Build unified comment list

Combine into a single list:
- Copilot inline comments (already threads)
- Newly created Claude inline comments (now threads too)
- Claude findings without file/line (report-only)
- Human reviewer comments

Each entry should have: `source`, `severity` (infer for Copilot based on content), `file_path`, `line`, `body`, `thread_id` (GraphQL node ID for resolution).

To get thread IDs for resolution later, fetch review threads via GraphQL:

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes {
            id
            isResolved
            comments(first: 1) {
              nodes {
                id
                databaseId
                body
                author { login }
                path
                line
              }
            }
          }
        }
      }
    }
  }
' -f owner="{OWNER}" -f repo="{REPO}" -F pr={PR_NUMBER}
```

Match threads to comments by `databaseId` to get the thread `id` for resolution.

## Step 6: Analyze each finding

For each unprocessed comment/finding:

1. Read the referenced file and surrounding code context (use the Read tool, not cat)
2. Assess whether the comment is:
   - **Valid — fix needed**: The issue exists in the current code and should be fixed
   - **Valid — already fixed**: The issue was already addressed (code doesn't match what the reviewer described)
   - **Valid — but out of scope**: Real issue but not appropriate for this PR
   - **Style nit**: Subjective preference, not a bug or security issue
   - **Disagree**: The reviewer's assessment is incorrect (explain why)

## Step 7: Present the report

Output a structured report grouped by assessment:

```
## PR Review Comment Analysis — PR #{NUMBER}

### Fixes Needed (X items)
| # | Source | Severity | File | Finding | Assessment |
|---|--------|----------|------|---------|------------|
| 1 | Copilot | High | src/import.py:444 | Issue description | Valid — fix needed |

### Already Fixed (X items)
...

### Out of Scope (X items)
...

### Style Nits (X items)
...

### Disagree (X items)
...
```

Then ask: **"Which items should I fix? (e.g., 'all fixes needed', '1,3,5', 'skip')"**

## Step 8: Fix selected items

For each item the user wants fixed:
1. Read the full relevant code
2. Implement the fix
3. After fixing, reply to the PR review thread:
   ```bash
   gh api repos/:owner/:repo/pulls/{PR_NUMBER}/comments \
     -f body="Fixed in latest push. {BRIEF_DESCRIPTION_OF_FIX}" \
     -F in_reply_to={ORIGINAL_COMMENT_ID}
   ```

## Step 9: Resolve threads

For ALL processed comments (fixed or not):

**Fixed items**: Resolve the thread:
```bash
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "{THREAD_ID}"}) { thread { id isResolved } } }'
```

**Not fixing (out of scope, disagree, style nit)**: Reply with reason, then resolve:
```bash
gh api repos/:owner/:repo/pulls/{PR_NUMBER}/comments \
  -f body="Not fixing — {REASON}" \
  -F in_reply_to={ORIGINAL_COMMENT_ID}
```
Then resolve the thread with the same GraphQL mutation.

**Already fixed**: Reply noting it's already addressed, then resolve.

## Step 10: Mark all source comments as processed

Add `eyes` reaction to every Copilot inline comment that was processed:
```bash
gh api repos/:owner/:repo/pulls/comments/{COMMENT_ID}/reactions -f content=eyes
```

This ensures the next run of `/review-pr` skips these comments.

## Step 11: Run checks

After all fixes are applied, run the pre-commit hooks to catch any issues introduced:
```bash
.venv/bin/pre-commit run --all-files
```

Fix any issues before considering the task complete.

## Important notes

- NEVER resolve threads or reply to comments without explicit user approval
- Present the full report FIRST, then wait for user direction
- When creating inline comments from Claude findings, use the exact file paths from the PR diff (not guessed paths)
- If a Claude finding references multiple files, create a comment on the primary file mentioned
- Handle pagination — PRs can have many comments across multiple pages
- The `eyes` reaction is the "processed" marker — do not use other reactions
- If the user runs `/review-pr` again on the same PR, only NEW unprocessed comments should appear
