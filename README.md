# Pupil Labs pl-realtime-tui

[![ci](https://github.com/pupil-labs/pl-realtime-tui/actions/workflows/main.yml/badge.svg)](https://github.com/pupil-labs/pl-realtime-tui/actions/workflows/main.yml)
[![documentation](https://img.shields.io/badge/docs-mkdocs-708FCC.svg?style=flat)](https://pupil-labs.github.io/pl-realtime-tui/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre_commit-black?logo=pre-commit&logoColor=FAB041)](https://github.com/pre-commit/pre-commit)
[![pypi version](https://img.shields.io/pypi/v/pl-realtime-tui.svg)](https://pypi.org/project/pl-realtime-tui/)
[![python version](https://img.shields.io/pypi/pyversions/pl-realtime-tui)](https://pypi.org/project/pl-realtime-tui/)

[![pl-realtime-tui banner](https://raw.githubusercontent.com/pupil-labs/pl-realtime-tui/refs/heads/main/docs/assets/banner.png)](https://pupil-labs.com/https://docs.pupil-labs.com/alpha-lab/)

A TUI to monitor, control and send synchronized events to multiple eye-trackers.

`pl-realtime-tui` is a Python-based Text User Interface (TUI) application designed to monitor, control, and send synchronized events to multiple Pupil Labs eye-trackers (Neon/Pupil Invisible). It leverages the `pupil-labs-realtime-api` for low-latency communication with devices and `textual` for a responsive terminal-based dashboard.

See the accompanying [Alpha Lab article](https://docs.pupil-labs.com/alpha-lab/a-guide-to-multiperson-eye-tracking/) for more details and example use cases.

## Installation

```
pip install pupil-labs-realtime-tui # or pip install git+https://github.com/pupil-labs/pl-realtime-tui.git
```

## Run It

if you have [Astral's UV](https://github.com/astral-sh/uv) installed. You can run it directly with:

```bash
uvx pupil-labs-realtime-tui
```

If you want to run more than one time, you may want to install it as a tool.

```bash
uv tool install pupil-labs-realtime-tui
```

From there, you would be able to invoke it with just `pl-realtime-tui` from anywhere in the terminal.

## Prior Work

We would like to also acknowledge the following published prior work using terminal-based interfaces for eye-tracking device management, concretely with our own devices:

- [Neurolive](https://pupil-labs.com/blog/neurolive-project)
- [SocialEyes](https://pupil-labs.com/blog/socialeyes)

## Key Features

- **Discovery:** Implements both standard mDNS discovery and a "Deep Scan" (ARP-based or brute-force subnet scan).
- **Device Dashboard:** Displays connected devices in a `DataTable` with real-time status, battery, storage, and last event info.
- **Recording Control:** Start/stop recordings on selected devices or all devices simultaneously.
- **Event Triggers:** Keyboard keys `0`-`9` trigger events sent to either the selected device or all connected devices if none is selected.
- **Selection Logic:** Clicking a device in the `DataTable` selects it, allowing targeted start/stop/event commands.
- **Time Sync:** Automatically estimates clock offsets periodically to maintain synchronization.

## Tech Stack

- **Language:** Python (>=3.10, <4.0)
- **TUI Framework:** [Textual](https://github.com/Textualize/textual)
- **CLI Framework:** [Typer](https://github.com/tiangolo/typer)
- **API:** [pupil-labs-realtime-api](https://github.com/pupil-labs/realtime-python-api)
- **Package Management:** [uv](https://github.com/astral-sh/uv)
- **Networking:** `aiohttp` for HTTP API calls, `scapy` for deep network scans (ARP).

## Development Conventions

- **Code Quality:** Strictly follows PEP 8 via `ruff`. Ensure all changes pass `make check` before committing.
- **Typing:** Uses static type hints throughout. `mypy` is used for verification.
- **Asynchronous Code:** Heavily relies on `asyncio` for non-blocking I/O with multiple devices. Textual workers (`@work`) are used for long-running tasks like network discovery.
- **Time Synchronization:** Uses `TimeOffsetEstimator` from the realtime API to calculate clock offsets between the host and eye-trackers, ensuring events are accurately timestamped in the device's clock domain.
- **UI Styling:** Uses Textual CSS (`.tcss`). Modifications to the UI look should be done in `src/pupil_labs/realtime_tui/css/main.tcss`.
- **Pre-commit:** Pre-commit hooks are configured to run linting and formatting on every commit.

> [!IMPORTANT]
> Old terminals (e.g. macOS Terminal.app) do not support key-hold events, which can lead to performance issues when holding down event trigger keys. We attempt to bypass it by blocking new triggers during 0.3s, but key releases may not be detected. We recommend using modern terminals like WezTerm, Ghostty, Kitty, or Alacritty for the best experience. On those terminals, we will use Kitty protocol to detect key releases and support true key-hold events.
