"""Build a character fragment with verified new clothes and preserved identity."""

import argparse
import sys

import yaml

from anima_lookup import emit, lookup_character, select_identity, source_options, verify_clothing
from anima_tools_source import AnimaToolsSource, tokens
from check_nsfw import NSFW_KEYWORDS


def swap(character, clothing, source, copyright=None, identity=None, nsfw=False):
    result = lookup_character(character, source, copyright)
    if result["status"] != "found":
        return result
    checked = verify_clothing(clothing, source, nsfw)
    if checked["status"] != "verified":
        return {"status": "clothing_unverified", "clothing_check": checked, "warnings": result["warnings"]}
    row = result["results"][0]
    selected, alternatives = select_identity(row["identity"], overrides=identity)
    tag_list = tokens(row["gender"] + row["trigger"] + selected + checked["verified"])
    blocked = [t for t in tag_list if t in NSFW_KEYWORDS and not nsfw]
    if blocked:
        return {"status": "blocked", "blocked": blocked}
    return {
        "status": "found", "character": row["character"], "source": row["source"],
        "trigger": row["trigger"], "gender": row["gender"], "identity": selected,
        "alternatives": row["alternatives"] | alternatives, "removed_default_outfit": row["default_outfit"],
        "omitted_other_tags": row["other_tags"], "clothing": checked["verified"],
        "all_tags": tag_list, "prompt": ", ".join(tag_list), "warnings": result["warnings"],
    }


def main():
    parser = argparse.ArgumentParser(description="角色换装：输出角色片段，随后继续槽位组装与 check_prompt 校验")
    parser.add_argument("--character", required=True)
    parser.add_argument("--clothing", required=True, help="逗号分隔英文 tags，全部必须在 attire 库中")
    parser.add_argument("--copyright")
    parser.add_argument("--identity", help="用户指定的外观覆盖，如 pink hair, green eyes")
    parser.add_argument("--nsfw", action="store_true")
    source_options(parser)
    args = parser.parse_args()
    try:
        source = AnimaToolsSource(args.anima_tools, args.config)
        result = swap(args.character, args.clothing, source, args.copyright, args.identity, args.nsfw)
        if not args.json and result["status"] == "found":
            print(result["prompt"])
        else:
            emit(result, True)
        return 0 if result["status"] == "found" else 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        emit({"status": "error", "error": str(exc)}, True)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
