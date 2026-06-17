#!/usr/bin/env bash
# Rebuild the compiled Tailwind stylesheet (static/css/output.css).
#
# IMPORTANT: the app ships a *precompiled* CSS file. Tailwind only includes the
# utility classes it finds in the templates at build time, so whenever you add a
# NEW class to a template (e.g. a new arbitrary value like h-[calc(100vh-8rem)]
# or a variant like lg:col-span-9) you must run this, or that class will have no
# effect in the browser.
#
# Uses npx so it works without `npm install`. Requires Node.js + internet the
# first time (to fetch tailwindcss). Commit the regenerated output.css.
set -euo pipefail
cd "$(dirname "$0")"

npx --yes tailwindcss@3.4.17 \
    -i static/css/input.css \
    -o static/css/output.css \
    --config tailwind.config.js \
    --minify

echo "Rebuilt static/css/output.css"
