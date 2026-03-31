#!/bin/bash
# XP CLI Wrapper
VENV_PATH="/Users/lianzimeng/workspace/xp/.venv"
source "$VENV_PATH/bin/activate"
python -m src.cli "$@"
