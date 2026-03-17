#!/usr/bin/env bash
set -euo pipefail

# Deploy build/ to gh-pages branch
# Requires GH_TOKEN env var or git credentials configured

REPO_URL="${REPO_URL:-https://github.com/blat-ai/clawhubtrends.git}"
BUILD_DIR="${BUILD_DIR:-/app/build}"

if [ ! -d "$BUILD_DIR" ] || [ -z "$(ls -A "$BUILD_DIR")" ]; then
    echo "[DEPLOY] No build output found at $BUILD_DIR, skipping deploy"
    exit 0
fi

echo "[DEPLOY] Deploying to gh-pages..."

DEPLOY_DIR=$(mktemp -d)
cp -r "$BUILD_DIR"/* "$DEPLOY_DIR/"
touch "$DEPLOY_DIR/.nojekyll"

COMMIT_MSG="Deploy site $(date -u '+%Y-%m-%d %H:%M UTC')"

# If GH_TOKEN is set, use it for auth
if [ -n "${GH_TOKEN:-}" ]; then
    PUSH_URL="https://x-access-token:${GH_TOKEN}@github.com/blat-ai/clawhubtrends.git"
else
    PUSH_URL="$REPO_URL"
fi

cd "$DEPLOY_DIR"
git init -b gh-pages
git config user.email "deploy@clawhubtrends"
git config user.name "ClawHub Deploy"
git add -A
git commit -m "$COMMIT_MSG"
git push --force "$PUSH_URL" gh-pages

rm -rf "$DEPLOY_DIR"
echo "[DEPLOY] Done"
