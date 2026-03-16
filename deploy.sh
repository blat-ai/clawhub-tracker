#!/usr/bin/env bash
set -euo pipefail

# Deploy static site to GitHub Pages (gh-pages branch)
# Usage: ./deploy.sh

echo "Generating site..."
.venv/bin/python -m app.site

echo "Deploying to gh-pages..."

# Create a temporary directory for deployment
DEPLOY_DIR=$(mktemp -d)
cp -r build/* "$DEPLOY_DIR/"

# Add .nojekyll to skip Jekyll processing
touch "$DEPLOY_DIR/.nojekyll"

# Get current commit info for the deploy message
COMMIT_SHA=$(git rev-parse --short HEAD)
COMMIT_MSG="Deploy site from $COMMIT_SHA ($(date -u '+%Y-%m-%d %H:%M UTC'))"

cd "$DEPLOY_DIR"
git init -b gh-pages
git add -A
git commit -m "$COMMIT_MSG"

REMOTE_URL=$(cd - > /dev/null && git remote get-url origin)
git push --force "$REMOTE_URL" gh-pages

# Cleanup
rm -rf "$DEPLOY_DIR"

echo "Deployed to gh-pages branch."
echo "Enable GitHub Pages at: https://github.com/$(cd - > /dev/null && gh repo view --json nameWithOwner -q .nameWithOwner)/settings/pages"
echo "Select source: 'Deploy from a branch' -> 'gh-pages' -> '/ (root)'"
