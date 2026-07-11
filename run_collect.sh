#!/bin/bash
cd /Users/kendrichsu/vol-surface
/Users/kendrichsu/vol-surface/venv/bin/python collect.py >> collect.log 2>&1
git add data/
git commit -m "Auto: daily snapshot $(date +%Y-%m-%d)" >> collect.log 2>&1
git push >> collect.log 2>&1