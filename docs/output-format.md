# Output format

The text report, the JSON report schema, finding labels and exit codes.

The report formats are documented together with the reports themselves.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No failing findings. |
| `1` | Failing findings: `unexpected` or `unclear` with the default `--fail-on unclear`; only `unexpected` with `--fail-on unexpected`. |
| `2` | Tool or configuration error: not a git repository, git missing, invalid flag or config value, missing API key. |
| `130` | Interrupted with Ctrl-C; temporary worktrees, copies and processes are removed first. |
