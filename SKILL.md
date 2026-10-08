---
name: anima-prompt
description: >
  将中文场景描述转写为 Anima 模型的英文标签 prompt，查询已有角色的身份/服装标签、
  验证服装候选、角色换装、校验 prompt 或调用已有 ComfyUI workflow 出图时使用。
  不用于其他模型的通用 prompt 或 ComfyUI 安装配置。
metadata:
  runtime: Python 3.11, uv, pyyaml, rapidfuzz
---

# Anima Prompt Engineer

将用户描述组装为 Anima 英文 prompt。已有角色优先查真实来源，明确分开身份特征和服装。

## 运行与数据

所有命令在 Skill 根目录执行：`uv run scripts/<name>.py`。依赖由 `pyproject.toml`/uv 管理。
首次安装可执行 `uv venv && uv pip install pyyaml`。

角色/服装主要读取已安装的 Comfyui-Anima-Tools，不复制数据库。
复制 `config.example.yaml` 为 `config.local.yaml` 并填写 `anima_tools.path`；空路径可保持占位。
也可在查询命令中加 `--anima-tools "<插件根目录>"`，或设置 `ANIMA_TOOLS_PATH`。
配置、字段与在线回退的细节按需查 [角色服装接入](references/character-clothing.md)。
可选 `tag-library/danbooru_character.csv` 是冷门角色回退，不是启动必需项。
`extra_characters.csv` 人工覆盖优先，中文/日文别名复用 `cn_char_map.yaml`；不直接编辑标签库 YAML。

## 输出与模式

- 默认 SFW。仅用户明确包含 `--nsfw`、`NSFW`、`R18` 或 `r18` 时切换 NSFW，额外读
  [NSFW 扩展](references/nsfw-primer.md)。详细特殊主题再按需读 [配方](references/special-themes.md)。
- **生成 prompt**：只输出一行纯文本，标签以 `, ` 分隔，无解释、Markdown 或权重语法。
  标签 lowercase，多人分隔符保留 `BREAK`。不加质量词、画师名；自然语言短句放末尾。
- **查询/校验请求**：返回查询结果、来源、歧义或未收录项；不能因为一行 prompt 规则而沉默。
  数据缺失或角色有歧义时说明阻塞点，不能编造标准角色/服装 tags。
- **出图请求**：先生成并校验 prompt，再调用已配置 API，返回图像结果或错误。

## 核心工作流（SFW 自包含）

### 1. 判定场景

| 用户需求 | 处理 |
|---|---|
| 单人展示/日常 | 外观、衣服、一个主要动作、表情、镜头、环境 |
| 运动/动作 | 一个主要动作 + 必要姿态细节；避免同时静坐、奔跑等矛盾 |
| 双人/多人互动 | 总人数 + 共享互动；每人有独立外观/衣服/动作/表情 block |
| 分镜/对比 | 明确分区关系，末尾用短英文句说明；不把互斥时态混为同一角色状态 |
| NSFW 明确模式 | 加载 nsfw-primer，再按相应类型处理；沿用角色身份/服装拆分 |

### 1a. 角色解析

用户包含角色专名时执行（只给作品名时先查候选，不擅自指定某个角色）：

```bash
uv run scripts/anima_lookup.py character "<角色名>" --json
```

- 只有 `status=found` 才是唯一精确匹配；`ambiguous`/`candidates` 需核对作品和完整名称后重查。
  可加 `--copyright "<作品名>"`。不要自动选候选第一条，也不要拿示例中的名字猜 canonical tag。
- `trigger` 放 count/identity，`identity` 放 appearance；`gender` 按实际人数统一组装。
- `default_outfit` 仅在用户没有指定衣服时选用；来源统计标签不等于官方默认服装。
- 用户明确发色、瞳色、发型等覆盖来源候选；每种竞争属性选一个，多色/异色瞳按实际语义保留。
- `all_tags` 仅供参考，不能整包复制。`other_tags` 不自动加到新衣服中。
- `alias_only` 只提供本地别名 trigger，其他从用户描述补充；没有数据时不编造外观和出处。
- 默认离线；有需要时显式 `--bangumi` 翻译、`--online` Danbooru 最后回退。

### 1b. 服装解析与换装

Agent 把中文衣服理解成英文候选 tags，再核实：

```bash
uv run scripts/anima_lookup.py clothing "<tag1>, <tag2>" --json
uv run scripts/anima_lookup.py clothing "<关键词>" --search --json
uv run scripts/outfit_swap.py --character "<角色名>" --clothing "<服装 tags>" --json
```

- `verified` 是本地 attire 词表已收录项；`unverified` 不是已验证标签，也不一定错误。
  未收录的剪裁/颜色细节可按用户原意写短英文描述，不能偷偷当 canonical tag。
