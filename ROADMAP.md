# B.O.B. — Roadmap

**B.O.B. — Beyond Orbit Buddy**

Each phase ships something that runs, is tested, and is useful on its own. A phase
is done when its exit criteria are met — not when the code is written.

Legend: ✅ done · 🔨 in progress · ⬜ not started

---

## ✅ Phase 0 — Foundation

**Goal:** an architecture that can be tested before any AI exists.

- Project structure, `pyproject.toml`, `.gitignore`, `.env.example`
- Layered configuration (`default.toml` → `user.toml` → env), typed and validated
- Logging on four channels (`app` / `ai` / `tools` / `errors`), rotating JSON lines
- Async event bus with a documented thread-safe bridge
- State machine with a declared transition table
- Seven provider Protocols + registry + mock implementations for all of them
- Tool system: Pydantic validation → permission broker → audit log → execution
- 89 tests; ruff clean; mypy strict clean

**Exit criteria — all met**
- `python -m bob` boots to `IDLE`, runs a tool through the full pipeline, exits clean
- The entire core runs with no Qt, no audio device, no models
- HIGH-risk actions cannot execute unconfirmed, proven by test

---

## ✅ Phase 1 — Desktop shell and sci-fi UI

**Goal:** B.O.B. has a face, driven by real state.

- Design system first: tokens for typography, spacing, radii, panels, borders,
  glow, opacity, motion, icons and status colours — widgets are composed from
  them, never styled ad-hoc
- **Visual identity: "Orrery"** — an armillary instrument with a mechanical
  hexagonal iris. Deliberately not a HUD, not a terminal, not a glowing orb
- Animated core in six layers on one animation clock, with a distinct
  behaviour per state
- PySide6 shell; kernel on its own thread; the bridge in `ui/bridge.py`
- Panels: conversation/activity, current task, system, providers
- Text input, so B.O.B. is usable before the microphone exists
- Developer state switcher (F12) and scripted demo (F9), dev builds only
- Responsive layout from 1366x768 to 4K

**Exit criteria — all met**
- 60 fps target with 2.4–3.1× frame-budget headroom measured (5.4–6.9 ms/frame)
- Typed input drives a full mock round trip; the UI reflects every state
- `reduced_motion` stills motion while keeping every state distinguishable
- No Qt import outside `src/bob/ui/`; the kernel still runs headless
- 251 tests, ruff clean, mypy strict clean

**Deferred to the phase that can honestly do it:** the confirmation dialog is
wired at the presenter level but has no real tool to gate until Phase 6, so the
UI half ships then rather than as dead code now.

---

## ⬜ Phase 2 — Microphone and speech-to-text

**Goal:** B.O.B. hears Greek.

- `sounddevice` capture: one always-open 16 kHz mono stream, frames on a queue
- Silero VAD provider; utterance segmentation with configurable silence timeout
- faster-whisper provider (`large-v3`), running in a thread pool
- Device selection in config, listed in the UI
- Live input level feeding the core animation (the core already consumes it)

**Exit criteria**
- Greek speech transcribes at usable accuracy, including code-switched sentences
- The GUI never stutters during transcription
- Measured latency from end-of-speech to transcript, recorded as a baseline

**Risks:** R5 (Greek WER), R6 (latency)

---

## ⬜ Phase 3 — The brain

**Goal:** B.O.B. thinks, in character, and decides when to act.

- Ollama provider with **streaming** tokens and function calling
- Orchestrator: the one component that drives the state machine
- Prompt assembly: persona file + short-term context + available tool schemas
- Structured tool selection with a bounded repair loop on invalid JSON
- Deterministic fast-path for common Greek commands (no LLM round trip for
  "άνοιξε X")
- Short-term conversation memory (last N turns, in RAM)

**Exit criteria**
- Replies in natural Greek, matching the persona file
- Correctly routes: chat vs. tool vs. "I need to look at the screen"
- A malformed tool call is repaired or refused — never executed
- Changing `config/personas/bob.md` visibly changes his manner, with no code change

**Risks:** R4 (function calling), R6 (latency), R7 (VRAM)

---

## ⬜ Phase 4 — Text-to-speech

**Goal:** B.O.B. talks, and can be interrupted.

- **First: a listening comparison** — Piper vs. XTTS-v2 vs. SAPI Greek voices.
  Pick on quality, then implement. This gate exists because of R2.
- Streaming synthesis: begin speaking sentence one while the rest generates
- Playback as a cancellable consumer task over a chunk queue
- Barge-in v1 (headphones): VAD stays live during `SPEAKING`; sustained speech
  cancels playback and transitions `SPEAKING → LISTENING`
