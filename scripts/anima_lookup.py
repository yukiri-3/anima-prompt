"""Unified character lookup and clothing verification. Offline unless opted in."""

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

import yaml

from anima_tools_source import AnimaToolsSource, ROOT, normalize, tokens
from check_nsfw import NSFW_KEYWORDS
from resolve_cn_character import load_cache, resolve

COLORS = set("aqua black blonde blue brown cyan gray green grey indigo lavender magenta maroon orange pink purple red silver teal turquoise violet white yellow".split())
LENGTHS = {"very short hair", "short hair", "medium hair", "long hair", "very long hair", "absurdly long hair"}
STYLES = {"twintails", "short twintails", "ponytail", "side ponytail", "low ponytail", "high ponytail", "braid", "single braid", "twin braids", "hair bun", "double bun", "drill hair", "two side up", "one side up", "updo", "hime cut"}


def gender_tag(tag):
    return bool(re.fullmatch(r"\d+(?:girls?|boys?|others?)", tag)) or tag in {"solo", "no humans", "multiple girls", "multiple boys"}


def feature_group(tag):
    words = tag.split()
    if len(words) >= 2 and words[-1] in {"hair", "eyes"} and any(w in COLORS for w in words[:-1]):
        return words[-1] + "_color"
    if tag in LENGTHS:
        return "hair_length"
    if tag in STYLES:
        return "hair_style"
    if tag in {"flat chest", "small breasts", "medium breasts", "large breasts", "huge breasts", "gigantic breasts"}:
        return "body_size"
    return None


def is_feature(tag):
    if tag.startswith("fake ") or "ornament" in tag or re.search(r"\bhair (?:bow|ribbon|tubes|scrunchie)\b", tag) or tag in {"hairband", "hairclip"}:
        return False
    return bool(feature_group(tag)) or bool(re.search(
        r"\b(?:hair|eyes|pupils|bangs|ahoge|sidelocks|ears|ear fluff|tails?|horns?|halo|wings|fangs?|sharp teeth|mole|scars?|heterochromia|fins)\b", tag
    ))


def is_outfit(tag, vocabulary):
    if tag in vocabulary:
        return True
    # A coloured variant can identify clothing without being verified as a tag.
    words = tag.split()
    return (len(words) > 1 and words[0] in COLORS and " ".join(words[1:]) in vocabulary) or bool(re.search(
        r"\b(?:dress|skirt|shirt|sleeves|uniform|swimsuit|leotard|bodysuit|gloves|boots|shoes|socks|thighhighs|pantyhose|hat|headwear|headdress|headband|hairband|hairclip|bow|ribbon|ornament|scarf|necktie|choker)\b", tag
    ))


def split_tags(tags, vocabulary):
    genders, identity, outfit, other = [], [], [], []
    for tag in tokens(tags):
        target = genders if gender_tag(tag) else identity if is_feature(tag) else outfit if is_outfit(tag, vocabulary) else other
        target.append(tag)
    return genders, identity, outfit, other


def select_identity(identity, index=None, overrides=None):
    identity = tokens(identity)
    overrides = tokens(overrides)
    if any(not is_feature(t) for t in overrides):
        raise ValueError("--identity 只接受外观特征；服装通过 --clothing 指定")
    overridden = {feature_group(t) for t in overrides if feature_group(t)}
    identity = [t for t in identity if not feature_group(t) or feature_group(t) not in overridden]
    combined = tokens(overrides + identity)
    groups = {}
    for tag in combined:
        group = feature_group(tag)
        if group == "eyes_color" and "heterochromia" in combined:
            continue
        if group == "hair_color" and any(t in combined for t in ("multicolored hair", "two-tone hair", "gradient hair", "streaked hair")):
            continue
        if group:
            groups.setdefault(group, []).append(tag)
    chosen = {}
    for group, choices in groups.items():
        preferred = ""
        if index and group not in overridden:
            field, suffix = ("hair", "hair") if group == "hair_color" else ("eye", "eyes")
            if group in {"hair_color", "eyes_color"}:
                preferred = f"{normalize(index.get(field, ''))} {suffix}"
        chosen[group] = preferred if preferred in choices else choices[0]
    selected = [t for t in combined if feature_group(t) not in chosen or chosen[feature_group(t)] == t]
    alternatives = {g: v for g, v in groups.items() if len(v) > 1}
    return selected, alternatives


