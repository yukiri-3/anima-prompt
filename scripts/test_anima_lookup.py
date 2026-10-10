"""Behavioral regression checks with disposable fixtures; no ComfyUI/network needed."""

import json
import io
import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import anima_lookup as lookup
from anima_tools_source import AnimaToolsSource, ROOT, read_data
from outfit_swap import swap
import resolve_cn_character as resolver
import character_lib as legacy


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugin"
        self.js = self.plugin / "js"
        self.js.mkdir(parents=True)
        self.library = self.root / "tag-library"
        self.library.mkdir()
        (self.library / "extra_characters.csv").write_text("character,copyright,trigger,core_tags\n", encoding="utf-8")
        self.index = [
            {"name": "test girl", "copyright": "test game", "gender": "1girl", "hair": "grey", "eye": "blue"},
            {"name": "test girl (swimsuit)", "copyright": "test game", "gender": "1girl"},
            {"name": "same name", "copyright": "game a"},
            {"name": "same name", "copyright": "game b"},
        ]
        self.official = {"test girl||test game": {"trigger": "test girl, test game", "tags": [
            "1girl", "wolf ears", "wolf tail", "halo", "blue hair", "grey hair", "blue eyes", "red eyes", "medium hair", "long hair", "school uniform", "blue necktie", "scarf", "hair bow", "katana",
        ]}}
        self.attire = {"uniform": ["school uniform", "maid"], "decoration": ["necktie", "scarf", "apron", "maid headdress", "hair bow"], "top": ["dress", "sweater"], "vocabulary": ["school uniform", "maid", "apron", "maid headdress", "dress", "sweater", "pantyhose", "loafers", "penis"]}
        self.write_data()
        self.alias_patch = patch.object(lookup, "load_cache", return_value={"测试角色": "test_girl", "孤立别名": "missing_tag"})
        self.alias_patch.start()
        self.addCleanup(self.alias_patch.stop)
        root_patch = patch.object(lookup, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def write_data(self):
        (self.js / "character_data.js").write_text("const characterData = " + json.dumps(self.index) + ";\nwindow.characterData = characterData;", encoding="utf-8")
        (self.js / "character_official_data.json").write_text(json.dumps(self.official), encoding="utf-8")
        (self.js / "danbooru_attire_data.json").write_text(json.dumps(self.attire), encoding="utf-8")
        (self.js / "clothing_data.js").write_text('const clothingData = [{"name":"Maid","name_zh":"女仆","tags":"maid, apron, imaginary outfit"}]; window.clothingData = clothingData;', encoding="utf-8")

    def source(self):
        return AnimaToolsSource(str(self.plugin))

    def character(self):
        return lookup.lookup_character("测试角色", self.source())["results"][0]

    def test_alias_normalization_exact_beats_variant(self):
        result = lookup.lookup_character("测试角色", self.source())
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["character"], "test_girl")
        self.assertEqual(lookup.lookup_character("ＴＥＳＴ＿ＧＩＲＬ", self.source())["status"], "found")

    def test_ambiguous_is_not_resolved_by_limit(self):
        result = lookup.lookup_character("same name", self.source(), limit=1)
        self.assertEqual((result["status"], result["total"], len(result["results"])), ("ambiguous", 2, 1))
        self.assertEqual(lookup.lookup_character("same name", self.source(), copyright="game b")["status"], "found")

    def test_partial_match_never_selected(self):
        self.assertEqual(lookup.lookup_character("test", self.source())["status"], "candidates")
        self.assertEqual(lookup.lookup_character("long hair", self.source())["status"], "not_found")

    def test_identity_retains_nonhuman_and_removes_competing_colors(self):
        row = self.character()
        self.assertTrue({"wolf ears", "wolf tail", "halo", "grey hair", "blue eyes"} <= set(row["identity"]))
        self.assertNotIn("blue hair", row["identity"])
        self.assertNotIn("red eyes", row["identity"])
        self.assertNotIn("scarf", row["identity"])
        self.assertEqual(row["other_tags"], ["katana"])
        self.assertIn("blue necktie", row["default_outfit"])

    def test_swap_replaces_entire_outfit_and_preserves_index_choice(self):
        result = swap("测试角色", "maid, apron, maid headdress", self.source())
        self.assertEqual(result["status"], "found")
        self.assertTrue({"wolf ears", "wolf tail", "halo", "grey hair"} <= set(result["all_tags"]))
        self.assertFalse({"school uniform", "blue necktie", "scarf", "hair bow", "katana", "blue hair"} & set(result["all_tags"]))
        self.assertTrue({"maid", "apron", "maid headdress"} <= set(result["all_tags"]))

    def test_explicit_identity_override(self):
        result = swap("测试角色", "maid", self.source(), identity="pink hair, green eyes, twintails")
        self.assertTrue({"pink hair", "green eyes", "twintails", "wolf ears", "halo"} <= set(result["identity"]))
        self.assertFalse({"grey hair", "blue hair", "blue eyes", "red eyes"} & set(result["identity"]))
        with self.assertRaises(ValueError):
            swap("测试角色", "maid", self.source(), identity="school uniform")

    def test_heterochromia_and_multicolor(self):
        selected, _ = lookup.select_identity(["heterochromia", "red eyes", "blue eyes", "two-tone hair", "black hair", "white hair"])
        self.assertEqual(len(selected), 6)

    def test_manual_override_works_without_danbooru_csv(self):
        (self.library / "extra_characters.csv").write_text('character,copyright,trigger,core_tags\ntest_girl,test_game,"test girl, test game","1girl, pink hair, green eyes, dress"\n', encoding="utf-8")
        row = self.character()
        self.assertEqual(row["source"], "extra-characters")
        self.assertEqual(row["identity"], ["pink hair", "green eyes"])
        self.assertNotIn("school uniform", row["default_outfit"])

    def test_legacy_csv_entrypoint_preserves_manual_results_without_base_csv(self):
        extra = self.library / "extra_characters.csv"
        extra.write_text('character,copyright,trigger,core_tags\ntest_girl,test_game,test girl,pink hair\n', encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        args = SimpleNamespace(fields=None, keyword="test_girl", limit=2, threshold=95, exact=True, json=True)
        with patch.object(legacy, "EXTRA_PATH", extra), patch.object(legacy, "CSV_PATH", self.library / "missing.csv"), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            legacy.cmd_search(args)
        self.assertEqual(json.loads(output.getvalue())[0]["character"], "test_girl")
        self.assertIn("缺失数据文件", errors.getvalue())

    def test_csv_fallback_and_missing_source(self):
        (self.library / "danbooru_character.csv").write_text('character,copyright,core_tags\nrare_char,rare_game,"1girl, green hair, dress"\n', encoding="utf-8")
        source = AnimaToolsSource(str(self.root / "missing"))
        result = lookup.lookup_character("rare char", source)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["results"][0]["source"], "danbooru-csv")
        self.assertTrue(result["warnings"])
        self.assertEqual(lookup.lookup_character("孤立别名", source)["status"], "alias_only")

    def test_no_network_by_default(self):
        with patch.object(lookup, "api_get", side_effect=AssertionError("network")), patch.object(lookup, "bangumi_candidates", side_effect=AssertionError("network")):
            self.assertEqual(lookup.lookup_character("unknown", self.source())["status"], "not_found")

    def test_exact_primary_skips_large_fallback_csv(self):
        original = lookup.csv_rows
        def read(path):
            if path.name == "danbooru_character.csv":
                raise AssertionError("Should not read fallback for exact primary match")
            return original(path)
        with patch.object(lookup, "csv_rows", side_effect=read):
            self.assertEqual(lookup.lookup_character("test girl", self.source())["status"], "found")

    def test_bangumi_translation_is_rechecked_and_failure_is_structured(self):
        candidate = {"id": 1, "name": "测试角色", "exact": True, "extracted": "Test Girl", "translated_name": "test_girl", "translations": ["Test Girl"]}
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate]), patch.object(lookup, "bangumi_subjects", return_value=[{"name": "テスト -Test Game-"}]):
            result = lookup.lookup_character("未缓存角色", self.source(), bangumi=True)
        self.assertEqual(result["translated_name"], "test_girl")
        self.assertEqual(result["results"][0]["source"], "comfyui-anima-tools")
        with patch.object(lookup, "bangumi_candidates", side_effect=SystemExit(1)):
            with self.assertRaises(ValueError):
                lookup.lookup_character("未缓存角色", self.source(), bangumi=True)

    def setup_kisaki(self):
        self.index += [{"name": "kisaki (blue archive)", "copyright": "blue archive"},
                       {"name": "kisaki (swimsuit) (blue archive)", "copyright": "blue archive"},
                       {"name": "kisaki (other game)", "copyright": "other game"},
                       {"name": "tokisaki (blue archive)", "copyright": "blue archive"}]
        self.write_data()
        return {"id": 124994, "name": "竜華キサキ", "exact": True, "extracted": "Ryuuge Kisaki", "translated_name": "ryuuge_kisaki", "translations": ["Ryuuge Kisaki"]}

    def test_bangumi_full_name_maps_short_tag_using_subject(self):
        candidate = self.setup_kisaki()
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate]), patch.object(lookup, "bangumi_subjects", return_value=[{"name": "ブルーアーカイブ -Blue Archive-"}]), patch.object(resolver, "save_cache", side_effect=AssertionError("must not cache")):
            result = lookup.lookup_character("龙华妃咲", self.source(), bangumi=True)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["results"][0]["character"], "kisaki_(blue_archive)")
        self.assertEqual(result["translated_name"], "ryuuge_kisaki")

    def test_bangumi_name_without_verified_subject_is_not_selected(self):
        candidate = self.setup_kisaki()
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate]), patch.object(lookup, "bangumi_subjects", return_value=[{"name": "Unrelated Game"}]):
            self.assertEqual(lookup.lookup_character("龙华妃咲", self.source(), bangumi=True)["status"], "not_found")

    def test_bangumi_wrong_requested_copyright_is_not_accepted(self):
        candidate = self.setup_kisaki()
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate]), patch.object(lookup, "bangumi_subjects", return_value=[{"name": "Blue Archive"}]):
            self.assertEqual(lookup.lookup_character("龙华妃咲", self.source(), copyright="other game", bangumi=True)["status"], "not_found")

    def test_bangumi_short_query_does_not_pick_first_search_result(self):
        candidate = self.setup_kisaki()
        candidate["exact"] = False
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate]), patch.object(lookup, "bangumi_subjects", side_effect=AssertionError("must not guess character")):
            result = lookup.lookup_character("妃咲", self.source(), bangumi=True)
        self.assertEqual(result["status"], "candidates")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["bangumi_total"], 1)

    def test_bangumi_duplicate_exact_names_stay_ambiguous_with_limit_one(self):
        candidate = self.setup_kisaki()
        with patch.object(lookup, "bangumi_candidates", return_value=[candidate, candidate | {"id": 2}]), patch.object(lookup, "bangumi_subjects", side_effect=AssertionError("ambiguous")):
            result = lookup.lookup_character("龙华妃咲", self.source(), bangumi=True, limit=1)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["bangumi_total"], 2)

    def test_bangumi_native_names_are_checked_before_translation(self):
        rows = [
            {"id": 2, "name": "黒川妃咲", "infobox": [{"key": "别名", "value": [{"k": "罗马字", "v": "Kurokawa Kisaki"}]}]},
            {"id": 1, "name": "竜華キサキ", "infobox": [{"key": "简体中文名", "value": "龙华妃咲"}, {"key": "别名", "value": [{"k": "第二中文名", "v": "龙华妃姬"}, {"k": "罗马字", "v": "Ryuuge Kisaki"}]}]},
        ]
        with patch.object(resolver, "bangumi_search", return_value=rows):
            self.assertEqual(resolver.resolve("龙华妃咲")[2], "ryuuge_kisaki")
            self.assertEqual(resolver.resolve("龙华妃姬")[2], "ryuuge_kisaki")
            self.assertEqual(resolver.resolve("妃咲"), (None, None, None))

    def test_bangumi_matching_uses_name_boundaries_and_preserves_variants(self):
        self.assertEqual(lookup.bangumi_name_score("tokisaki (blue archive)", "blue archive", ["Ryuuge Kisaki"]), 0)
        self.assertEqual(lookup.bangumi_name_score("ryuuge (blue archive)", "blue archive", ["Ryuuge Kisaki"]), 0)
        self.assertEqual(lookup.bangumi_name_score("kisaki (swimsuit) (blue archive)", "blue archive", ["Ryuuge Kisaki"]), 0)
        self.assertFalse(lookup.subject_matches("blue archive", [{"name": "Blue Archiver"}]))

    def test_clothing_validation_does_not_invent_or_accept_recipe_tags(self):
        result = lookup.verify_clothing("maid, maid, black dress, imaginary outfit", self.source())
        self.assertEqual(result["verified"], ["maid"])
        self.assertEqual(result["unverified"], ["black dress", "imaginary outfit"])
        self.assertEqual(swap("测试角色", "maid, imaginary outfit", self.source())["status"], "clothing_unverified")
        recipe = lookup.search_clothing("女仆", self.source())["recipes"][0]
        self.assertEqual(recipe["unverified"], ["imaginary outfit"])

    def test_nsfw_mode_is_explicit(self):
        self.assertEqual(lookup.verify_clothing("penis", self.source())["blocked"], ["penis"])
        self.assertEqual(lookup.verify_clothing("penis", self.source(), nsfw=True)["verified"], ["penis"])

    def test_malformed_js_is_never_executed_and_index_fallback_survives(self):
        (self.js / "clothing_data.js").write_text('const clothingData = [{name: process.exit()}];', encoding="utf-8")
        source = self.source()
        self.assertEqual(source.load("clothing_data"), [])
        self.assertTrue(source.warnings)
        (self.js / "character_official_data.json").write_text("[]", encoding="utf-8")
        row = lookup.lookup_character("test girl", self.source())["results"][0]
        self.assertEqual(row["source"], "comfyui-anima-tools-index")
        self.assertIn("grey hair", row["identity"])

    def test_configuration_relative_path_and_refresh(self):
        config = self.root / "config.yaml"
        config.write_text("anima_tools:\n  path: plugin\n", encoding="utf-8")
        with patch.dict(os.environ, {"ANIMA_TOOLS_PATH": ""}):
            self.assertEqual(AnimaToolsSource(config=str(config)).path, self.plugin)
        self.official["test girl||test game"]["tags"] = ["1girl", "pink hair"]
        self.write_data()
        self.assertEqual(self.character()["identity"], ["pink hair"])

    def test_online_sample_is_marked_as_inference(self):
        posts = [{"rating": "g", "tag_string_character": "rare_char", "tag_string_copyright": "rare_game", "tag_string_general": "1girl green_hair halo school_uniform standing"} for _ in range(3)]
        with patch.object(lookup, "api_get", side_effect=[[{"name": "rare_char", "category": 4}], posts]), patch.object(lookup.time, "sleep"):
            row = lookup.lookup_character("rare_char", self.source(), online=True)["results"][0]
        self.assertEqual(row["sample_count"], 3)
        self.assertEqual(row["source"], "danbooru-online-sample")
        self.assertNotIn("standing", row["all_tags"])

    def test_alias_writer_backs_up(self):
        cache_file = self.root / "aliases.yaml"
        cache_file.write_text("旧别名: old_tag\n", encoding="utf-8")
        with patch.object(resolver, "CACHE_PATH", cache_file):
            resolver.save_cache({"新别名": "new_tag"})
        self.assertEqual(cache_file.with_suffix(".yaml.bak").read_text(encoding="utf-8"), "旧别名: old_tag\n")

    def test_cli_json_and_exit_status_from_other_cwd(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/anima_lookup.py"), "character", "test girl", "--anima-tools", str(self.plugin), "--json"], cwd=self.root, capture_output=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "found")
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/outfit_swap.py"), "--character", "test girl", "--clothing", "imaginary outfit", "--anima-tools", str(self.plugin), "--json"], cwd=self.root, capture_output=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertNotIn("prompt", json.loads(proc.stdout))


if __name__ == "__main__":
    unittest.main(verbosity=2)
