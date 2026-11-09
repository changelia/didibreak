# spec

The shared contract for all didibreak packages (Python now, JS/TS later).
Packages copy these files at build time and never read across folders at
runtime.

| Path | Contents |
| --- | --- |
| `report.schema.json` | JSON Schema of the `--format json` report (`schema_version: 1`). |
| `prompts/` | Versioned LLM prompt templates. |
| `cases/` | Shared cross-language test cases (data only); added when the first cases exist. |

A change here affects every package: CI runs the checks of all packages when
`spec/` changes.