- `--search` 中的配方独立标明已收录与未收录项，不整包视为 Danbooru 词表。
- **用户指定新衣服 → 删除全部来源默认服装与制服细节 → 保留身份 → 加新衣服**。
  不把旧制服、帽子、领带叠进女仆装；天然兽耳、尾巴、角、halo、翅膀保留。
- `outfit_swap.py` 输出角色片段；必须全部新衣服通过词表核实才输出。
  可加 `--identity "pink hair, green eyes"` 覆盖外观，然后继续槽位组装。
- NSFW 模式下 clothing/outfit_swap 也显式加 `--nsfw`；最终仍运行总校验。

### 2. 按槽位组装

**单人**：`count/identity → appearance → clothing → pose/action → expression → camera → scene → detail/mood → natural language`。

| 槽位 | 核心规则 |
|---|---|
| count/identity | 人数只写一次，单人女性可用 `1girl, solo`；角色+作品 trigger 显式保留 |
| appearance | 先种族/标志特征，再发色/发长/发型，再眼睛；至少保留 3 个可区分锚点（有来源时） |
| clothing | 上衣→下装→袜→鞋→配饰；服装特征与身份特征分开 |
| pose/action | 一个主要动作，手臂/手指的辅助动作与它兼容 |
| expression | 简洁、与动作情绪一致；不同时写 open mouth 与 closed mouth |
| camera | 选一个主视角、一个景别；禁止上下视角、正背视角或近景全身并存 |
| scene | 地点→物体→时间/天气；衣服与环境风格一致，除非用户要求反差 |
| detail/mood | 少量氛围或相容光影，不重复堆叠同部位细节 |
| natural language | 仅补标签无法精确表达的空间、动作关系或衣服细节，放末尾 |

**多人**：`总人数 → 共享互动 → [A: trigger → appearance → clothing → solo-action → expression], BREAK, [B: ...] → camera → scene → detail/mood → natural language`。
总人数按用户要求汇总，不把每条来源的 `1girl` 再贴入角色 block；角色 trigger 各在自己的 block。

### 3. 冲突精简

输出前去重，优先保留用户明确要求，删除相冲突的来源默认项：

- `from front`/`from behind`、`from above`/`from below`、`close-up`/`full body` 二选一。
- `looking at viewer` 不与 `facing away`、`sleeping`、`unconscious` 并存。
- `blindfold` 不与可见眼部细节或 `glasses` 并存。
- `open mouth`/`closed mouth`、`spread legs`/`legs together`、张指/握拳二选一。
- `pantyhose` 不与 `barefoot` 并存，除非明确脚部破损并人工核对脚本报告。
- 全裸不保留具体衣服；用户换装不保留旧制服。
- `day`/`night`、室内/室外、水下/明火等保持物理兼容；同一部位少量必要细节。
- `solo` 不与多人或共享互动标签并存。现有 count 检查器会拒绝 `solo, 1boy`，男性单人暂只写 `1boy`。

### 4. 校验并输出

```bash
uv run scripts/check_prompt.py "<最终 prompt>" [--nsfw]
```

修正报告中失败的项目后再校验。脚本实际检查 **6 项**：NSFW、人数、互斥、重复、场景、光影。
`tag_count` 仅统计，光影仅报告；脚本不验证全球 Danbooru 存在性，也不自动处理所有发色冲突。
不要声称第七项标签数检查已执行。校验通过后，按上面的输出规则交付。

## 保存和出图

用户要求保存时：

```bash
uv run scripts/warehouse.py add "<描述>" "<prompt>" --type "<场景>"
uv run scripts/warehouse.py search "<关键词>"
```

用户要求生图时：

```bash
uv run scripts/call_anima.py -p "<prompt>" --ratio 3:4 --api-url "http://localhost:8188"
```

可选 `-w "<workflow.json>"`、`-o "<输出目录>"`。默认 workflow 为 `workflows/t2i/AnimaApi.json`。
比例支持 1:1、16:9、9:16、4:3、3:4、3:2、2:3、5:4、4:5。
自定义 workflow 必须含 `__PROMPT__`，且恰有一个可修改宽高的 `EmptyLatentImage`；未满足则报告错误。
本 Skill 不因查角色/服装而自动生图。

## 按需参考

- 复杂服装细节、表情、构图和风格：[深度规则](references/reference.md)。
- 配置、来源字段、在线统计及故障：[角色服装接入](references/character-clothing.md)。
- NSFW 模式：[NSFW primer](references/nsfw-primer.md)；详细配方：[特殊主题](references/special-themes.md)。
- 表情符号：[表情参考](references/emoticon-reference.md)；完整组装：[例子](references/example.md)。
- 用户需要已有 OpenCode/Hermes 代理集成时：[代理工作流](references/agent-workflows.md)。
