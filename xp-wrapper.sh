#!/bin/bash
# XP CLI Wrapper
VENV_PATH="/Users/lianzimeng/working/happy/xp/.venv"
source "$VENV_PATH/bin/activate"
python -m src.cli "$@"
