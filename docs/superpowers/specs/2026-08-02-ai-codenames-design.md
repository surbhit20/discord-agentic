# AI-vs-AI Codenames — Design Spec

## Purpose

A multi-agent system where LLM agents play Codenames against each other (Red team vs Blue team, each with a spymaster and one or more operatives). Primary goal: **experimentation and learning** about multi-agent LLM orchestration — how agents reason, communicate through constrained signals (clues), and collaborate (operative deliberation) — not a polished product or a rigorous benchmark. A CLI runner supports fast iteration; a web UI supports watching games play out visually.

## Architecture

A single core library, consumed by two thin front ends:

```
codenames/
  game/            # pure-Python rules engine, no LLM/framework deps
  agents/          # per-role LLM wrappers, prompts, structured-output schemas
  orchestration/   # LangGraph graph wiring game + agents into the turn loop
  config/          # config loading (YAML) + API key resolution
  cli/             # CLI runner — fast terminal iteration loop
  web/             # FastAPI backend + static HTML/JS/CSS frontend
  events/          # shared event schema emitted by orchestration, consumed by CLI/web
```

`game/`, `agents/`, `orchestration/`, `config/`, and `events/` form the reusable core. `cli/` and `web/` are both just consumers of that core's `run_game(config) -> stream of events` entry point — this keeps prompt/config iteration fast (via CLI) while still supporting a nicer visual view (via web) from the same underlying game logic.

## Game Engine (`game/`)

Pure Python, fully unit-testable in isolation (no LLM calls, no LangGraph).

- **Board**: 25 words drawn from the standard public Codenames word list. Standard color split: starting team 9 words, other team 8, neutral 7, assassin 1.
- **State**: word → color map, revealed/unrevealed flags per word, current team, full clue history, full guess history, win/loss state.
- **Rules enforced by the engine** (never trusted to the LLM):
  - A clue must be a single word, not on the board, and not a substring/derivative of a board word.
  - A guess must target a currently-unrevealed board word.
  - An operative may guess while correct, up to `clue_number + 1` guesses per turn; a wrong-team or neutral guess ends the turn immediately; an explicit pass ends the turn.
  - Guessing the assassin word ends the game immediately (guessing team loses).
  - A team wins when all of their words are revealed.
- **Invalid agent output handling**: if a spymaster/operative response fails validation (bad clue, guess that isn't a real unrevealed board word), the engine issues one retry-with-feedback to that same agent. If the retry is still invalid, the engine treats it as a pass so the game never stalls indefinitely.

## Agents (`agents/`)

- Four base roles: `red_spymaster`, `red_operative`, `blue_spymaster`, `blue_operative`.
- Each role is independently configured with `{provider: anthropic | openai | google, model, temperature}`, using LangChain's chat-model classes (`ChatAnthropic`, `ChatOpenAI`, `ChatGoogleGenerativeAI`) behind a common interface — any role can run any provider/model, enabling cross-provider matches (e.g. Claude spymaster vs GPT spymaster).
- Structured output via Pydantic schemas for reliable parsing:
  - `Clue { word: str, number: int, reasoning: str }`
  - `Guess { word: str, reasoning: str }`
- Agent reasoning text is always captured and surfaced in events/logs/UI — never discarded — since understanding *how* agents reason is a core goal of the project.
- `operatives_per_team` is configurable per game (default `1`). When set higher, operatives run a bounded deliberation loop: each proposes a candidate word + reasoning, sees the other operatives' proposals, for up to a capped number of rounds, then converge on the team's final guess order (default convergence rule: most recent proposal per slot, i.e. last-mover consensus).

## Orchestration (`orchestration/`)

One LangGraph graph instance per game run. Game state is a single typed state object threaded through every node: board, clue/guess histories, current team, current clue, guesses made so far this turn.

Graph flow (conceptual):

```
start_turn
  -> spymaster_clue
  -> validate_clue (conditional: retry spymaster_clue once on invalid, else pass)
  -> operative_phase
       (if operatives_per_team > 1: deliberation subgraph -> consensus)
  -> resolve_guess
  -> continue_guessing? (loop back to operative_phase while correct & guesses remain)
  -> end_turn
  -> check_win (conditional: END if won/assassin, else loop to start_turn for other team)
```

## Config & API Keys (`config/`)

- `.env` holds `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, loaded via `python-dotenv`.
- A `config.yaml` (or an equivalent dict passed programmatically) defines per-role model assignment and `operatives_per_team`. Both the CLI and the web UI accept a config to start a game — no code edits needed to try a new matchup.
- Key resolution lives behind a single function/module boundary. For now it reads from environment variables; when this is later turned into a public demo where users supply their own keys, only that one boundary needs to change.

## CLI Runner (`cli/`)

Takes a config (file path or flags), runs the LangGraph game loop, and prints each turn to the terminal as it happens: board state, clue + reasoning, each guess + reasoning + outcome, turn/game-end summary. This is the fast iteration loop for tuning prompts and trying model/config combinations without touching a browser.

## Web UI (`web/`)

- FastAPI backend: an endpoint to start a game given a config, and an SSE endpoint that streams the same game events live as the orchestration graph produces them.
- Frontend: plain HTML/CSS/JS, no framework — a color-coded board grid and a live transcript panel showing clue → reasoning → guesses → outcome per turn, sourced from the same event stream the CLI prints.

## Shared Event Schema (`events/`)

Both CLI and web UI render the same stream of structured events (e.g. `ClueGiven`, `GuessMade`, `TurnEnded`, `GameEnded`) emitted by the orchestration layer — this is what keeps the two front ends thin and in sync, since neither has its own copy of game logic.

## Testing

- **Game engine**: unit tests with no LLM involvement — board setup/color distribution, clue validation, guess validation, turn transitions, win/assassin conditions.
- **Orchestration**: graph-flow tests using a scripted/fake chat model (no real API calls) to confirm the graph visits the expected nodes/edges for given scripted agent outputs (valid clue, invalid clue triggering retry, wrong guess ending turn, assassin ending game, etc).
- **End-to-end sanity check**: one live run via the CLI with real (cheap) models, manually observed, before considering the initial version done. No automated "is the AI good at Codenames" benchmark — watching agent behavior *is* the point of the project.

## Explicitly out of scope for v1

- Human-in-the-loop play (a human playing alongside/against the agents).
- Saved-game replay viewer (events are logged, but no replay UI yet).
- Multi-game/multi-tenant web UI (one game at a time).
- User-supplied API keys in the web UI (env-var keys only for now; noted above as a localized future change).
