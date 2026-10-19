# AGENTS.md

Instructions for coding agents (Claude Code, Codex, Cursor, etc.) working in this repo.

## What this is

`cua.py` is a single-file agent loop for Anthropic's computer use toolset (`computer_toolset_20260801`, Messages API) on Claude Opus 5.5. Each turn, Claude returns one or more `tool_use` blocks. The block's `name` is the action and `toolset_name` is `"computer"`. `act()` runs each one with `xdotool`, and the loop sends back one `tool_result` per call (echoing `toolset_name`) until Claude stops calling tools. The desktop is either:

- `Docker`: a local container (`claude-desktop`), started by `compose.yaml`. Commands run via `docker exec`.
- `Orgo`: a cloud computer created through `https://www.orgo.ai/api` and deleted when the run ends. The same `xdotool` commands run via `POST /computers/{id}/bash`. `--computer <id>` reuses an existing computer instead, and never deletes it.

With `--orgo-agent`, `run_orgo_agent` skips our loop entirely. It sends one streaming call to Orgo's `POST /api/v1/chat/completions` with `model` (default `claude-opus-5.5`, override with `ORGO_AGENT_MODEL`) and `computer_id`, and Orgo runs the loop. That mode only needs `ORGO_API_KEY`.

## Setup (run in order)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                 # skip if .env already exists; never overwrite it
docker compose up -d --build         # only for the local Docker backend
```

## API keys

Keys live in `.env` at the repo root, which `python-dotenv` loads. Exported shell variables also work.

| Variable | Required | Where the user gets it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | local and `--orgo` (not `--orgo-agent`) | https://platform.claude.com/settings/keys |
| `ORGO_API_KEY` | `--orgo` and `--orgo-agent` | https://www.orgo.ai/settings/credentials |
| `ANTHROPIC_MODEL` | no (default `claude-opus-5-5`) | any model that supports `computer_toolset_20260801` |
| `ORGO_WORKSPACE_ID` | no (defaults to the first workspace) | Orgo dashboard |
| `ORGO_AGENT_MODEL` | no (default `claude-opus-5.5`; or `orgo-agent-opus-5.5`) | Orgo chat completions docs |
| `ORGO_BILLING_MODE` | no (default `plan`); set `hourly` on free Orgo accounts | Orgo billing docs |

Rules for agents:
- Never print, echo, log or commit key values. To check whether a key is set, print only the variable name, for example `grep -q '^ANTHROPIC_API_KEY=sk-ant-' .env && echo set`.
- If a key is missing, ask the user to add it to `.env` themselves. Don't ask them to paste it into chat.
- `.env` is gitignored. Keep it that way.

## Run and verify

```bash
.venv/bin/python cua.py "Open Firefox, go to anthropic.com and tell me the top headline."
.venv/bin/python cua.py "Open a terminal and show me the system info" --orgo
.venv/bin/python cua.py "Open a terminal and show me the system info" --orgo-agent
```

- A successful run ends with a green `✅ Done` panel holding Claude's answer.
- Screenshots go to `runs/<timestamp>/NN-<action>.png`. Open the last one to confirm the result.
- Live view of the local desktop: http://localhost:6080/vnc.html?autoconnect=1&resize=scale
- Test the action handlers with no API key (and no cost):
  ```bash
  .venv/bin/python -c "from cua import Docker, act; d = Docker(); print(act(d, 'left_click', {'coordinate': [567, 775]})); open('/tmp/t.png', 'wb').write(act(d, 'screenshot', {}))"
  ```
  This clicks the terminal icon in the dock.

## Conventions

- Keep `cua.py` small (about 290 lines today), single-file and dependency-light (`anthropic`, `requests`, `rich`, `python-dotenv`, `pillow`).
- Use the official `anthropic` SDK for Claude calls. `requests` is only for Orgo's REST API.
- A backend is any class with `watch_url`, `xdo(*args) -> str` (runs `xdotool`), `screenshot() -> bytes` (PNG) and `close()`. `act()` is shared.
- Keep the message history append-only and pass `response.content` back unchanged. Claude Opus 5.5 thinking blocks are tied to the conversation, so editing or pruning earlier turns invalidates them.
- Screenshots must fit Claude's image limits (2576 px long edge). The 1280×800 desktop is sent unscaled, so coordinates need no mapping. If you change the resolution, scale screenshots and coordinates together.
- Don't use forced `tool_choice` (`any` / `tool`); Claude Opus 5.5 rejects it.
- Clean up: `docker compose down` for local runs. Orgo computers are deleted automatically unless you pass `--keep`.

## Docs

- Claude computer use: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
- Anthropic reference implementation: https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo
- Orgo + Claude: https://docs.orgo.ai/guides/claude-computer-use
- Orgo hosted agent: https://docs.orgo.ai/api-reference/chat/completions
- Orgo API reference: https://docs.orgo.ai/api-reference/introduction (full index: https://docs.orgo.ai/llms.txt)
