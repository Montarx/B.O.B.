# B.O.B. — Beyond Orbit Buddy

A local-first, Greek-speaking desktop AI companion for Windows 11.

B.O.B. hears you, talks back, controls your PC, remembers what you ask him to
remember, and looks at your screen only when you tell him to. He runs on free,
local software — no paid API is required for anything in the core.

> **Status: Phase 1.** The foundation (Phase 0) and the desktop shell are in
> place: design system, animated core, state-driven UI, developer tooling.
> Every provider is still a mock — there is no microphone, no local model and no
> PC control yet. Those are Phases 2–6.

![B.O.B. listening](docs/images/shell-listening.png)

<sub>B.O.B. in `LISTENING`. The core is an armillary instrument with a mechanical
iris; the membrane around it reacts to the microphone.</sub>

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
| **Design is a system** | Every colour, size and duration is a token. A test fails if a stylesheet uses an off-palette colour. |
| **Accessible by test** | WCAG contrast ratios are asserted, not assumed. Reduced motion keeps every state distinguishable. |

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

pip install -e ".[ui,dev]"
```

`[ui]` pulls in PySide6. Leave it out and the shell will tell you what is missing;
`--headless` still works without it.

Then launch him:

```bash
python -m bob                # the desktop shell
python -m bob --dev          # ...with the developer state switcher (F12)
python -m bob --demo         # ...and start the scripted walkthrough immediately
python -m bob --headless     # boot the kernel only, no window (what CI runs)
```

Run the tests:

```bash
pytest                       # 251 tests; UI tests run offscreen, no display needed
ruff check . && mypy         # lint and strict type check
```

## The interface

The visual identity is **"Orrery"** — an armillary sphere, an antique
astronomical instrument, rendered matte and modern. The core's signature is a
**mechanical iris**: six blades meeting at a hexagonal opening over a dark well.
The light at B.O.B.'s centre is the *edge* where those blades meet, not a glow
filter.

Every state has its own behaviour, and the animation carries meaning rather than
decoration:

| State | The core does this |
|---|---|
| `OFFLINE` | dormant; iris sealed, no motion |
| `IDLE` | slow breathing; the instrument at rest |
| `WAKE_DETECTED` | a flinch — iris snaps open, orbits kick |
| `LISTENING` | iris wide, membrane reacting to the microphone |
| `TRANSCRIBING` | iris narrows to a slit; locked, mechanical spin |
| `THINKING` | orbits accelerate and diverge; more data nodes |
| `EXECUTING` | orbits harmonise; the status ring sweeps as progress |
| `SPEAKING` | membrane driven by B.O.B.'s own output |
| `ERROR` | motion stalls into a slow asymmetric pulse — never a flash |

| Idle | Thinking | Executing |
|---|---|---|
| ![idle](docs/images/shell-idle.png) | ![thinking](docs/images/shell-thinking.png) | ![executing](docs/images/shell-executing.png) |

### Keyboard

| Key | Action |
|---|---|
| `Ctrl+K` | focus the input |
| `Ctrl+L` | clear the conversation |
| `F12` | developer state switcher (`--dev` only) |
| `F9` | start/stop the demo scenario (`--dev` only) |

### Accessibility

Body text is 13px and nothing is smaller than 9px. Every ink colour clears WCAG
AA on every surface, and the status hues clear AA for large text — both asserted
in `tests/test_theme.py`. `ui.reduced_motion = true` stills the animation while
keeping colour and iris aperture, so no state becomes ambiguous. Nothing
flashes.

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
    ui/            the desktop shell
        theme/     design tokens, colour maths, stylesheet, fonts, easing
        widgets/   primitives, core layers, panels, chrome, conversation
        windows/   main window, developer overlay
        bridge.py  the only file importing both Qt and the kernel
    dev/           demo scenarios and mock telemetry (never shipped behaviour)
    utils/         logging, paths
tests/
```

The one architectural fence: **`src/bob/ui/` may import the kernel; nothing in
the kernel may import Qt.** That is what keeps the core testable headless, and
it is why `python -m bob --headless` still works with PySide6 uninstalled.

See `ARCHITECTURE.md` for how these communicate, and `ROADMAP.md` for what
happens next.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the design, the reasoning, and the risks
- [`ROADMAP.md`](ROADMAP.md) — phases, scope and exit criteria

## Language

B.O.B. **speaks** Greek. The **code and documentation** are English.

## License

MIT
