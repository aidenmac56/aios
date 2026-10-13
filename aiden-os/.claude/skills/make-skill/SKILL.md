---
name: make-skill
description: Turn what we just did into a reusable skill (reverse-engineer it), or improve an existing skill from his feedback. Use when he says "make this a skill", "remember how to do this", or gives feedback on a skill's output.
---

New skill:
1. Look back at this conversation: the goal, inputs, tools used, questions asked, what he corrected, and the
   final output he liked.
2. Write `.claude/skills/<short-name>/SKILL.md` with a one-line description of WHEN to use it, then numbered
   steps that reproduce that output. Point to context files instead of copying their content.
3. Keep it under 30 lines. Tell him the slash command.

Improving a skill: add the specific fix he asked for as a step or rule, so the same miss can't repeat.
