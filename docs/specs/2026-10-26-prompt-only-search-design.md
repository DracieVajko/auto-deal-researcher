# Prompt-Only Search and Launcher Scripts — Design

Date: 2026-10-26
Status: approved in session (part 1 category inference, part 2 wizard and launchers)
Companion spec: `docs/specs/2026-10-26-product-domains-design.md`

## 1. Problem

Today the everyday command is:

```bash
python -m src.cli run --prompt "DJI drone under 350 euros" --condition refurbished --category electronics
```

The user has to pre-classify their own request. The intent lives entirely in the
free-text prompt: the user writes there whether they want brand new, used, a price
limit, a brand, free shipping — everything. The application should read condition,
category and the rest of the filters from the prompt itself, and the normal path
should need exactly one input: the prompt.

The user also wants simple cross-platform launchers: a `.bat` for Windows and a
`.sh` for Linux/macOS that open a small interactive wizard, so the tool is usable
without remembering CLI flags.

## 2. Verified facts (current state)

* `run`'s `--condition` and `--category` already default to `"any"`; both flags are
  optional today. Omitting them does not fail.
* **Condition is already inferred from the prompt.** `parse_filters_from_text`
  (deterministic, sk/cs/de/en/pl since the product-domains work) and
  `LLMClient.extract_search_filters` (`src/llm/client.py:256`) both resolve it, and
  `app.py` adopts the inferred value when the CLI left `"any"`.
* **Category is not inferred.** `extract_search_filters`'s system prompt
  (`client.py:258-267`) does not ask for a category, and `resolve_filters` returns
  only `SearchFilters`. With `"any"`, every condition-matching shop stays a
  candidate and the site-selection LLM narrows the list.
* `SearchFilters` has no category field. Any unknown key in an LLM payload lands in
  `extras` (`filters_from_mapping`), so a `category` key must be read out before the
  mapping, not after.
* Canonical categories: `electronics`, `appliances`, `auto`, `home`, `hobby`,
  `general`.
* Launcher scripts exist but are pass-through wrappers that *require* arguments and
  always forward `--condition any --category any`
  (`scripts/run_once.ps1`, `scripts/run_once.sh`). `setup.bat` has the established
  Python-discovery pattern (`python`, else `py -3`).
* Site selection is cached per `(condition, category)` and reads no browser page, so
  the chosen shop names can be reported before the search runs.

## 3. Goals

* G1 — A single natural-language prompt is enough: condition, **category**, price,
  brand, shipping, location and sort come from the prompt via the model. Condition
  and the others already work; category is added.
* G2 — A wrong or missing category guess never makes the run fail and never narrows
  shops beyond what `--category any` allows.
* G3 — Offline behaviour is preserved: without an LLM everything runs as today
  (deterministic parsing; category stays `any`).
* G4 — New command `python -m src.cli ask`: a prompt-only wizard that shows what the
  system understood **before** searching, then runs the search and prints the report
  paths.
* G5 — Thin launchers: `scripts/search.bat` (Windows), `scripts/search.sh`
  (Linux/macOS) start `ask` using the existing Python-discovery pattern.

## 4. Non-goals

* A full menu app (browse results, doctor, login entries) — the user chose the
  prompt-only wizard explicitly.
* Deterministic category word mapping (`"drone" → electronics`) — brittle, and it
  contradicts the domain-layer philosophy just established.
* Making `run` interactive when `--prompt` is missing — scheduled jobs and
  automation must keep failing fast; a hanging stdin is a regression.
* Changing `diamond-search`, `search` or `monitor` behaviour. They may adopt
  inference later through the same shared resolver.

## 5. Category inference (G1–G3)

### 5.1 One LLM call, one extra key

The existing filter-extraction call gains a `category` key. No second LLM request
is introduced:

```text
... condition (new|used|refurbished|open_box|marketplace), category
(electronics|appliances|auto|home|hobby|general), brand, location, ...
```

`resolve_request()` in `src/searcher/filters.py` becomes the app-level entry point:

```python
@dataclass(frozen=True)
class ResolvedRequest:
    filters: SearchFilters
    category: str | None      # validated canonical value, or None

async def resolve_request(prompt, cli_filters, llm=None) -> ResolvedRequest: ...
```

* `category` is popped from the raw LLM payload **before** `filters_from_mapping`
  (otherwise it would leak into `extras`).
* Validation: the value, folded and stripped, must equal one canonical category.
  Anything else (`None`, `""`, `"drone"`, a list) becomes `None` and a debug log
  line records it. `None` means: behave exactly as today.
* `resolve_filters(prompt, cli_filters, llm)` is kept as a thin wrapper returning
  `resolve_request(...).filters`, so every existing caller and test is unchanged.

### 5.2 Precedence

`CLI --category` > LLM inference > `"any"`:

* `run --category electronics` pins the category; inference is skipped.
* `run --category any` (now an explicit choice) suppresses inference and searches
  everything, as today.
* `--category` default changes from `"any"` to unset (`None`): unset enables
  inference. Automation that passed `--category any` explicitly sees no change.
* An invalid explicit value fails fast with the list of allowed categories and
  exit code 1, mirroring the `--domain` rule from the product-domains work.
* The condition path is untouched: explicit `--condition` still wins, the inferred
  value is used otherwise.

### 5.3 Where the resolved category flows

`_run_async` (and `ask`) pass the category into the existing `searcher.search(...)`
→ `_select_sites(condition, category)` path. Nothing inside site selection changes;
inference only decides which string reaches it.

## 6. The `ask` wizard (G4)

