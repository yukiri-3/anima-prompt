# AGENTS.md — anima-prompt

本项目是一个 **OpenCode Skill 仓库**。`SKILL.md` 是主要交付物，`scripts/` 是其下层工具。

## 设计原则

- **SFW 模式自包含**：核心规则（决策树/槽位顺序/冲突精简）内联于 SKILL.md，Agent 在 SFW 模式下无需读取任何外部参考文件即可完成 80% 的工作。
- **NSFW 模式分散加载**：NSFW 扩展集中在 `references/nsfw-primer.md`（一个文件），AGent 在 NSFW 模式下额外读此文件即可；需详细配方时按需查 `references/special-themes.md`。
- **references/ 降级参考**：不再是 WORKFLOW 强制读取步骤，而是复杂场景下的按需深度查阅。

## 运行环境

- Python 3.11 (`.python-version`)，包管理用 `uv`（非 pip/poetry）
- 首次使用：`uv venv && uv pip install pyyaml rapidfuzz`
- 所有脚本通过 `uv run scripts/<name>.py` 执行

## 关键命令

| 命令 | 用途 |
|------|------|
| `uv run scripts/anima_lookup.py character "<name>" --json` | 统一角色查询（人工 CSV → Anima Tools → 可选 CSV） |
| `uv run scripts/anima_lookup.py clothing "<tags>" --json` | 服装候选核实；`--search` 搜索标签/配方 |
| `uv run scripts/outfit_swap.py --character "<name>" --clothing "<tags>" --json` | 保留身份，替换衣服，输出角色片段 |
| `uv run scripts/check_prompt.py "<prompt>" [--nsfw]` | 六项校验（人数/冲突/重复/场景/灯光/NSFW）；标签数仅统计，灯光仅报告。默认 SFW；`--nsfw` 允许 NSFW |
| `uv run scripts/check_nsfw.py "<prompt>"` | 独立 NSFW 标签检测 |
| `uv run scripts/warehouse.py add/search/stats` | prompt 仓库管理 |

## 注意事项

- 查询选项放在子命令之后，如 `anima_lookup.py character "初音未来" --json`
- 别名写入通过 `resolve_cn_character.py "<别名>" --set "<已核实 tag>"`，自动生成 `.bak`；在线统一查询不写缓存
- 编辑标签库通过脚本操作，**不要直接写 YAML**
- 无第三方测试框架，无 CI；`uv run scripts/test_anima_lookup.py` 使用标准库和临时数据验证，无需 ComfyUI/网络
- `config.local.yaml` 为忽略提交的本机配置；空路径表示占位，不自动扫描/下载/连接其他电脑
- 每次查询只读 Comfyui-Anima-Tools 数据；身份与衣服分开，来源统计衣服不是默认服装的证明
- `SKILL.md` 是核心交付物，修改前需确认与脚本能力一致
- `docs/` 为归档目录（原始教程留存），不修改其中的文件

## 关键路径

- Skill 本体: `SKILL.md`
- 标签库: `tag-library/`（cn_char_map.yaml、extra_characters.csv；danbooru_character.csv 可选）
- 参考文件: `references/`（核心深度参考、模式扩展、character-clothing.md 数据接入、agent-workflows.md 可选代理集成）
- 脚本工具: `scripts/`（角色/服装查询、换装、回归验证及原有校验/API/仓库工具）
- prompt 仓库: `warehouse/prompts.db` (SQLite FTS5)
