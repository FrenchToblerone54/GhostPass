#!/bin/bash
set -e

echo "Building GhostPass binary..."

cd "$(dirname "$0")/.."

python3.13 -m PyInstaller --onefile --name ghostpass \
  --hidden-import bot.handlers.admin \
  --hidden-import bot.handlers.consumer \
  --hidden-import bot.handlers.payment_card \
  --hidden-import bot.handlers.payment_crypto \
  --hidden-import bot.handlers.payment_request \
  main.py

echo "Generating checksums..."
cd dist
sha256sum ghostpass > ghostpass.sha256
cd ..

echo "Build complete!"
echo "Binary available in dist/"
ls -lh dist/