`python -m src.cli ask` — interactive by default, optional flags
`--country`/`--max-sites` seed the answers (useful over SSH, harmless otherwise).

Flow:

1. **Prompt** — the only mandatory question: *"What are you looking for?"*.
   Whitespace-only answers re-prompt. `Ctrl+C` aborts before anything runs.
2. **Country** — defaults to `search.user_country`; Enter accepts the default.
   Stored uppercased.
3. **Max shops** — defaults to `search.max_sites`; non-numeric re-prompts.
4. **Understanding summary**, printed *before* the search starts:

   ```text
   Understood: condition=refurbished, category=electronics, max_price=350 EUR,
   brand=DJI, shipping=free
   Category inferred by the model; override with --category.
   Shops: alza, bazos
   ```

   Values that are `None` are omitted. Without an LLM the line says
   `category=any (no LLM available)`. The shop list arrives through a small
   `plan` callback: `run_search` accepts an optional callable that receives the
   selected site names right before rounds start. `run` passes nothing; `ask`
   prints. No selection logic is duplicated.
5. **Search** — the shared runner (below).
6. **Result** — deal count and the JSON/Markdown paths, same information `run`
   echoes today, plus the report directory.

### 6.1 Shared runner

The body of `_run_async` (config load → filters → browser → search → storage →
report) is extracted into:

```python
async def run_search(config, prompt, *, condition="any", category=None,
                     winners=None, output_format=None, plan=None,
                     cli_filters_kwargs=None, domain=None) -> SearchOutcome
```

`SearchOutcome` carries `deal_count`, `sites`, `json_path`, `md_path`. `run` keeps
its exact flags and final echo; `ask` calls the same function after collecting
answers. This is a refactor, not a behaviour change: `run`'s observable output and
exit codes stay identical.

## 7. Launchers (G5)

* `scripts/search.bat` — same Python discovery as `setup.bat` (`python`, else
  `py -3`, else error with an install hint), `cd` to repo root,
  `python -m src.cli ask`, `pause` at the end so a double-click window stays open.
  Exit code propagates. Messages are pure ASCII (no cmd.exe codepage traps).
* `scripts/search.sh` — `python3`, else `python`, else error; `exec … -m src.cli
  ask`. Works on Linux and macOS; README notes `chmod +x` after clone.
* `run_once.ps1` / `run_once.sh` — updated to forward `--condition`/`--category`
  **only when provided** (empty no longer forces `any`), so the old wrappers gain
  inference too instead of blocking it.

## 8. Documentation

* README: a "Prompt-only search" subsection under Usage (the prompt carries
  condition/category/price; flags remain overrides) and a "Launcher scripts"
  subsection for `search.bat` / `search.sh`.
* CHANGELOG: Added entries for inference, `ask`, and the launchers.

## 9. Error handling

| Case | Behaviour |
|---|---|
| LLM returns a category outside the enum | Ignored → `any`, debug log; run continues |
| LLM unavailable / offline | Deterministic filters as today; category `any`; summary states it |
| Explicit `--category no-such` | Error listing allowed values, exit 1 |
| Filter parse raises (e.g. nonsense price) | Same as `run` today: error message, exit 1 |
| Wizard: empty prompt | Re-prompt |
| Wizard: `Ctrl+C` at any question | "Aborted.", exit 1, nothing written |
| Search finds no deals | Report with 0 results is still written (today's behaviour) |
| Launcher finds no Python | Install hint, exit 1 (same as `setup.bat`) |

The inference layer can only broaden or pin the shop list to a real category; it
can never crash a run that would work today.

## 10. Testing

* **filters/`resolve_request`** — payload with valid `category` → returned; with
  `"drone"`/list/`None` → `None`; `category` never appears in `extras`; no LLM →
  `category=None`; `resolve_filters` wrapper unchanged semantics.
* **client** — the extraction system prompt now names the category enum (string
  assertion, no network).
* **`run` command (CliRunner)** — invalid `--category` exits 1 with the allowed
  list; explicit `--category electronics` overrides the stub LLM's guess; unset
  `--category` consumes the stub's inferred value; `--category any` skips
  inference.
* **`ask` command (CliRunner)** — scripted stdin answers; stub `run_search`;
  assert the summary contains `condition=…`/`category=…` and that `run_search`
  received the inferred category; empty prompt re-prompts; non-numeric max-sites
  re-prompts; `plan` callback prints the shop names.
* **Launchers** — `bash -n scripts/search.sh`; the `.bat` is reviewed by inspection
  and verified by the user on Windows (no cmd.exe in the dev environment — this is
  recorded honestly in the plan).
* Full suite stays green (baseline 509 passed, 11 skipped); every changed file
  passes scoped ruff.

## 11. Risks

* **Mis-guessed category narrows the shop list** (e.g. a home appliance read as
  electronics). Mitigations: the summary is printed *before* the search so the
  user sees it; `--category any` re-widens; the wizard answers nothing about
  category, so there is no second failure path.
* **Refactor of `_run_async`** touches the most-used command. Mitigation: the
  extraction is behaviour-preserving and covered by existing tests plus new
  command-level tests.
* **`.bat` encoding traps** — messages kept ASCII, file CRLF, no diacritics.

## 12. Decisions log (from the brainstorm)

| Decision | Choice |
|---|---|
| Category when not passed | LLM infers it (not "always any", not heuristics) |
| Launcher scope | Prompt-only wizard, not a full menu |
| Where the menu lives | Python `ask` command; `.bat`/`.sh` are thin launchers |
| `run` semantics | Unchanged; flags remain overrides; only `--category` default becomes auto |
