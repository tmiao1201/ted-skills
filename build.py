#!/usr/bin/env python3
"""
Skills Dashboard Builder
扫描 ~/.claude/skills/ 下所有 SKILL.md，生成可视化看板 + 下载包。

注意：HTML 模板已抽出到 template.html，本文件只负责数据生成 + 模板替换。
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"
OUT_DIR = Path.home() / "skills_dashboard"
DL_DIR = OUT_DIR / "downloads"
TEMPLATE_FILE = OUT_DIR / "template.html"

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
            "kautoresearch", "kenmoe", "tedmoe", "research", "workflow-runner",
            "github-cron", "building-feishu-daily-reports", "huashu-nuwa",
        },
    },
    "perspective": {
        "label": "人物视角",
        "color": "#8b6fb1",
        "skills": set(),  # 后缀 *-perspective 自动匹配，见 classify()
    },
}

CATEGORY_EMOJI = {
    "finance": "📊", "chinese": "🇨🇳", "engineering": "🛠",
    "meta": "🧩", "orchestration": "🎼", "perspective": "🎭", "other": "📦",
}


def classify(name: str) -> tuple[str, str, str]:
    if name.endswith("-perspective") or name in ("x-mastery-mentor",):
        return "perspective", CATEGORIES["perspective"]["label"], CATEGORIES["perspective"]["color"]
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

    if not desc:
        for line in body.split("\n"):
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith(">") and not s.startswith("<"):
                desc = re.sub(r"\*\*|`|\[|\]\(.*?\)", "", s)[:300]
                break

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
        "source": "installed",
    }


def extract_triggers(desc: str) -> list[str]:
    triggers: list[str] = []
    for marker in ["Use when:", "Triggers on", "触发词", "触发：", "Trigger when:", "Examples:"]:
        if marker in desc:
            tail = desc.split(marker, 1)[1]
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


# ---------- 打包 ----------
# GitHub 单文件上限 100 MB；超过此阈值的 skill 不打包（避免 push 失败）
MAX_PACKAGE_MB = 95


def package_skill(skill_dir: Path, name: str, size_kb: int) -> str:
    # 跳过超大 skill（GitHub 100MB 限制）
    if size_kb > MAX_PACKAGE_MB * 1024:
        print(f"  ⚠ 跳过打包 {name}（{size_kb // 1024} MB，超过 {MAX_PACKAGE_MB}MB 上限）")
        # 如果之前 zip 已存在，删掉避免 git 误 add
        old = DL_DIR / f"{name}.zip"
        if old.exists():
            old.unlink()
        return ""  # 空字符串表示无下载

    zip_path = DL_DIR / f"{name}.zip"
    DL_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in skill_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                z.write(f, arcname=f"{name}/{f.relative_to(skill_dir)}")
    return f"downloads/{name}.zip"


# ---------- 渲染 HTML ----------
def render_card(s: dict) -> str:
    triggers_html = "".join(
        f'<span class="trigger">{t}</span>' for t in s["triggers"][:3]
    )
    source = s.get("source", "installed")
    source_badge = '<span class="badge-source badge-nuwa">女娲库</span>' if source == "nuwa_example" else ""
    emoji = CATEGORY_EMOJI.get(s["category_id"], "📦")
    desc_safe = s["desc"].replace('"', "&quot;")
    return f'''
<div class="card" data-cat="{s["category_id"]}" data-name="{s["name"].lower()}"
     data-search="{(s["name"] + " " + s["desc"]).lower().replace('"', "&quot;")}"
     onclick="showDetail('{s["name"]}')" style="--card-color:{s["color"]}">
  <div class="card-icon">{emoji}</div>
  <div class="card-body">
    <div class="card-head">
      <h3>{s["name"]}</h3>
      <div class="card-badges">
        {source_badge}
        <span class="card-cat">{s["category"]}</span>
      </div>
    </div>
    <p class="card-desc" data-desc-en="{desc_safe}">{truncate(s["desc"], 140)}</p>
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


def render_html(skills: list[dict], stats: dict) -> str:
    cats = {cid: c for cid, c in CATEGORIES.items()}
    cats["other"] = {"label": "其他", "color": "#888888"}

    # Sidebar 分类导航项
    nav_items = "\n".join(
        f'<button class="nav-item" data-cat="{cid}" style="--nav-color:{c["color"]}">'
        f'<span class="nav-emoji">{CATEGORY_EMOJI.get(cid, "📦")}</span>'
        f'<span class="nav-label">{c["label"]}</span>'
        f'<span class="nav-count">{stats["by_cat"].get(cid, 0)}</span>'
        f'</button>'
        for cid, c in cats.items() if stats["by_cat"].get(cid, 0) > 0
    )

    cards = "\n".join(render_card(s) for s in skills)
    skills_json = json.dumps([{
        "name": s["name"], "desc": s["desc"], "overview": s["overview"],
        "triggers": s["triggers"], "category_id": s["category_id"],
        "category": s["category"], "color": s["color"],
        "size_kb": s["size_kb"], "files": s["files"],
        "source": s.get("source", "installed"),
        "download": s.get("download", ""),
    } for s in skills], ensure_ascii=False)

    # 读模板（template.html 含完整 CSS/HTML/JS，用 __XX__ 占位符）
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    return (template
        .replace("__TOTAL__", str(stats["total"]))
        .replace("__CAT_COUNT__", str(len([c for c in stats["by_cat"].values() if c > 0])))
        .replace("__TOTAL_SIZE__", str(stats["total_size_mb"]))
        .replace("__NAV_ITEMS__", nav_items)
        .replace("__CARDS__", cards)
        .replace("__SKILLS_JSON__", skills_json)
    )


# ---------- main ----------
def main() -> None:
    skills: list[dict] = []
    seen_names: set[str] = set()

    # 优先级 1：~/.claude/skills/ 根目录直接安装的 skill
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = parse_skill(d)
        if s and s["name"] not in seen_names:
            s["download"] = package_skill(d, s["name"], s["size_kb"])
            skills.append(s)
            seen_names.add(s["name"])

    # 优先级 2：女娲 examples 库（perspective skills 备用库）
    nuwa_examples = SKILLS_DIR / "huashu-nuwa" / "examples"
    if nuwa_examples.exists():
        for d in sorted(nuwa_examples.iterdir()):
            if not d.is_dir():
                continue
            s = parse_skill(d)
            if s and s["name"] not in seen_names:
                s["source"] = "nuwa_example"
                s["download"] = package_skill(d, s["name"], s["size_kb"])
                skills.append(s)
                seen_names.add(s["name"])

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

    # 元数据 JSON
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
