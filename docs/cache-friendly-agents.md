# Cache-Friendly Agent Workflow

DeepSeek (and most LLM providers) bill cache-miss tokens at ~120x the cost of
cache-hit tokens. For this repo:

| Token type | Price ($/1M) |
|---|---|
| Cache miss | 1.74 |
| Output | 3.48 |
| Cache hit | 0.0145 |

A single cache-busted day can cost more than a month of cache-friendly use.
The system prompt cache is **prefix-based** — it requires the exact same byte
sequence at the start of every request. Any change anywhere in the prefix
invalidates the whole cache.

## Known upstream issue (not fixable here)

OpenCode constructs sub-agent system prompts on the fly. The list of available
tools and agents is not deterministically ordered between calls, so the prefix
cache is invalidated on every sub-agent spawn. This is upstream and must be
fixed by the OpenCode maintainers (sort the agent/tool list).

Reference: <https://github.com/sst/opencode> — track the next sub-agent prompt
sorting change.

## What we control in this repo

These choices visibly affect cache-hit rate. Treat them as engineering
constraints, not style preferences.

### 1. Prefer continuing an existing agent session over spawning a new one

`task_id` reuse keeps the same prefix. Spawning a fresh agent rebuilds the
prefix from scratch and burns cache-miss tokens.

- Yes: `task(task_id="ses_abc123", prompt="follow-up: ...")`
- No: a brand new `task(...)` for every small step.

### 2. Don't spawn sub-agents for trivial work

The cheapest cache-miss is the one you don't generate. Single-file edits,
typos, and known-location lookups should be done in the main session.

### 3. Keep always-loaded instructions small and stable

These files are injected on every turn:

- `AGENTS.md`
- `rules/kicad.md`

Edit them rarely. Every byte change invalidates the cache for every following
request.

### 4. Don't add new entries to `.opencode/agents/` lightly

Each agent expands the agent list and increases the permutation space the
upstream non-determinism can hit. Only add a sub-agent when its workflow truly
cannot be expressed by an existing one.

### 5. Beware per-message directive injection

Wrappers (e.g. `oh-my-openagent`) that inject mode tags, status banners, or
todo-continuation prompts on every turn change the prefix on every request and
can be a major cache-hit killer. If cache-hit rate is unacceptable:

1. Audit which plugin in `opencode.json` is injecting per-turn directives.
2. Disable the plugin or pin it to a single stable directive.
3. Re-measure cache-hit rate before re-enabling anything new.

### 6. Order matters — don't rearrange the prefix

If you must edit `AGENTS.md` or `rules/kicad.md`, append rather than
re-flow. A re-ordered file invalidates all downstream cache.

## Decision rule

Before adding any per-turn directive, plugin, or agent, answer:

> Does this change the always-loaded prefix? If yes, is the cache cost worth
> the benefit?

If the benefit is "feels nicer to use," the answer is no.
