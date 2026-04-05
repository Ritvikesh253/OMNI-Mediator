# Omni-Mediator

Omni-Mediator is a secure, Zero-Touch agentic middleware platform that bridges a lightweight Telegram interface to high-compute local hardware (macOS or Windows) for private, local-first AI execution using Ollama.

O.M.N.I. = Operating My Network Invisibly

Built for academic demonstration environments and hackathon-grade reliability, Omni-Mediator is designed to deliver practical local AI control with strong human oversight, resilient async execution, and no cloud model dependency for core reasoning.

## Concept

Omni-Mediator solves a common hardware-access gap:

- The user interacts from a lightweight mobile device (Telegram).
- The middleware runs on a local machine with stronger compute.
- Requests are routed to either:
  - local system operations, or
  - a local Ollama model for semantic processing.

Result: end-to-end local execution, low-latency control, and privacy-preserving operation.

## Key Feature 1: Zero-Touch Deployment

Omni-Mediator is designed for one-command startup:

- Automatically checks required Python packages.
- Installs missing dependencies.
- Restarts itself transparently after installation.
- Launches an interactive first-time setup wizard for token, local model readiness, and security mode.

This provides a clean exhibition workflow for evaluators: run once, configure once, and demonstrate immediately.

## Key Feature 2: Sentinel Shell (Human-in-the-Loop Security)

Sentinel Shell enforces Human-in-the-Loop (HITL) authorization for local command execution:

- The AI can suggest or route eligible OS/terminal actions.
- Execution does not happen immediately.
- Commands are held in a pending state.
- The user must explicitly approve or deny via Telegram inline buttons.
- Critical dangerous patterns (such as sudo, su, and rm -rf) are hard-blocked.

This architecture keeps the user in command at every sensitive boundary.

## Quick Start

1. Open a terminal in the project directory.
2. Run:

   python3 omni_mediator.py

3. Complete the terminal setup wizard:
   - Enter Telegram bot token.
   - Validate local Ollama availability.
   - Configure Sentinel Shell mode.
   - Finish owner authorization for secure control.

After setup, connect through Telegram and begin interacting with your local AI bridge.

## Exhibition Value

- Local-first AI execution for privacy and reliability.
- Clear security posture with HITL approval gates.
- Practical systems integration across messaging, LLM runtime, and OS automation.
- Strong demo ergonomics for academic and judging environments.
