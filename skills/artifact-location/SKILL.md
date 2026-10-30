---
name: artifact-location
description: "Where the local source of an artifact (.html/.md for the Artifact tool) goes. Load before creating any artifact: write to artifacts/ in the project root, never scratchpad/temp. Visual design is the built-in artifact-design skill. Triggers: artifact, HTML page, dashboard, report, page, publishing a page."
---

Only the local file's location changes; publication stays.

1. Path: `<root>/artifacts/<name>.html`; root = git root of the working directory, else the primary working directory.
2. `mkdir -p <root>/artifacts` without prior checks.
3. Keep `artifacts/` in `.gitignore`, unless explicitly asked to commit artifacts.
4. Stable descriptive name per artifact (`brief-golive-status.html`): same path → same URL on repeat `Artifact` call; new path = new artifact, only for a separate page.
5. `Write` the file, then `Artifact` with `file_path` = that path.

Load `artifact-design` before layout. Read-only project, not a project, or root not writable → fall back to scratchpad.
