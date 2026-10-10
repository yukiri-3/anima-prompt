#!/usr/bin/env python3
"""将中文角色名解析为 danbooru 蛇形命名（本地缓存 + Bangumi API）。

默认仅查本地缓存，未命中时提示使用 --bangumi 调用 API 查询并自动写入缓存。

输出 danbooru_name（如 "hatsune_miku"），可 pipe 到 character_lib.py：
  uv run scripts/resolve_cn_character.py 初音未来 | xargs uv run scripts/character_lib.py search {} --exact --limit 1 --json

用法:
  uv run scripts/resolve_cn_character.py <中文名>
  uv run scripts/resolve_cn_character.py 初音未来 --json
  uv run scripts/resolve_cn_character.py 迷迭香 --bangumi
"""

import argparse
import json
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import yaml

CACHE_PATH = Path(__file__).resolve().parent.parent / "tag-library" / "cn_char_map.yaml"
BANGUMI_API = "https://api.bgm.tv/v0/search/characters"
USER_AGENT = "anima-prompt/1.0"


def load_cache():
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.exists():
        shutil.copy2(CACHE_PATH, CACHE_PATH.with_suffix(CACHE_PATH.suffix + ".bak"))
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cache, f, allow_unicode=True, default_flow_style=False)


def bangumi_search(keyword):
    data = json.dumps({"keyword": keyword}).encode("utf-8")
    req = urllib.request.Request(
        BANGUMI_API,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("data", [])
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"网络错误: {e}", file=sys.stderr)
        sys.exit(1)


def bangumi_subjects(character_id):
    request = urllib.request.Request(
        f"https://api.bgm.tv/v0/characters/{int(character_id)}/subjects",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        subjects = json.load(response)
    if not isinstance(subjects, list):
        raise ValueError("Bangumi 关联作品响应不是数组")
    return subjects


def name_key(value):
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s_·・-]+", "", text)


def bangumi_candidates(keyword):
    """Expose exact names and all search candidates; never pick by search rank."""
    rows = bangumi_search(keyword)
    if not isinstance(rows, list):
        raise ValueError("Bangumi 搜索结果不是数组")
    candidates = []
    for row in rows:
        names = [row.get("name"), row.get("name_cn")]
        infobox = row.get("infobox") or []
        translations = []
        for item in infobox:
            value = item.get("value")
            if isinstance(value, str) and "名" in item.get("key", ""):
                names.append(value)
            elif item.get("key") == "别名" and isinstance(value, list):
                for alias in value:
                    if not isinstance(alias, dict) or not isinstance(alias.get("v"), str):
                        continue
                    names.append(alias["v"])
                    if alias.get("k") in ("罗马字", "英文名"):
                        translations.append((alias["k"], alias["v"]))
        translations.sort(key=lambda pair: pair[0] != "罗马字")
        source, extracted = translations[0] if translations else (None, None)
        candidates.append({
            "id": row.get("id"), "name": row.get("name"),
            "names": list(dict.fromkeys(n for n in names if isinstance(n, str) and n.strip())),
            "exact": any(name_key(n) == name_key(keyword) for n in names if n),
            "source": source, "extracted": extracted,
            "translated_name": to_snake(extracted) if extracted else None,
            "translations": list(dict.fromkeys(n for _, n in translations)),
        })
    return candidates


def extract_name(infobox):
    for item in infobox:
        if item.get("key") != "别名":
            continue
        aliases = item.get("value", [])
        for priority in ("罗马字", "英文名"):
            for alias in aliases:
                if alias.get("k") == priority:
                    return priority, alias.get("v", "")
    return None, None


def to_snake(name):
    return name.lower().strip().replace(" ", "_").replace("-", "_")


def resolve(keyword):
    exact = [row for row in bangumi_candidates(keyword) if row["exact"]]
    if len(exact) == 1 and exact[0]["extracted"]:
        row = exact[0]
        return row["source"], row["extracted"], row["translated_name"]
    return None, None, None


def main():
    parser = argparse.ArgumentParser(
        description="中文角色名 → danbooru 蛇形命名"
    )
    parser.add_argument("keyword", help="中文角色名或待补录的别名")
    parser.add_argument("--set", dest="alias_target", help="写入别名映射（值须为已核实的角色 tag），自动生成 .bak")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument(
        "--bangumi", action="store_true",
        help="未命中缓存时调用 Bangumi API 查询并自动写入缓存",
    )
    args = parser.parse_args()

    cache = load_cache()
    keyword = args.keyword

    if args.alias_target is not None:
        if not keyword.strip() or not args.alias_target.strip():
            parser.error("别名及目标 tag 不能为空")
        cache[keyword] = args.alias_target.strip()
        save_cache(cache)
        print(json.dumps({"chinese_name": keyword, "danbooru_name": cache[keyword]}, ensure_ascii=False) if args.json else cache[keyword])
        return

    if keyword in cache:
        name = cache[keyword]
        if args.json:
            json.dump({"chinese_name": keyword, "danbooru_name": name}, sys.stdout, ensure_ascii=False)
            print()
        else:
            print(name, end="")
        return

    if not args.bangumi:
        print(
            f"未在本地缓存中找到: {keyword}\n"
            f"  使用 --bangumi 参数调用 Bangumi API 查询并自动缓存",
            file=sys.stderr,
        )
        sys.exit(1)

    source, extracted, danbooru_name = resolve(keyword)

    if danbooru_name:
        cache[keyword] = danbooru_name
        save_cache(cache)
        if args.json:
            json.dump({
                "chinese_name": keyword,
                "source": source,
                "extracted": extracted,
                "danbooru_name": danbooru_name,
            }, sys.stdout, ensure_ascii=False, indent=2)
            print()
        else:
            print(danbooru_name, end="")
    else:
        if source is None and extracted is None:
            print(
                f"未找到唯一且含罗马字/英文名的 Bangumi 精确角色: {keyword}\n"
                "  先用 anima_lookup.py character --bangumi --json 查看候选，再用 --set 补录已核实的角色 tag",
                file=sys.stderr,
            )
        else:
            print(f"未在 Bangumi 找到角色: {keyword}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
