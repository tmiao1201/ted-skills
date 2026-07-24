#!/usr/bin/env bash
# auto_sync.sh — Claude Code Stop hook 调用
#
# 行为：只在 ~/.claude/skills/ 下 SKILL.md 最近 10 分钟内有变动时才跑 sync.sh。
# 这样每次 Claude 响应结束都触发，但实际工作只在 skill 真的变化时发生。
#
# 日志：/tmp/teds-sync.log（最近一次执行的输出）

set -euo pipefail

LOG=/tmp/teds-sync.log

# 检查最近 10 分钟内是否有 SKILL.md 变动
# 注意用 find -L 跟随符号链接，否则软链进来的 skill（如 Ted-imgstyle、kendiag）检测不到
RECENT=$(find -L "$HOME/.claude/skills" -name "SKILL.md" -mmin -10 2>/dev/null | head -1)

if [ -z "$RECENT" ]; then
  # 无变化，安静跳过
  exit 0
fi

# 有变化，跑同步
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 检测到 SKILL.md 变化 ==="
  echo "触发文件: $RECENT"
  cd "$HOME/skills_dashboard" && ./sync.sh
  echo "=== 完成 ==="
} > "$LOG" 2>&1 &
# & 后台跑，不阻塞 Claude 响应

exit 0
