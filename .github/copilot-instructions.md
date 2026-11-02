# Project Guidelines

## Local workflow console

- Use the workspace tasks in `.vscode/tasks.json` for the local console.
- `Ctrl+Alt+R` runs `WizExpert: Workflow console (auto-reload)`.
- `Ctrl+Alt+S` runs `WizExpert: Stop workflow console`.
- If the shortcuts do not work after task changes, run **Developer: Reload Window** once, then retry.
- If the console helper is updated or VS Code asks to permit chat creation, reload the VS Code
  window once and choose **Allow Always** for creating a chat in this workspace. This is a
  one-time VS Code permission; do not bypass or alter it programmatically.
- The auto-reload task watches console Python, JavaScript, HTML, CSS, JSON, and SVG files. Refresh the browser after a backend restart.
- Do not start a real Wiz workflow during UI or console validation.
- Run only one workflow-console backend at a time. Do not run `wizexpert console`
  and `wizexpert.console.dev` together, or launch them from both the project
  virtual environment and global Python; they can share `bridge.json` and make
  the helper appear disconnected. Stop stale console/watch processes before
  retrying.
- The auto-reload task uses a new terminal because VS Code can retain a disposed
  terminal ID. After changing `.vscode/tasks.json`, reload the VS Code window
  before using `Ctrl+Alt+R`.
- After changing console static assets or backend code, restart the console
  process itself; browser refresh alone cannot load files into an already
  running backend. Before a live refresh, confirm the helper is connected in
  the same workspace and that the console is using the current project
  environment.
- In this workspace, the console workspace is the outer
  `C:\Users\PrashantKumar\WizExpert` folder, not the nested public
  `C:\Users\PrashantKumar\WizExpert\WizExpert` checkout. The VS Code window
  must open the outer folder when the console is launched with the outer path;
  the helper intentionally rejects jobs from a different workspace folder.

See `docs/CONSOLE.md` for the complete console workflow.
