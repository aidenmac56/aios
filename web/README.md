# Command center (web dashboard)

The founder's dashboard for AI Company OS. Vite + React 18 + TypeScript, no UI kit, no router
library, no chart library. It reads and writes only through the JSON API in `aios/api/app.py`.

## Develop

Start the API on port 8787, then the Vite dev server:

```sh
aios serve                 # API on http://127.0.0.1:8787
cd web
npm install
npm run dev                # http://localhost:5173, proxies /api to 127.0.0.1:8787
```

## Build

```sh
cd web
npm run build              # tsc --noEmit, then vite build
```

The build writes `index.html` and `assets/` to `../aios/web_dist`, which `aios serve` serves at
`/`. `npm run typecheck` runs the TypeScript check on its own.

## Auth

If the server sets `AIOS_API_TOKEN`, the dashboard asks for the token once and sends it as
`Authorization: Bearer <token>`. It is kept in memory and, if "Remember on this device" is checked,
in `localStorage` under `aios.api_token`.

## Layout

```
src/
  api.ts        typed fetch helper; throws ApiError carrying the API's {code, message}
  types.ts      response shapes, field names as the API returns them
  router.ts     hash router (#/executive, #/runs/<id>, #/agents/<id>, #/projects/<id>, #/research/<id>)
  hooks.ts      useApi (GET with optional polling), useAction (busy + error)
  format.ts     money (cents and *_usd dollars), dates, durations
  events.ts     plain-language lines for activity events
  components/   Badge, Card, Table, BarChart, EmptyState, CommandBar, BriefView, ...
  pages/        one file per sidebar page, plus run detail
```

Money from the API in cents (`*_cents`, `cents`) is divided by 100; `*_usd` values are already
dollars. Times without a zone suffix are treated as UTC, as the server stores them.
