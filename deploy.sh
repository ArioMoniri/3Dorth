#!/usr/bin/env bash
# One-line server deploy: build the images and bring up API + both frontends.
# Usage on a fresh server (Docker + compose plugin installed):
#   git clone https://github.com/ArioMoniri/3Dorth.git && cd 3Dorth && ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
docker compose --profile all up -d --build
echo
echo "3Dorth is up:"
echo "  React UI : http://<server>:8088"
echo "  trame UI : http://<server>:8081"
echo "  API docs : http://<server>:8000/docs"
echo "Upload a CT .zip in the UI to begin (no patient data is baked into the image)."
