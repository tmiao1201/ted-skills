#!/usr/bin/env bash
# sync.sh — 一键重新生成看板。后续若推 GitHub Pages，把 PUSH 段改成 1 即可。
set -euo pipefail

cd "$(dirname "$0")"

echo "▶ 重新扫描 ~/.claude/skills/ 并生成看板..."
python3 build.py

echo ""
echo "▶ 本地预览："
echo "   cd ~/skills_dashboard && python3 -m http.server 8765"
echo "   open http://localhost:8765/index.html"
echo ""

# ============================================================
# 推 GitHub Pages：远端 = git@github.com:tmiao1201/ted-skills.git
# 首次上线后 PUSH=1，之后每次 ./sync.sh 自动 commit+push
# ============================================================
PUSH=1
if [ "$PUSH" = "1" ]; then
  echo "▶ 推送到远端..."
  git add -A
  git commit -m "sync: $(date '+%Y-%m-%d %H:%M') · $(ls -d ~/.claude/skills/*/ | wc -l | tr -d ' ') skills" || echo "  (无变更)"
  git push origin main
  echo "✓ 已推送，几分钟后 https://tmiao1201.github.io/ted-skills/ 会更新"
fi
