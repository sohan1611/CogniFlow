---
title: CogniFlow
emoji: 🎓
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 6.26.0
app_file: app.py
python_version: "3.12"
pinned: false
license: mit
short_description: An agentic tutor that changes its own objective when it works out why you are failing
---

# CogniFlow

A student fails recursion twice. Most AI tutors generate an easier recursion problem.
CogniFlow walks a prerequisite graph, works out that the real gap is `functions`, and
**reassigns its own teaching objective** — then comes back.

**Two modes**

- **Watch the demo** — the full prerequisite redirect, step by step, with the live event
  stream. Nothing here is scripted except the student's submissions.
- **Be the student** — a real session. The graph checkpoints to disk and *halts* while
  you think, then resumes from that checkpoint when you submit.

## A note on running your code

This Space executes Python you submit, so submissions pass a **static allowlist before
any process is created**: standard computation modules are available, while filesystem,
network, process and introspection access are refused. A refusal is reported as a system
event and **never affects a student's mastery** — writing a correct function that also
imports `os` demonstrates no misconception.

## Source and method

Full source, architecture, and the measured ablation:
**https://github.com/sohan1611/CogniFlow**

Built for the Agentic AI Hackathon, Tech Zephyr 4.0, IIT Bhubaneswar.
