# Frontend setup

Opinionssimulator SPA: Vite + React + TypeScript + Tailwind + shadcn + React Router.

## Init (already done)

The app was scaffolded from the mockup. To recreate from empty:

```bash
cd frontend
pnpm create vite . --template react-ts
pnpm install
pnpm add react-router-dom @supabase/supabase-js
pnpm add -D tailwindcss @tailwindcss/vite
pnpm dlx shadcn@latest init
```

## Run

```bash
cd frontend
pnpm install
cp .env.example .env   # set VITE_API_BASE_URL=http://localhost:8000
pnpm dev
```

Open http://localhost:5173/runs — admin pages call the backend. Simulator stays mock at `/simulator`.

Start the backend first (see [backend-setup.md](backend-setup.md)).

## Check

```bash
pnpm exec tsc -p tsconfig.app.json --noEmit
pnpm lint
```

## Themes

- Simulator: `src/styles/simulator.css` (`.theme-simulator`)
- Admin stubs: Devbrains tokens in `src/index.css`
