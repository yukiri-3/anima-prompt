"""Read Comfyui-Anima-Tools data without executing JS or copying its database."""

import json
import os
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "character_data": ("js/character_data.js", "characterData", list),
    "official_data": ("js/character_official_data.json", None, dict),
    "attire_data": ("js/danbooru_attire_data.json", None, dict),
    "clothing_data": ("js/clothing_data.js", "clothingData", list),
}


def normalize(value):
    text = unicodedata.normalize("NFKC", str(value)).lower().strip()
    text = re.sub(r"\\([()\[\]{}])", r"\1", text)
    return re.sub(r"\s+", " ", text.replace("_", " "))


def tokens(value):
    parts = value if isinstance(value, list) else str(value or "").split(",")
    return list(dict.fromkeys(normalize(p) for p in parts if isinstance(p, str) and p.strip()))


def read_data(path, variable=None):
    text = path.read_text(encoding="utf-8-sig")
    if variable:
        match = re.search(r"\b(?:const|let|var)\s+" + re.escape(variable) + r"\s*=\s*", text)
        if not match:
            raise ValueError(f"未找到 JSON 数组赋值: {variable}")
        # Upstream files are JSON literal arrays wrapped in const/window assignments.
        # raw_decode stops at the closing array; never eval/import JavaScript.
        value, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        return value
    return json.loads(text)


class AnimaToolsSource:
    def __init__(self, path=None, config=None):
        self.warnings = []
        self._data = {}
        config_path = Path(config).resolve() if config else ROOT / "config.local.yaml"
        settings = {}
        if config_path.exists():
            settings = yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
            if not isinstance(settings, dict) or not isinstance(settings.get("anima_tools", {}), dict):
                raise ValueError("配置必须是 anima_tools 映射")
        elif config:
            raise ValueError(f"配置文件不存在: {config_path}")
        self.settings = settings.get("anima_tools", {})
        for key in ("path", *FILES):
            if key in self.settings and not isinstance(self.settings[key], str):
                raise ValueError(f"anima_tools.{key} 必须是字符串；未配置路径请用空字符串")
        selected = path or os.environ.get("ANIMA_TOOLS_PATH") or self.settings.get("path")
        self.path = None
        if selected:
            self.path = Path(selected).expanduser()
            if not self.path.is_absolute():
                self.path = config_path.parent / self.path
            self.path = self.path.resolve()
            if not self.path.is_dir():
                self.warnings.append(f"Comfyui-Anima-Tools 目录不存在: {self.path}")
        else:
            self.warnings.append("未配置 Comfyui-Anima-Tools 路径；仅可使用本地 CSV/别名回退")

    def load(self, key):
        if key in self._data:
            return self._data[key]
        filename, variable, expected = FILES[key]
        value = expected()
        if self.path and self.path.is_dir():
            file = self.path / self.settings.get(key, filename)
            try:
                value = read_data(file, variable)
                if not isinstance(value, expected):
                    raise ValueError(f"应为 {expected.__name__}")
                if key in ("character_data", "clothing_data") and not all(isinstance(v, dict) for v in value):
                    raise ValueError("数组元素应为对象")
                if key == "official_data" and not all(isinstance(v, dict) for v in value.values()):
                    raise ValueError("角色数据应为对象映射")
                if key == "attire_data" and not all(isinstance(v, list) and all(isinstance(t, str) for t in v) for v in value.values()):
                    raise ValueError("服装数据应为标签数组映射")
            except (OSError, ValueError) as exc:
                self.warnings.append(f"无法读取 {key}: {file}: {exc}")
                value = expected()
        self._data[key] = value
        return value

    def attire(self):
        data = self.load("attire_data")
        return {tag for values in data.values() for tag in tokens(values)}

    def characters(self):
        index = {}
        for item in self.load("character_data"):
            key = (normalize(item.get("name", "")), normalize(item.get("copyright", "")))
            if key[0]:
                index[key] = dict(item)
        official = self.load("official_data")
        merged = {}
        for key, value in official.items():
            name, _, copyright = key.partition("||")
            pair = (normalize(name), normalize(copyright))
            merged[pair] = value
            index.setdefault(pair, {"name": name, "copyright": copyright})
        rows = []
        for pair, item in index.items():
            details = merged.get(pair, {})
            tag_list = tokens(details.get("tags"))
            if not tag_list:
                tag_list = tokens(item.get("gender"))
                for field, suffix in (("hair", "hair"), ("eye", "eyes")):
                    if item.get(field):
                        tag_list.append(f"{normalize(item[field])} {suffix}")
            rows.append({
                "character": pair[0].replace(" ", "_"), "copyright": pair[1].replace(" ", "_"),
                "trigger": tokens(details.get("trigger")) or tokens([pair[0], pair[1]]),
                "tags": tokens(tag_list), "index": item,
                "source": "comfyui-anima-tools" if details else "comfyui-anima-tools-index",
            })
        return rows