def character_record(row, source, vocabulary):
    genders, identity, outfit, other = split_tags(row.get("tags") or row.get("core_tags", ""), vocabulary)
    selected, alternatives = select_identity(identity, row.get("index"))
    name = normalize(row.get("character", ""))
    copyright = normalize(row.get("copyright", ""))
    trigger = tokens(row.get("trigger")) or tokens([name, copyright])
    # Keep a canonical character trigger even for a manually provided description.
    trigger = tokens([name] + trigger + tokens(copyright))
    return {
        "character": name.replace(" ", "_"), "copyright": copyright.replace(" ", "_"),
        "source": source, "trigger": trigger, "gender": genders,
        "identity": selected, "identity_candidates": identity, "alternatives": alternatives,
        "default_outfit": outfit, "other_tags": other,
        "all_tags": tokens(genders + trigger + selected + outfit + other),
        "outfit_basis": "source-tags; not proof of canonical/default costume",
    }


def csv_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def api_get(endpoint, params):
    url = "https://danbooru.donmai.us/" + endpoint + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "anima-prompt/0.1 (character lookup)", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def online_character(query, vocabulary):
    slug = normalize(query).replace(" ", "_")
    data = api_get("tags.json", {"search[name_matches]": slug, "search[category]": 4, "limit": 10})
    matches = [t for t in data if t.get("name") == slug and t.get("category") == 4]
    if len(matches) != 1:
        return None
    # General-rated, single-character samples reduce alternate/crossover pollution.
    time.sleep(0.5)
    posts = api_get("posts.json", {"tags": f"{slug} solo rating:g -alternate_costume -cosplay -parody -crossover -genderswap -chibi order:score", "limit": 20})
    if not isinstance(posts, list):
        raise ValueError("Danbooru posts 响应不是数组")
    excluded = {"alternate_costume", "cosplay", "parody", "crossover", "genderswap", "chibi"}
    samples = [p for p in posts if p.get("tag_string_character", "").split() == [slug] and p.get("rating") == "g"
               and not excluded.intersection(p.get("tag_string_general", "").split())]
    tags = Counter(t for p in samples for t in set(tokens(p.get("tag_string_general", "").split())))
    frequent = [t for t, n in tags.most_common() if n / len(samples) >= 0.6] if samples else []
    copyrights = Counter(t for p in samples for t in p.get("tag_string_copyright", "").split())
    row = {"character": slug, "copyright": copyrights.most_common(1)[0][0] if copyrights else "", "tags": frequent}
    record = character_record(row, "danbooru-online-sample", vocabulary)
    record["sample_count"] = len(samples)
    record["outfit_basis"] = "general-rated solo sample >=60%; inference, not official costume"
    # Scene/action frequencies are not identity evidence.
    record["other_tags"] = []
    record["all_tags"] = tokens(record["gender"] + record["trigger"] + record["identity"] + record["default_outfit"])
    return record


def lookup_character(query, source, copyright=None, limit=10, online=False, bangumi=False):
    vocabulary = source.attire()
    cache = load_cache()
    alias = cache.get(query)
    queries = {normalize(query)}
    if isinstance(alias, str):
        queries.add(normalize(alias))
    cp = normalize(copyright) if copyright else None
    sources = [
        ("extra-characters", lambda: csv_rows(ROOT / "tag-library/extra_characters.csv")),
        (None, source.characters),
        ("danbooru-csv", lambda: csv_rows(ROOT / "tag-library/danbooru_character.csv")),
    ]
    candidates = {}
    exact = {}
    for source_name, read_rows in sources:
        for row in read_rows():
            name, series = normalize(row.get("character", "")), normalize(row.get("copyright", ""))
            if not name or cp is not None and cp != series:
                continue
            key = (name, series)
            is_exact = name in queries or any(q == f"{name}, {series}" for q in queries)
            if not is_exact and not any(q in name or q in series or q == normalize(row.get("index", {}).get("name_zh", "")) for q in queries):
                continue
            record = character_record(row, source_name or row["source"], vocabulary)
            candidates.setdefault(key, record)
            if is_exact:
                exact.setdefault(key, record)
        if exact:
            break
    if exact:
        records = list(exact.values())
        return {"status": "found" if len(records) == 1 else "ambiguous", "query": query, "results": records[:limit], "total": len(records), "warnings": list(source.warnings)}
    # Translation is explicit and never writes inferred romanizations as verified tags.
    if bangumi and not alias:
        try:
            _, _, translated = resolve(query)
        except SystemExit as exc:
            raise ValueError("Bangumi 查询失败；参见网络错误信息") from exc
        if translated:
            result = lookup_character(translated, source, copyright, limit, online, False)
            result["query"] = query
            result["translated_name"] = translated
            result["warnings"].append("Bangumi 罗马字是名称候选；请核对是否为原请求角色")
            return result
    if online:
        record = online_character(alias or query, vocabulary)
        if record and (cp is None or normalize(record["copyright"]) == cp):
            return {"status": "found", "query": query, "results": [record], "total": 1, "warnings": list(source.warnings)}
    records = list(candidates.values())
    if not records and isinstance(alias, str) and cp is None:
        record = character_record({"character": alias}, "local-alias-only", vocabulary)
        return {"status": "alias_only", "query": query, "results": [record], "total": 1,
                "warnings": list(source.warnings) + ["仅核实本地别名；出处、外观与服装数据缺失，请从用户描述补充"]}
    return {"status": "candidates" if records else "not_found", "query": query, "results": records[:limit], "total": len(records), "warnings": list(source.warnings)}


