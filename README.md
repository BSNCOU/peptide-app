# Peptide Protocol Builder (React + Vite + Tailwind)

## Quickstart
1. Install Node.js LTS (v18+ recommended).
2. Open a terminal and run:
   ```bash
   cd peptide-protocol-builder
   npm install
   npm run dev
   ```
3. Open the printed local URL in your browser.

## Build for production
```bash
npm run build
npm run preview
```

## Deploy (Vercel)
- Push this folder to a new GitHub repo.
- Import the repo in https://vercel.com/new
- Framework Preset: **Vite**. Build command: `npm run build`. Output: `dist/`.

## Deploy (Netlify)
- Drag the `dist/` folder after `npm run build` into Netlify Drop,
  or connect your Git repo. Build command: `npm run build`. Publish dir: `dist/`.

## Tailwind
Configured in `tailwind.config.js` and `src/index.css` with the @tailwind directives.

## PWA (optional later)
Add `vite-plugin-pwa` for install-to-home-screen behavior if you want a phone-app feel.
