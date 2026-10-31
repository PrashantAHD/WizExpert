"""Local, click-driven workflow console (generic; no client data, no private paths).

The console is a localhost-only web page that drives the enforced category
workflows through *private adapters* supplied from a private root. It is an MCP
client (OAuth 2.1 + PKCE) for read-only collection, never sends email and never
changes Wiz, ticketing or cloud systems.
"""
