"""Local frontend for the reporting workflow (generic; no client data, no private paths).

The console is a localhost-only web page. It does not run any workflow itself: it opens a new
VS Code agent-mode chat (custom agent, one validated prompt) through a small helper extension
and then mirrors that chat's session log (progress, questions, final summary, files).
"""
