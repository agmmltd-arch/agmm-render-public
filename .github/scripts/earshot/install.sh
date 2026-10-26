#!/usr/bin/env bash
# install.sh - earshot (MIT, https://github.com/Leonxlnx/earshot) on an ubuntu runner, CPU only, pinned to one commit.
# Optional Gemini `llm` command is never used. Models (CLAP + AST, ~1.1 GB) land in $EARSHOT_HOME and are cached by the workflow.
set -euo pipefail
EARSHOT_SHA="591fa3e028032e6dce56620a20e932e35667e8d8"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends ffmpeg libsndfile1
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
src="$RUNNER_TEMP/earshot-src"
mkdir -p "$src" && cd "$src"
git init -q . && git remote add origin https://github.com/Leonxlnx/earshot.git
git fetch -q --depth 1 origin "$EARSHOT_SHA" && git checkout -q FETCH_HEAD
test "$(git rev-parse HEAD)" = "$EARSHOT_SHA"
python3 -m pip install --quiet .
export EARSHOT_HOME="${EARSHOT_HOME:-$HOME/.cache/earshot}"
mkdir -p "$EARSHOT_HOME"
python3 -m earshot doctor --fetch || true
python3 -c "import earshot; print('earshot', earshot.__version__)"
