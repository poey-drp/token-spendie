#!/bin/bash
# Run Token Spendie menu bar app
cd "$(dirname "$0")"
pip3 install -q -r requirements.txt
python3 token_spendie.py