- Output level feeding the core animation

**Exit criteria**
- First audio within ~1.5 s of the model starting to respond
- Saying something mid-sentence stops B.O.B. within ~300 ms
- Cancellation leaves no orphaned audio task

**Risks:** R1 (echo cancellation), R2 (Greek TTS quality) — the two biggest in the project

---

## ⬜ Phase 5 — Wake word

**Goal:** "Μπομπ" wakes him, and nothing else does.

- openWakeWord provider on the audio callback thread
- Custom-trained "Μπομπ" / "Bob" model on synthetic Greek samples
- Threshold, cooldown and a confirmation window to suppress false positives
- Hotkey alternative, always available

**Exit criteria**
- Under ~1 false activation per hour of normal desktop use
- Reliable activation from a few metres at conversational volume
- CPU cost of always-on detection under ~3% of one core

**Risks:** R3 (wake word reliability)

---

## ⬜ Phase 6 — Windows control

**Goal:** B.O.B. does things.

- App control: open / close / find (registry + Start Menu index, not hardcoded paths)
- Files and folders: open, search; **move and delete are MEDIUM/HIGH risk**
- System status: CPU, RAM, disk, top processes (`psutil`)
- Volume and media keys; clipboard; screenshots
- Windows search, websites, Steam game launch
- Multi-step execution: "άνοιξε Discord και Spotify" as two audited actions
- Keyboard/mouse automation, gated behind explicit confirmation

**Exit criteria**
- Every tool declares a risk level and validates its arguments
- The audit log tells the full story of a session
- Nothing HIGH-risk has ever run unconfirmed, verified against the audit log
- Multi-step requests execute in order and report once

---

## ⬜ Phase 7 — Memory

**Goal:** B.O.B. remembers what he was asked to remember, and nothing else.

- SQLite + `sqlite-vec`; embeddings via Ollama
- Three tiers: short-term (session) · long-term (facts and preferences) · task
- Explicit commands: "θυμήσου ότι…", "τι θυμάσαι για…", "ξέχνα ότι…"
- A memory panel in the UI: browse, edit, delete
- Long-term writes stay **deliberate** — `autosave_conversations` remains off

**Exit criteria**
- Nothing reaches long-term memory without an explicit instruction
- Every record is visible in the UI and individually deletable
- Recall demonstrably improves answers across a restart

---

## ⬜ Phase 8 — Vision

**Goal:** B.O.B. can look at the screen, when asked.

- Screenshot capture, downscaled before analysis
- Qwen2.5-VL via Ollama behind `VisionProvider`
- Multi-monitor and single-window capture
- A visible indicator whenever the screen is captured — no silent screenshots

**Exit criteria**
- "Μπομπ, τι βλέπεις;" yields a useful Greek description
- Reads an on-screen error message accurately enough to help
- Capture never happens without an explicit request, verified by audit

**Risks:** R7 (VRAM contention with the main LLM)

---

## ⬜ Phase 9 — Skills and integrations

**Goal:** capabilities without touching the core.

- Skill packages: manifest + tools + optional config schema, discovered at startup
- SpotifySkill, SteamSkill, WeatherSkill, BrowserSkill as the first four
- Per-skill settings and per-skill permissions
- A short guide: "how to write a B.O.B. skill"

**Exit criteria**
- A new skill can be added with zero edits to `src/bob/core/`
- A broken skill fails to load without preventing B.O.B. from starting

---

## ⬜ Phase 10 — Polish, performance and packaging

**Goal:** something installable.

- Animation and startup-time optimisation; measured latency budget per stage
- Model download manager with progress and integrity checks
- PyInstaller build; an installer; optional autostart
- First-run wizard: devices, models, voice, permissions
- Crash reporting and a diagnostics bundle

**Exit criteria**
- A clean Windows 11 machine goes from installer to working B.O.B. unaided
- Idle CPU under ~5%; idle RAM under ~500 MB excluding models
- Every setting in `Settings` is reachable from the UI

---

## Cross-cutting, every phase

- Tests for anything on the safety boundary — non-negotiable
- `ruff check`, `ruff format`, `mypy` clean before a phase is called done
- New settings get a default and a description; no magic numbers in code
- `ARCHITECTURE.md` updated whenever a structural decision changes
- New dependencies justified in the PR that adds them

## Explicitly out of scope for now

Mobile client · multi-user support · cloud sync · a plugin marketplace · anything
requiring a paid API to function.
