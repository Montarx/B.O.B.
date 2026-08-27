# B.O.B. — Beyond Orbit Buddy

A local-first, Greek-speaking desktop AI companion for Windows 11.

B.O.B. hears you, talks back, controls your PC, remembers what you ask him to
remember, and looks at your screen only when you tell him to. He runs on free,
local software — no paid API is required for anything in the core.

> **Status: Phase 0.** The foundation is in place: configuration, logging, event
> bus, state machine, provider interfaces, the tool/permission/audit system, and
> tests. Every provider is currently a mock. There is no window and no microphone
> yet — those are Phase 1 and Phase 2.

---

## Design principles

| Principle | What it means in practice |
|---|---|
| **Local first** | Ollama, faster-whisper, Piper. Cloud adapters are optional extras, never a requirement. |
| **Swappable everything** | LLM, STT, TTS, wake word, VAD, memory and vision are Protocols behind a registry. Changing one is a config edit. |
| **Explicit state** | One state machine with a declared transition table. There is not a single `is_listening` boolean in the codebase. |
| **Structured actions** | The model emits a tool *name* and a JSON *object*, validated against a Pydantic schema. It never emits anything executable. |
| **Ask before harm** | Risk levels gate every action. HIGH risk can never be auto-approved, not even by config. |
| **Personality is data** | B.O.B.'s character lives in `config/personas/bob.md`, not scattered through Python. |
| **Never block the UI** | The core is async and headless; heavy work goes to executors and subprocesses. |

## Requirements

- Python 3.12 or newer
- Windows 11 (the architecture keeps Linux viable; see `ARCHITECTURE.md`)

Phase 0 has three runtime dependencies. Heavy ones arrive with the phase that
needs them.

## Getting started

```bash
git clone https://github.com/Montarx/B.O.B.
cd B.O.B.

python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # Linux/macOS

pip install -e ".[dev]"
```

Run the headless smoke check:

```bash
python -m bob
```

You should see B.O.B. boot, list the providers he wired up, run the `core.ping`
tool through the full validate → authorise → audit → execute pipeline, and shut
down cleanly.

Run the tests:

```bash
pytest
```

## Configuration

Three layers, lowest priority first:

1. `config/default.toml` — committed, the shared baseline. **Do not edit for
   personal settings.**
2. `config/user.toml` — gitignored. Your personal overrides live here.
3. `BOB__SECTION__KEY` environment variables — for one-off runs and CI.

```bash
BOB__LOGGING__LEVEL=DEBUG python -m bob
```

Secrets are read **only** from the environment or `.env` (see `.env.example`).
The loader raises if it finds a `[secrets]` section in TOML, so a key cannot be
committed by accident.

Personality lives in `config/personas/bob.md`. Edit that file to change how B.O.B.
talks — no code change needed.

## Where things are written

Nothing user-generated is written into the repository. By default B.O.B. uses the
OS user-data directory; set `BOB_HOME` to override (useful for a portable install).

```
$BOB_HOME/
    logs/     app.log  ai.log  tools.log  errors.log
    data/     memory database (Phase 7)
    models/   whisper / piper / wake-word weights (Phase 2-5)
    audit/    actions.jsonl — append-only record of everything B.O.B. did
```

## Project layout

```
config/            default.toml, personas/
src/bob/
    core/          events, bus, states, state machine, kernel, errors
    config/        settings schema + layered loader
    providers/     Protocols, registry, and mock implementations
    tools/         tool base, registry/executor, permissions, audit, builtins
    utils/         logging, paths
tests/
```

See `ARCHITECTURE.md` for how these communicate, and `ROADMAP.md` for what
happens next.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the design, the reasoning, and the risks
- [`ROADMAP.md`](ROADMAP.md) — phases, scope and exit criteria

## Language

B.O.B. **speaks** Greek. The **code and documentation** are English.

## License

MIT
