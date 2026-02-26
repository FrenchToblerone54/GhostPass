#!/bin/bash
set -e

echo "Building GhostPass binary..."

cd "$(dirname "$0")/.."

python3.13 -m PyInstaller --onefile --name ghostpass main.py

echo "Generating checksums..."
cd dist
sha256sum ghostpass > ghostpass.sha256
cd ..

echo "Build complete!"
echo "Binary available in dist/"
ls -lh dist/
