#!/usr/bin/env python3
"""
Skills Dashboard Builder
扫描 ~/.claude/skills/ 下所有 SKILL.md，生成可视化看板 + 下载包。
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"
OUT_DIR = Path.home() / "skills_dashboard"
DL_DIR = OUT_DIR / "downloads"

# ---------- 分类规则 ----------
CATEGORIES = {
    "finance": {
        "label": "金融建模",
        "color": "#d4a574",
        "skills": {
            "3-statement-model", "audit-xls", "bond-futures-basis", "bond-relative-value",
            "clean-data-xls", "comps-analysis", "competitive-analysis", "datapack-builder",
            "dcf-model", "deck-refresh", "earnings-analysis", "earnings-preview-single",
            "equity-research", "financial-statements", "fixed-income-portfolio",
            "fsi-strip-profile", "funding-digest", "fx-carry-trade", "ib-check-deck",
            "initiating-coverage", "lbo-model", "macro-rates-monitor",
            "option-vol-analysis", "pitch-deck", "ppt-template-creator",
            "startup-financial-modeling", "swap-curve-strategy", "tear-sheet",
        },
    },
    "chinese": {
        "label": "中文协作",
        "color": "#c97064",
        "skills": {
            "chinese-code-review", "chinese-commit-conventions",
            "chinese-documentation", "chinese-git-workflow",
        },
    },
    "engineering": {
        "label": "工程方法",
        "color": "#5b9aa0",
        "skills": {
            "brainstorming", "build", "design-consultation", "design-review",
            "dispatching-parallel-agents", "executing-plans",
            "finishing-a-development-branch", "investigate", "office-hours",
            "plan", "prepare", "receiving-code-review", "requesting-code-review",
            "research-hours", "retro", "review", "ship", "subagent-driven-development",
            "systematic-debugging", "test", "test-driven-development",
            "using-git-worktrees", "using-superpowers",
            "verification-before-completion", "writing-plans", "writing-skills",
        },
    },
    "meta": {
        "label": "Skill 元工具",
        "color": "#b08bbb",
        "skills": {
            "find-skills", "skill-creator", "skill-harden", "skill-learn",
            "mcp-builder", "myframework",
        },
    },
    "orchestration": {
        "label": "研究编排",
        "color": "#7c9070",
        "skills": {
            "kautoresearch", "kenmoe", "research", "workflow-runner", "github-cron",
        },
    },
}


def classify(name: str) -> tuple[str, str, str]:
    for cid, c in CATEGORIES.items():
        if name in c["skills"]:
            return cid, c["label"], c["color"]
    return "other", "其他", "#888888"


# ---------- frontmatter 解析 ----------
FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_skill(skill_dir: Path) -> dict | None:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8", errors="replace")
    m = FM_RE.match(text)
    if m:
        fm_raw, body = m.group(1), m.group(2)
    else:
        # 兜底：无 frontmatter 的 SKILL.md，从首段提取描述
        fm_raw, body = "", text

    name = ""
    desc = ""
    in_desc_block = False
    desc_lines: list[str] = []
    for line in fm_raw.split("\n"):
        if in_desc_block:
            if line and not line.startswith(" ") and ":" in line:
                in_desc_block = False
            else:
                stripped = line.strip()
                if stripped:
                    desc_lines.append(stripped)
                continue
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            v = line.split(":", 1)[1].strip()
            if v in ("|", ">", "|-", ">-"):
                in_desc_block = True
            else:
                desc = v.strip('"').strip("'")
    if desc_lines:
        desc = " ".join(desc_lines)

    name = name or skill_dir.name

    # 无 frontmatter 时，从首段非标题文本提取描述
    if not desc:
        for line in body.split("\n"):
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith(">") and not s.startswith("<"):
                desc = re.sub(r"\*\*|`|\[|\]\(.*?\)", "", s)[:300]
                break

    # 提取正文里第一段非空文本作为概述（避开 frontmatter 后的 H1）
    body_lines = body.split("\n")
    overview = ""
    skip_h1 = True
    paragraph: list[str] = []
    for line in body_lines:
        s = line.strip()
        if skip_h1 and s.startswith("#"):
            continue
        skip_h1 = False
        if s.startswith("#") or s.startswith("---"):
            if paragraph:
                break
            continue
        if s.startswith("<") and s.endswith(">"):
            continue
        if s:
            paragraph.append(s)
        elif paragraph:
            break
    overview = " ".join(paragraph)[:400]

    # 提取触发关键词（从 description 里 Use when / 触发词 提取）
    triggers = extract_triggers(desc)

    cid, clabel, ccolor = classify(name)
    return {
        "name": name,
        "desc": desc,
        "overview": overview,
        "triggers": triggers,
        "category_id": cid,
        "category": clabel,
        "color": ccolor,
        "path": str(skill_dir),
        "size_kb": dir_size_kb(skill_dir),
        "files": count_files(skill_dir),
    }


def extract_triggers(desc: str) -> list[str]:
    """从 description 中抽取触发关键词。"""
    triggers: list[str] = []
    for marker in ["Use when:", "Triggers on", "触发词", "触发：", "Trigger when:", "Examples:"]:
        if marker in desc:
            tail = desc.split(marker, 1)[1]
            # 截取到下一个句号/Skip/Not ideal 之前
            for stop in [". Skip", ". Not", ". 不适用", "。不适用", " SKIP:"]:
                if stop in tail:
                    tail = tail.split(stop)[0]
                    break
            tail = tail[:300]
            for token in re.split(r"[,，;；、]|\"|“|”", tail):
                t = token.strip().strip("'\"`.()（）").strip()
                if 2 < len(t) < 35 and not t.lower().startswith("use") and ":" not in t:
                    triggers.append(t)
                if len(triggers) >= 8:
                    break
            break
    return triggers[:8]


def dir_size_kb(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / 1024)


def count_files(p: Path) -> int:
    return sum(1 for f in p.rglob("*") if f.is_file())


# ---------- SVG 图标 ----------
def svg_icon(category_id: str, color: str) -> str:
    """根据分类生成不同 SVG 图标。返回 inline SVG 字符串。"""
    icons = {
        "finance": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <rect x="6" y="10" width="52" height="44" rx="3" fill="none" stroke="{color}" stroke-width="2"/>
            <line x1="6" y1="20" x2="58" y2="20" stroke="{color}" stroke-width="2"/>
            <line x1="20" y1="20" x2="20" y2="54" stroke="{color}" stroke-width="1" opacity="0.4"/>
            <line x1="34" y1="20" x2="34" y2="54" stroke="{color}" stroke-width="1" opacity="0.4"/>
            <line x1="48" y1="20" x2="48" y2="54" stroke="{color}" stroke-width="1" opacity="0.4"/>
            <line x1="6" y1="32" x2="58" y2="32" stroke="{color}" stroke-width="1" opacity="0.4"/>
            <line x1="6" y1="42" x2="58" y2="42" stroke="{color}" stroke-width="1" opacity="0.4"/>
            <polyline points="10,50 22,38 36,44 52,26" fill="none" stroke="{color}" stroke-width="2.2"/>
            <circle cx="52" cy="26" r="2.2" fill="{color}"/>
        </svg>''',
        "chinese": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <rect x="8" y="8" width="48" height="48" rx="4" fill="none" stroke="{color}" stroke-width="2"/>
            <text x="32" y="42" text-anchor="middle" font-family="serif" font-size="28" font-weight="bold" fill="{color}">中</text>
            <line x1="14" y1="14" x2="22" y2="14" stroke="{color}" stroke-width="1.5"/>
            <line x1="14" y1="14" x2="14" y2="22" stroke="{color}" stroke-width="1.5"/>
            <line x1="42" y1="14" x2="50" y2="14" stroke="{color}" stroke-width="1.5"/>
            <line x1="50" y1="14" x2="50" y2="22" stroke="{color}" stroke-width="1.5"/>
            <line x1="14" y1="42" x2="14" y2="50" stroke="{color}" stroke-width="1.5"/>
            <line x1="14" y1="50" x2="22" y2="50" stroke="{color}" stroke-width="1.5"/>
            <line x1="42" y1="50" x2="50" y2="50" stroke="{color}" stroke-width="1.5"/>
            <line x1="50" y1="42" x2="50" y2="50" stroke="{color}" stroke-width="1.5"/>
        </svg>''',
        "engineering": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <circle cx="32" cy="32" r="14" fill="none" stroke="{color}" stroke-width="2"/>
            <circle cx="32" cy="32" r="4" fill="{color}"/>
            <line x1="32" y1="6" x2="32" y2="14" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="32" y1="50" x2="32" y2="58" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="6" y1="32" x2="14" y2="32" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="50" y1="32" x2="58" y2="32" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="14" y1="14" x2="20" y2="20" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="44" y1="44" x2="50" y2="50" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="50" y1="14" x2="44" y2="20" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
            <line x1="20" y1="44" x2="14" y2="50" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
        </svg>''',
        "meta": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <polygon points="32,6 56,20 56,44 32,58 8,44 8,20" fill="none" stroke="{color}" stroke-width="2"/>
            <polygon points="32,18 46,26 46,38 32,46 18,38 18,26" fill="none" stroke="{color}" stroke-width="1.5" opacity="0.6"/>
            <circle cx="32" cy="32" r="4" fill="{color}"/>
            <line x1="32" y1="6" x2="32" y2="18" stroke="{color}" stroke-width="1" opacity="0.5"/>
            <line x1="56" y1="20" x2="46" y2="26" stroke="{color}" stroke-width="1" opacity="0.5"/>
            <line x1="56" y1="44" x2="46" y2="38" stroke="{color}" stroke-width="1" opacity="0.5"/>
            <line x1="32" y1="58" x2="32" y2="46" stroke="{color}" stroke-width="1" opacity="0.5"/>
            <line x1="8" y1="44" x2="18" y2="38" stroke="{color}" stroke-width="1" opacity="0.5"/>
            <line x1="8" y1="20" x2="18" y2="26" stroke="{color}" stroke-width="1" opacity="0.5"/>
        </svg>''',
        "orchestration": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <circle cx="32" cy="14" r="6" fill="{color}"/>
            <circle cx="14" cy="40" r="6" fill="none" stroke="{color}" stroke-width="2"/>
            <circle cx="32" cy="40" r="6" fill="none" stroke="{color}" stroke-width="2"/>
            <circle cx="50" cy="40" r="6" fill="none" stroke="{color}" stroke-width="2"/>
            <circle cx="32" cy="56" r="4" fill="{color}" opacity="0.5"/>
            <line x1="32" y1="20" x2="14" y2="34" stroke="{color}" stroke-width="1.8"/>
            <line x1="32" y1="20" x2="32" y2="34" stroke="{color}" stroke-width="1.8"/>
            <line x1="32" y1="20" x2="50" y2="34" stroke="{color}" stroke-width="1.8"/>
            <line x1="14" y1="46" x2="32" y2="54" stroke="{color}" stroke-width="1.5" opacity="0.6"/>
            <line x1="32" y1="46" x2="32" y2="52" stroke="{color}" stroke-width="1.5" opacity="0.6"/>
            <line x1="50" y1="46" x2="32" y2="54" stroke="{color}" stroke-width="1.5" opacity="0.6"/>
        </svg>''',
        "other": f'''<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <rect x="10" y="10" width="44" height="44" rx="6" fill="none" stroke="{color}" stroke-width="2"/>
            <circle cx="32" cy="32" r="6" fill="{color}"/>
        </svg>''',
    }
    return icons.get(category_id, icons["other"])


# ---------- 打包 ----------
def package_skill(skill_dir: Path, name: str) -> str:
    zip_path = DL_DIR / f"{name}.zip"
    DL_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in skill_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                z.write(f, arcname=f"{name}/{f.relative_to(skill_dir)}"
                )
    return f"downloads/{name}.zip"


# ---------- 渲染 HTML ----------
def render_html(skills: list[dict], stats: dict) -> str:
    cats = {cid: c for cid, c in CATEGORIES.items()}
    cats["other"] = {"label": "其他", "color": "#888888"}

    cat_buttons = "\n".join(
        f'<button class="cat-btn" data-cat="{cid}" style="--cat-color:{c["color"]}">'
        f'{c["label"]} <span class="cat-count">{stats["by_cat"].get(cid, 0)}</span>'
        f'</button>'
        for cid, c in cats.items() if stats["by_cat"].get(cid, 0) > 0
    )

    cards = "\n".join(render_card(s) for s in skills)
    skills_json = json.dumps([{
        "name": s["name"], "desc": s["desc"], "overview": s["overview"],
        "triggers": s["triggers"], "category_id": s["category_id"],
        "category": s["category"], "color": s["color"],
        "size_kb": s["size_kb"], "files": s["files"],
        "download": s.get("download", ""),
        "body_md": s.get("body_md", ""),
    } for s in skills], ensure_ascii=False)

    return HTML_TEMPLATE.format(
        total=stats["total"],
        cat_count=len([c for c in stats["by_cat"].values() if c > 0]),
        total_size=stats["total_size_mb"],
        cat_buttons=cat_buttons,
        cards=cards,
        skills_json=skills_json,
    )


def render_card(s: dict) -> str:
    triggers_html = "".join(
        f'<span class="trigger">{t}</span>' for t in s["triggers"][:4]
    )
    return f'''
<div class="card" data-cat="{s["category_id"]}" data-name="{s["name"].lower()}"
     data-search="{(s["name"] + " " + s["desc"]).lower().replace('"', "&quot;")}"
     onclick="showDetail('{s["name"]}')" style="--card-color:{s["color"]}">
  <div class="card-icon">{svg_icon(s["category_id"], s["color"])}</div>
  <div class="card-body">
    <div class="card-head">
      <h3>{s["name"]}</h3>
      <span class="card-cat">{s["category"]}</span>
    </div>
    <p class="card-desc">{truncate(s["desc"], 130)}</p>
    <div class="card-triggers">{triggers_html}</div>
    <div class="card-meta">
      <span>{s["files"]} 文件</span>
      <span>·</span>
      <span>{s["size_kb"]} KB</span>
    </div>
  </div>
</div>'''


def truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


# ---------- HTML 模板 ----------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ted's Skills · Claude Code 个人技能沉淀</title>
<style>
  :root {{
    --bg: #0f1419;
    --bg-elev: #1a2028;
    --bg-card: #1e252f;
    --bg-hover: #252d38;
    --text: #e6e6e6;
    --text-dim: #8b95a5;
    --text-mute: #5a6573;
    --border: #2a323d;
    --accent: #d4a574;
    --shadow: 0 4px 12px rgba(0,0,0,0.3);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}
  header {{
    padding: 48px 32px 32px; border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #141a22 0%, var(--bg) 100%);
  }}
  .header-inner {{ max-width: 1320px; margin: 0 auto; }}
  .brand {{
    display: flex; align-items: baseline; gap: 16px; margin-bottom: 12px;
  }}
  .brand h1 {{
    margin: 0; font-size: 28px; font-weight: 600; letter-spacing: -0.5px;
  }}
  .brand .accent {{ color: var(--accent); }}
  .tagline {{ color: var(--text-dim); font-size: 15px; margin: 0; }}
  .stats {{
    display: flex; gap: 32px; margin-top: 24px;
  }}
  .stat {{ display: flex; flex-direction: column; gap: 2px; }}
  .stat-num {{ font-size: 24px; font-weight: 600; color: var(--accent); }}
  .stat-label {{ font-size: 12px; color: var(--text-mute); text-transform: uppercase; letter-spacing: 1px; }}

  .controls {{
    max-width: 1320px; margin: 0 auto; padding: 24px 32px;
    display: flex; flex-direction: column; gap: 16px;
    position: sticky; top: 0; background: var(--bg); z-index: 10;
    border-bottom: 1px solid var(--border);
  }}
  .search-box {{
    width: 100%; padding: 12px 16px; background: var(--bg-elev);
    border: 1px solid var(--border); border-radius: 8px;
    color: var(--text); font-size: 14px; outline: none;
    transition: border-color 0.2s;
  }}
  .search-box:focus {{ border-color: var(--accent); }}
  .cat-bar {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .cat-btn {{
    padding: 6px 14px; background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 20px; color: var(--text-dim); font-size: 13px; cursor: pointer;
    transition: all 0.2s; font-family: inherit;
  }}
  .cat-btn:hover {{ color: var(--text); border-color: var(--cat-color, var(--accent)); }}
  .cat-btn.active {{
    background: var(--cat-color, var(--accent)); color: #1a1a1a; border-color: transparent; font-weight: 500;
  }}
  .cat-count {{ opacity: 0.7; margin-left: 4px; font-size: 11px; }}

  .grid {{
    max-width: 1320px; margin: 0 auto; padding: 24px 32px 64px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px;
  }}
  .card {{
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; cursor: pointer; transition: all 0.2s;
    display: flex; gap: 16px; align-items: flex-start;
    position: relative; overflow: hidden;
  }}
  .card::before {{
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: var(--card-color); opacity: 0; transition: opacity 0.2s;
  }}
  .card:hover {{ background: var(--bg-hover); transform: translateY(-2px); box-shadow: var(--shadow); }}
  .card:hover::before {{ opacity: 1; }}
  .card.hidden {{ display: none; }}
  .card-icon {{
    flex: 0 0 56px; height: 56px; padding: 8px;
    background: rgba(255,255,255,0.03); border-radius: 8px;
  }}
  .card-icon svg {{ width: 100%; height: 100%; display: block; }}
  .card-body {{ flex: 1; min-width: 0; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 6px; }}
  .card-head h3 {{
    margin: 0; font-size: 15px; font-weight: 600; color: var(--text);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .card-cat {{
    font-size: 11px; color: var(--card-color); flex-shrink: 0;
    padding: 2px 8px; background: rgba(255,255,255,0.04); border-radius: 4px;
  }}
  .card-desc {{
    margin: 0 0 10px; font-size: 13px; color: var(--text-dim); line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .card-triggers {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }}
  .trigger {{
    font-size: 11px; padding: 2px 8px; background: rgba(255,255,255,0.04);
    border-radius: 3px; color: var(--text-mute);
  }}
  .card-meta {{
    display: flex; gap: 6px; font-size: 11px; color: var(--text-mute);
  }}

  /* 详情抽屉 */
  .drawer-overlay {{
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    opacity: 0; pointer-events: none; transition: opacity 0.3s; z-index: 100;
    backdrop-filter: blur(2px);
  }}
  .drawer-overlay.open {{ opacity: 1; pointer-events: auto; }}
  .drawer {{
    position: fixed; right: 0; top: 0; bottom: 0; width: min(720px, 100vw);
    background: var(--bg-elev); border-left: 1px solid var(--border);
    transform: translateX(100%); transition: transform 0.3s ease;
    z-index: 101; overflow-y: auto;
  }}
  .drawer.open {{ transform: translateX(0); }}
  .drawer-head {{
    padding: 24px 32px; border-bottom: 1px solid var(--border);
    display: flex; gap: 16px; align-items: flex-start;
    position: sticky; top: 0; background: var(--bg-elev); z-index: 1;
  }}
  .drawer-icon {{ flex: 0 0 56px; height: 56px; padding: 8px;
    background: rgba(255,255,255,0.03); border-radius: 8px; }}
  .drawer-icon svg {{ width: 100%; height: 100%; }}
  .drawer-title-block {{ flex: 1; }}
  .drawer-title-block h2 {{ margin: 0 0 4px; font-size: 22px; }}
  .drawer-cat {{ font-size: 12px; color: var(--text-dim); }}
  .drawer-close {{
    background: none; border: none; color: var(--text-dim); font-size: 24px;
    cursor: pointer; padding: 0 8px; line-height: 1;
  }}
  .drawer-close:hover {{ color: var(--text); }}
  .drawer-body {{ padding: 24px 32px 64px; }}
  .drawer-section {{ margin-bottom: 28px; }}
  .drawer-section h4 {{
    margin: 0 0 12px; font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--text-mute); font-weight: 600;
  }}
  .drawer-section p {{ margin: 0; color: var(--text); font-size: 14px; }}
  .drawer-triggers {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .drawer-triggers .trigger {{
    font-size: 12px; padding: 4px 10px; background: rgba(212,165,116,0.1);
    color: var(--accent); border: 1px solid rgba(212,165,116,0.2);
  }}
  .drawer-actions {{ display: flex; gap: 12px; }}
  .btn {{
    padding: 10px 20px; border-radius: 6px; font-size: 13px; font-weight: 500;
    cursor: pointer; border: none; font-family: inherit; transition: all 0.2s;
    text-decoration: none; display: inline-flex; align-items: center; gap: 6px;
  }}
  .btn-primary {{ background: var(--accent); color: #1a1a1a; }}
  .btn-primary:hover {{ background: #e0b585; }}
  .btn-ghost {{ background: var(--bg-card); color: var(--text); border: 1px solid var(--border); }}
  .btn-ghost:hover {{ background: var(--bg-hover); }}
  .body-preview {{
    background: var(--bg); padding: 16px; border-radius: 6px; font-size: 13px;
    color: var(--text-dim); line-height: 1.7; max-height: 320px; overflow-y: auto;
    border: 1px solid var(--border); white-space: pre-wrap;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .meta-grid {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;
    background: var(--bg); padding: 16px; border-radius: 6px;
    border: 1px solid var(--border);
  }}
  .meta-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .meta-label {{ font-size: 11px; color: var(--text-mute); text-transform: uppercase; letter-spacing: 1px; }}
  .meta-value {{ font-size: 14px; color: var(--text); }}

  footer {{
    text-align: center; padding: 32px; color: var(--text-mute); font-size: 12px;
    border-top: 1px solid var(--border);
  }}
  footer a {{ color: var(--text-dim); }}

  @media (max-width: 640px) {{
    header, .controls, .grid {{ padding-left: 16px; padding-right: 16px; }}
    .grid {{ grid-template-columns: 1fr; }}
    .stats {{ gap: 20px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="brand">
      <h1>Ted's <span class="accent">Skills</span></h1>
      <span class="tagline">Claude Code 个人技能沉淀 · 持续更新中</span>
    </div>
    <p class="tagline">每个 skill 都是一段被验证过的工作流——从金融建模到工程协作，覆盖我日常使用的全部领域。</p>
    <div class="stats">
      <div class="stat"><span class="stat-num">{total}</span><span class="stat-label">Skills</span></div>
      <div class="stat"><span class="stat-num">{cat_count}</span><span class="stat-label">分类</span></div>
      <div class="stat"><span class="stat-num">{total_size}</span><span class="stat-label">MB 总量</span></div>
    </div>
  </div>
</header>

<div class="controls">
  <input type="text" class="search-box" id="search" placeholder="搜索 skill 名称、描述或触发词…">
  <div class="cat-bar">
    <button class="cat-btn active" data-cat="all">全部 <span class="cat-count">{total}</span></button>
    {cat_buttons}
  </div>
</div>

<div class="grid" id="grid">
{cards}
</div>

<div class="drawer-overlay" id="overlay" onclick="closeDetail()"></div>
<div class="drawer" id="drawer">
  <div class="drawer-head">
    <div class="drawer-icon" id="d-icon"></div>
    <div class="drawer-title-block">
      <h2 id="d-title">—</h2>
      <span class="drawer-cat" id="d-cat">—</span>
    </div>
    <button class="drawer-close" onclick="closeDetail()">×</button>
  </div>
  <div class="drawer-body">
    <div class="drawer-section">
      <h4>下载 / 安装</h4>
      <div class="drawer-actions">
        <a class="btn btn-primary" id="d-download" href="#" download>↓ 下载 zip</a>
        <button class="btn btn-ghost" onclick="copyInstall()">复制安装命令</button>
      </div>
      <p style="margin-top:10px; font-size:12px; color:var(--text-mute);" id="d-install-hint">
        解压到 <code style="background:var(--bg-card);padding:2px 6px;border-radius:3px;">~/.claude/skills/</code> 即可使用
      </p>
    </div>
    <div class="drawer-section">
      <h4>讲解</h4>
      <p id="d-desc">—</p>
    </div>
    <div class="drawer-section" id="d-triggers-section">
      <h4>触发场景</h4>
      <div class="drawer-triggers" id="d-triggers"></div>
    </div>
    <div class="drawer-section">
      <h4>核心思路</h4>
      <p id="d-overview" style="color:var(--text-dim);">—</p>
    </div>
    <div class="drawer-section">
      <h4>元信息</h4>
      <div class="meta-grid">
        <div class="meta-item"><span class="meta-label">分类</span><span class="meta-value" id="d-meta-cat">—</span></div>
        <div class="meta-item"><span class="meta-label">文件数</span><span class="meta-value" id="d-meta-files">—</span></div>
        <div class="meta-item"><span class="meta-label">大小</span><span class="meta-value" id="d-meta-size">—</span></div>
        <div class="meta-item"><span class="meta-label">本地路径</span><span class="meta-value" id="d-meta-path" style="font-size:11px;font-family:ui-monospace,monospace;">—</span></div>
      </div>
    </div>
  </div>
</div>

<footer>
  Generated by build.py · 重跑生成器即可同步新增的 skill · <a href="https://docs.claude.com/en/docs/claude-code">Claude Code 文档</a>
</footer>

<script>
const SKILLS = {skills_json};
const ICONS = {{
  finance: '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><rect x="6" y="10" width="52" height="44" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><line x1="6" y1="20" x2="58" y2="20" stroke="currentColor" stroke-width="2"/><polyline points="10,50 22,38 36,44 52,26" fill="none" stroke="currentColor" stroke-width="2.2"/><circle cx="52" cy="26" r="2.2" fill="currentColor"/></svg>',
  chinese: '<svg viewBox="0 0 64 64"><rect x="8" y="8" width="48" height="48" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><text x="32" y="42" text-anchor="middle" font-family="serif" font-size="28" font-weight="bold" fill="currentColor">中</text></svg>',
  engineering: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="14" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="32" cy="32" r="4" fill="currentColor"/></svg>',
  meta: '<svg viewBox="0 0 64 64"><polygon points="32,6 56,20 56,44 32,58 8,44 8,20" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="32" cy="32" r="4" fill="currentColor"/></svg>',
  orchestration: '<svg viewBox="0 0 64 64"><circle cx="32" cy="14" r="6" fill="currentColor"/><circle cx="14" cy="40" r="6" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="32" cy="40" r="6" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="50" cy="40" r="6" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  other: '<svg viewBox="0 0 64 64"><rect x="10" y="10" width="44" height="44" rx="6" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
}};

const cards = document.querySelectorAll('.card');
const search = document.getElementById('search');
let activeCat = 'all';

document.querySelectorAll('.cat-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeCat = btn.dataset.cat;
    applyFilter();
  }});
}});

search.addEventListener('input', applyFilter);

function applyFilter() {{
  const q = search.value.toLowerCase().trim();
  cards.forEach(c => {{
    const matchCat = activeCat === 'all' || c.dataset.cat === activeCat;
    const matchQ = !q || c.dataset.search.includes(q);
    c.classList.toggle('hidden', !(matchCat && matchQ));
  }});
}}

let currentSkill = null;
function showDetail(name) {{
  const s = SKILLS.find(x => x.name === name);
  if (!s) return;
  currentSkill = s;
  document.getElementById('d-title').textContent = s.name;
  document.getElementById('d-cat').textContent = s.category;
  document.getElementById('d-cat').style.color = s.color;
  document.getElementById('d-icon').innerHTML = ICONS[s.category_id] || ICONS.other;
  document.getElementById('d-icon').style.color = s.color;
  document.getElementById('d-desc').textContent = s.desc || '—';
  document.getElementById('d-overview').textContent = s.overview || '（无概述）';
  document.getElementById('d-meta-cat').textContent = s.category;
  document.getElementById('d-meta-files').textContent = s.files;
  document.getElementById('d-meta-size').textContent = s.size_kb + ' KB';
  document.getElementById('d-meta-path').textContent = '~/.claude/skills/' + s.name + '/';

  const trigBox = document.getElementById('d-triggers');
  trigBox.innerHTML = '';
  if (s.triggers && s.triggers.length) {{
    s.triggers.forEach(t => {{
      const el = document.createElement('span');
      el.className = 'trigger';
      el.textContent = t;
      trigBox.appendChild(el);
    }});
    document.getElementById('d-triggers-section').style.display = 'block';
  }} else {{
    document.getElementById('d-triggers-section').style.display = 'none';
  }}

  document.getElementById('d-download').href = s.download;
  document.getElementById('d-download').setAttribute('download', s.name + '.zip');

  document.getElementById('overlay').classList.add('open');
  document.getElementById('drawer').classList.add('open');
}}

function closeDetail() {{
  document.getElementById('overlay').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}}

function copyInstall() {{
  if (!currentSkill) return;
  const cmd = `curl -L -o /tmp/${{currentSkill.name}}.zip <你的看板URL>/${{currentSkill.download}} && unzip -o /tmp/${{currentSkill.name}}.zip -d ~/.claude/skills/`;
  navigator.clipboard.writeText(cmd).then(() => {{
    const hint = document.getElementById('d-install-hint');
    const old = hint.innerHTML;
    hint.innerHTML = '✓ 已复制到剪贴板';
    setTimeout(() => hint.innerHTML = old, 2000);
  }});
}}

document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeDetail();
}});
</script>

</body>
</html>
"""


