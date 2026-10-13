---
name: youtube-script
description: Turn a topic or this week's AI news into a YouTube script Aiden (or his clone) can say, plus title, thumbnail idea and description. Use for any video request.
---

1. Read `context/voice.md`, `context/audience.md`, `context/goals.md`, `context/links.md`.
2. Topic: use what he gave. Otherwise pull this week's trends (aios MCP `start_workflow` command `trends`, or
   the latest trends run via `list_runs`) and pick the one most useful to a San Diego service-business owner.
3. Write ~350 spoken words (about 2.5 minutes):
   - Hook in 10 seconds: the problem or the number.
   - The one idea, with a concrete example, price, or demo.
   - One thing to try this week.
   - CTA: free 20-minute AI Quick Wins call (real booking link from links.md).
   Stage directions in [brackets]; everything else is spoken.
4. Add: 3 title options (under 60 characters, no clickbait he'd be embarrassed by), 1 thumbnail concept
   (face + 3-5 words), and the description with the booking link.
5. Save to `content/youtube/YYYY-MM-DD-slug.md`.
6. Offer the next step: render it with his clone (`aios video make --file <that file>`), or film it himself.
