# VengaiCode Documentation

## Tailwind and Generated Apps

The code generation output must include:

- `frontend/src/index.css` with:
  ```css
  @tailwind base;
  @tailwind components;
  @tailwind utilities;
  ```
- `frontend/tailwind.config.js`
- `frontend/postcss.config.js`
- `frontend/src/main.jsx` importing `./index.css`
- all generated React components using Tailwind utility classes via `className`
- `frontend/package.json` containing `tailwindcss`, `postcss`, and `autoprefixer` as dev dependencies.

This ensures generated apps are styled consistently and can be built with Vite.

## Windows installer packaging

The Windows build workflow now:

1. fetches generated frontend files from the backend packaging endpoint,
2. copies the `templates/tauri-windows` template into `build/`,
3. injects the generated frontend files into that template,
4. uses the injected `build/package.json` when available,
5. updates `build/src-tauri/tauri.conf.json` with project-specific `productName`, `version`, and bundle `identifier`, and
6. runs `cargo tauri build` to produce per-project installers.

### Required backend support

The CI workflow expects a backend packaging endpoint that returns generated project files as JSON and a GitHub secret named `VENGAICODE_BUILD_SECRET` for authentication.

## Deploying backend changes

1. Push backend changes to the repo.
2. Deploy the updated backend to Render.
3. Ensure the Render service can return generated project files for packaging.
4. Add `VENGAICODE_BUILD_SECRET` to GitHub Actions secrets.

## Local validation

If you want a lightweight local check without a full Linux container:

```powershell
python scripts/test_codegen_prompt.py
```

This verifies the prompt text includes Tailwind requirements. For full AI runs you need a working backend/AI environment.

## Notes

- The app is designed to keep heavy build work in cloud CI and Render.
- The current repo changes are focused on Tailwind staging and making Windows installer builds unique per project.
