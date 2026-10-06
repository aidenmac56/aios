---
description: Structured decision analysis with options, evidence and a recommendation
argument-hint: [request]
allowed-tools: Bash(aios:*), Bash(python3 -m aios.cli:*)
---
Run this command from the repository root and show the founder the result:

```
aios decision "$ARGUMENTS"
```

Report the outcome briefly: the conclusion or numbers first, then anything waiting on the founder (approval ids, contradictions, failures). If it prints an approval id, tell him the exact `aios approve <id>` / `aios reject <id>` command. Do not approve anything yourself.