def verify_clothing(query, source, nsfw=False):
    vocabulary = source.attire()
    requested = tokens(query)
    blocked = [t for t in requested if t in NSFW_KEYWORDS and not nsfw]
    verified = [t for t in requested if t in vocabulary and t not in blocked]
    unverified = [t for t in requested if t not in vocabulary and t not in blocked]
    return {
        "status": "unavailable" if not vocabulary else "verified" if requested and not unverified and not blocked else "partial",
        "verified": verified, "unverified": unverified, "blocked": blocked,
        "suggestions": {t: sorted(v for v in vocabulary if t in v or v in t)[:8] for t in unverified},
        "source": "comfyui-anima-tools/danbooru_attire_data.json", "warnings": list(source.warnings),
    }


def search_clothing(query, source, limit=10, nsfw=False):
    key = normalize(query)
    vocabulary = source.attire()
    matches = sorted(t for t in vocabulary if key in t and (nsfw or t not in NSFW_KEYWORDS))
    recipes = []
    for item in source.load("clothing_data"):
        fields = [item.get("name", ""), item.get("name_zh", ""), item.get("tags", ""), item.get("tags_zh", "")]
        if not any(key in normalize(f) for f in fields):
            continue
        tag_list = tokens(item.get("tags"))
        if not nsfw and any(t in NSFW_KEYWORDS for t in tag_list):
            continue
        recipes.append({"name": item.get("name"), "name_zh": item.get("name_zh"), "tags": tag_list, "verified": [t for t in tag_list if t in vocabulary], "unverified": [t for t in tag_list if t not in vocabulary], "source": "comfyui-anima-tools/clothing_data.js"})
    return {"status": "found" if matches or recipes else "not_found" if vocabulary else "unavailable", "tags": matches[:limit], "recipes": recipes[:limit], "warnings": list(source.warnings)}


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def source_options(parser):
    parser.add_argument("--anima-tools", help="插件根目录；优先于环境变量和配置")
    parser.add_argument("--config", help="配置 YAML；默认仓库 config.local.yaml")
    parser.add_argument("--json", action="store_true", help="JSON 输出")


def emit(result, json_output=True):
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result.get('status')}")
        for row in result.get("results", []):
            print(f"{row['character']} [{row['copyright']}] ({row['source']})")
            print("identity: " + ", ".join(row["identity"]))
            print("default_outfit: " + ", ".join(row["default_outfit"]))
        for field in ("verified", "unverified", "blocked", "tags", "recipes", "warnings"):
            if result.get(field):
                print(f"{field}: {result[field]}")


def main():
    parser = argparse.ArgumentParser(description="Anima 角色查询/服装标签校验")
    sub = parser.add_subparsers(dest="command", required=True)
    char = sub.add_parser("character")
    char.add_argument("query")
    char.add_argument("--copyright", help="作品精确过滤，消除同名歧义")
    char.add_argument("--limit", type=positive_int, default=10)
    char.add_argument("--online", action="store_true", help="本地精确查询失败时读取 Danbooru；不写库")
    char.add_argument("--bangumi", action="store_true", help="显式允许 Bangumi 翻译回退；不写库")
    source_options(char)
    cloth = sub.add_parser("clothing")
    cloth.add_argument("query", help="逗号分隔英文候选 tags；--search 时也可用中文")
    cloth.add_argument("--search", action="store_true", help="搜索标签及服装配方，不自动采用配方")
    cloth.add_argument("--limit", type=positive_int, default=10)
    cloth.add_argument("--nsfw", action="store_true")
    source_options(cloth)
    args = parser.parse_args()
    try:
        if not args.query.strip():
            raise ValueError("查询不能为空")
        source = AnimaToolsSource(args.anima_tools, args.config)
        if args.command == "character":
            result = lookup_character(args.query, source, args.copyright, args.limit, args.online, args.bangumi)
        elif args.search:
            result = search_clothing(args.query, source, args.limit, args.nsfw)
        else:
            result = verify_clothing(args.query, source, args.nsfw)
        emit(result, args.json)
        return 0 if result["status"] in {"found", "verified"} else 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        emit({"status": "error", "error": str(exc)}, True)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
