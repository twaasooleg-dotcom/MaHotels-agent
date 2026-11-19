# Working on MaHotels-agent

Read Memory.md before changing this project; update it when requirements or behavior change.

This folder, D:\MaHotels-agent, is the sole active project. Make project edits here. Keep ArabiaTrend code, state, credentials and tasks separate. Do not create duplicate staging copies.

Preserve editorial/vision gates, durable budgets/cooldowns, IDs and ownership checks. Never delete state/ or reset counters to retry. ZIP backups in state/backups/ are historical, not active implementations.

Run .venv\Scripts\python.exe -B -m unittest discover -s tests -v and .venv\Scripts\python.exe -m pip check after relevant code changes. TEST.cmd runs both offline. Tests use temporary state and mocked providers; production run/resume-batch can schedule WordPress content. Do not launch production just to inspect files.