# ---------- main ----------
def main() -> None:
    skills: list[dict] = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = parse_skill(d)
        if s:
            s["download"] = package_skill(d, s["name"])
            skills.append(s)

    # 排序：先按分类（按 CATEGORIES 顺序），再按名称
    cat_order = list(CATEGORIES.keys()) + ["other"]
    skills.sort(key=lambda x: (cat_order.index(x["category_id"]), x["name"]))

    # 统计
    by_cat: dict[str, int] = {}
    total_size = 0
    for s in skills:
        by_cat[s["category_id"]] = by_cat.get(s["category_id"], 0) + 1
        total_size += s["size_kb"]
    stats = {
        "total": len(skills),
        "by_cat": by_cat,
        "total_size_mb": round(total_size / 1024, 1),
    }

    # 渲染
    html = render_html(skills, stats)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")

    # 元数据 JSON（外部可消费）
    (OUT_DIR / "skills.json").write_text(
        json.dumps([{k: v for k, v in s.items() if k != "body_md"} for s in skills],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("✓ 生成完成")
    print(f"  Skills: {stats['total']}")
    cat_dist = {(CATEGORIES[c]["label"] if c in CATEGORIES else c): n for c, n in by_cat.items()}
    print(f"  分类: {cat_dist}")
    print(f"  总大小: {stats['total_size_mb']} MB")
    print(f"  输出: {OUT_DIR}/index.html")


if __name__ == "__main__":
    main()
