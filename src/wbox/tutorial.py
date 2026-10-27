"""wbox.tutorial —— 教程库：加载 / 过滤 / 检索（帮助中心的数据源）。

存在理由：教程是"人在某个步骤上卡住时最需要的东西"，所以它必须能被**按当前步骤
自动匹配**，而不是塞进帮助文档让人自己翻。本模块把 src/wbox/tutorials/*.md
（每篇带 front-matter）解析成结构化数据，供帮助中心做三件事：

  1. 情境教程：当前步骤（extract/plan/decide/fill/assemble/seal）对应哪几篇
  2. 相关推荐：按标签重合度打分排序
  3. 本地搜索：标题 / 标签 / 摘要 / 正文全文匹配

约定（写死）：
- front-matter 用最朴素的手写解析（key: value、[a, b]、- item 三种形式即可），
  **不引入 PyYAML**——为一个 5 字段的头信息加一个依赖不划算，而且打包更省事。
- 目录定位与 shapes/templates 同一套规则：Path(__file__).parent / "tutorials"，
  开发态与 PyInstaller 冻结态同一条路径，不会漂。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TUTORIALS_DIRNAME = "tutorials"
_DEFAULT_ORDER = 999

_CACHE: list["Tutorial"] | None = None


@dataclass
class Tutorial:
    """一篇教程。body 是去掉 front-matter 后的 Markdown 正文。"""

    slug: str
    title: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    order: int = _DEFAULT_ORDER
    body: str = ""
    path: Path | None = None

    def as_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "summary": self.summary,
            "tags": list(self.tags), "steps": list(self.steps),
            "order": self.order, "chars": len(self.body),
        }

    def haystack(self) -> str:
        """全文检索用的拼装串（标题 + 标签 + 摘要 + 正文）。"""
        return "\n".join([self.title, " ".join(self.tags), self.summary, self.body]).lower()


# ---------------------------------------------------------------- front-matter


def _clean_scalar(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def parse_front_matter(text: str) -> tuple[dict, str]:
    """解析 `---` 包裹的 front-matter，返回 (meta, body)。格式不对就原样返回。"""
    if not text.lstrip().startswith("---"):
        return {}, text
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return {}, text
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text

    meta: dict = {}
    key: str | None = None
    for raw in lines[start + 1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.lstrip()
        if stripped.startswith("- ") and key:                 # 块状列表
            value = meta.get(key)
            if not isinstance(value, list):
                value = []
            value.append(_clean_scalar(stripped[2:]))
            meta[key] = value
            continue
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        key = name.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [_clean_scalar(x) for x in inner.split(",") if x.strip()] if inner else []
        elif value == "":
            meta[key] = []                                     # 可能是块状列表的开头
        else:
            meta[key] = _clean_scalar(value)
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


def _to_int(value, default: int = _DEFAULT_ORDER) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,，]", value) if part.strip()]
    return []


# ---------------------------------------------------------------- 加载


def tutorials_dir() -> Path:
    """教程目录（开发态 src/wbox/tutorials，冻结态 _MEI/wbox/tutorials）。"""
    return Path(__file__).resolve().parent / TUTORIALS_DIRNAME


def load_tutorials(force: bool = False) -> list[Tutorial]:
    """加载全部教程，按 order 升序；目录缺失返回空列表（帮助中心显示空状态）。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    items: list[Tutorial] = []
    d = tutorials_dir()
    if d.is_dir():
        for path in sorted(d.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = parse_front_matter(text)
            title = str(meta.get("title") or path.stem)
            items.append(Tutorial(
                slug=path.stem,
                title=title,
                summary=str(meta.get("summary") or ""),
                tags=_as_list(meta.get("tags")),
                steps=[s.lower() for s in _as_list(meta.get("steps"))],
                order=_to_int(meta.get("order")),
                body=body,
                path=path,
            ))
    items.sort(key=lambda t: (t.order, t.title))
    _CACHE = items
    return items


def get(slug: str) -> Tutorial | None:
    return next((t for t in load_tutorials() if t.slug == slug), None)


# ---------------------------------------------------------------- 匹配


def by_step(step_id: str, limit: int = 3) -> list[Tutorial]:
    """当前步骤的「情境教程」。steps 为空的教程视为通用（排最后）。"""
    step = (step_id or "").strip().lower()
    hits = [t for t in load_tutorials() if step and step in t.steps]
    if not hits:
        hits = [t for t in load_tutorials() if not t.steps]
    return hits[:limit]


def related(tags: list[str] | None = None, step_id: str = "",
            limit: int = 5, exclude: set[str] | None = None) -> list[Tutorial]:
    """相关推荐：标签重合 ×2 + 命中当前步骤 ×3 打分，取前 limit。"""
    tags = {t.strip().lower() for t in (tags or []) if t.strip()}
    step = (step_id or "").strip().lower()
    exclude = exclude or set()
    scored: list[tuple[int, Tutorial]] = []
    for t in load_tutorials():
        if t.slug in exclude:
            continue
        score = 0
        if step and step in t.steps:
            score += 3
        score += 2 * len(tags & {x.lower() for x in t.tags})
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda pair: (-pair[0], pair[1].order))
    return [t for _score, t in scored[:limit]]


def search(keyword: str, limit: int = 20) -> list[Tutorial]:
    """本地全文检索：标题 / 标签 / 摘要 / 正文，忽略大小写。"""
    needle = (keyword or "").strip().lower()
    if not needle:
        return []
    terms = [t for t in re.split(r"\s+", needle) if t]
    hits: list[tuple[int, Tutorial]] = []
    for tut in load_tutorials():
        hay = tut.haystack()
        if not all(term in hay for term in terms):
            continue
        # 标题命中权重更高，便于排序
        score = 3 * sum(term in tut.title.lower() for term in terms)
        score += 1 * sum(term in " ".join(tut.tags).lower() for term in terms)
        hits.append((score, tut))
    hits.sort(key=lambda pair: (-pair[0], pair[1].order))
    return [t for _s, t in hits[:limit]]


def all_tags() -> list[str]:
    tags: list[str] = []
    for t in load_tutorials():
        for tag in t.tags:
            if tag not in tags:
                tags.append(tag)
    return tags


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WBox 教程库")
    parser.add_argument("--step", help="按步骤匹配（extract/plan/decide/fill/assemble/seal）")
    parser.add_argument("--search", help="本地全文检索关键词")
    args = parser.parse_args(argv)

    if args.search:
        for t in search(args.search):
            print(f"{t.title}  [{','.join(t.tags)}]  ({len(t.body)} 字)")
        return 0
    if args.step:
        for t in by_step(args.step, limit=10):
            print(f"{t.title}")
        return 0
    for t in load_tutorials():
        print(f"{t.order:>3}  {t.title:<30} tags={','.join(t.tags)}  steps={','.join(t.steps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
