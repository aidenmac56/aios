---
description: What the AI company costs: by agent, model, workflow, day
argument-hint: 
allowed-tools: Bash(aios:*), Bash(python3 -m aios.cli:*)
---
Run this command from the repository root and show the founder the result:

```
aios cost
```

Report the outcome briefly: the conclusion or numbers first, then anything waiting on the founder (approval ids, contradictions, failures). If it prints an approval id, tell him the exact `aios approve <id>` / `aios reject <id>` command. Do not approve anything yourself.
