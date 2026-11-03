# Backend diagrams

[backend.drawio](backend.drawio) contains the editable source for every diagram. Each page uses native Draw.io shapes
and connectors. PNG previews are embedded in the project documentation.

| Page | Diagram                | Preview                                                  |
|------|------------------------|----------------------------------------------------------|
| 1    | System overview        | [system-overview.png](system-overview.png)               |
| 2    | Hexagonal architecture | [hexagonal-architecture.png](hexagonal-architecture.png) |
| 3    | Code dependencies      | [code-dependencies.png](code-dependencies.png)           |
| 4    | Diagnostic overview    | [diagnostic-overview.png](diagnostic-overview.png)       |
| 5    | Diagnostic details     | [diagnostic-details.png](diagnostic-details.png)         |
| 6    | Action overview        | [action-overview.png](action-overview.png)               |
| 7    | Action details         | [action-details.png](action-details.png)                 |
| 8    | Action lifecycle       | [action-lifecycle.png](action-lifecycle.png)             |

Page IDs match preview filenames. After editing a page, re-export its PNG from the repository root. The installed
draw.io CLI uses **1-based** `--page-index` values. Check `--help` when using another version.

```powershell
& "C:\Program Files\draw.io\draw.io.exe" --export --format png `
  --page-index 2 --scale 1.25 --border 20 --theme light `
  --output docs/diagrams/hexagonal-architecture.png docs/diagrams/backend.drawio
```

Use the light export theme to keep labels readable on both light and dark documentation pages.
Optimize large PNG exports to stay below the 500 KiB pre-commit limit.
