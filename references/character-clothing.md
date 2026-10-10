# 角色与服装数据接入

仅在配置数据源、排查缺失/歧义、使用在线回退或需要查询字段详情时读本文件。
普通生成规则和查询命令已在 SKILL.md 内联。

## 配置

复制 `config.example.yaml` 为 `config.local.yaml`，填写插件根目录（不是 ComfyUI 根目录）：

```yaml
anima_tools:
  path: "D:/ComfyUI/custom_nodes/Comfyui-Anima-Tools"
  character_data: js/character_data.js
  official_data: js/character_official_data.json
  attire_data: js/danbooru_attire_data.json
  clothing_data: js/clothing_data.js
```

空路径代表尚未接入，不会扫描磁盘、下载数据库或连接 ComfyUI。
`config.local.yaml` 已被 Git 忽略。相对插件路径基于配置文件所在目录解析。
路径优先级：命令的 `--anima-tools` > 环境变量 `ANIMA_TOOLS_PATH` > 配置。
所有选项写在子命令后；任意工作目录运行脚本时，默认配置和 CSV 仍定位于 Skill 根目录。

数据按每次命令读取，仅在本次进程内缓存。上游更新后下次执行即生效。
JS 只解析 `const/let/var characterData = [...]` 与 `clothingData = [...]` 中的 JSON 数组，绝不执行 JS。
若上游改成非 JSON 的 JS 语法或改变字段结构，会报告读取警告并尝试剩余来源。

已对照的上游格式：[nregret/Comfyui-Anima-Tools](https://github.com/nregret/Comfyui-Anima-Tools)。
这里的适配规则不保证所有 fork 的数据格式都相同。

## 查询与优先级

```bash
uv run scripts/anima_lookup.py character "初音未来" --json
uv run scripts/anima_lookup.py character "shiroko (blue archive)" --copyright "blue archive" --json
uv run scripts/anima_lookup.py character "miku" --limit 5 --json
uv run scripts/anima_lookup.py clothing "sweater, pleated skirt, pantyhose, loafers" --json
uv run scripts/anima_lookup.py clothing "女仆" --search --json
uv run scripts/outfit_swap.py --character "初音未来" --clothing "maid, apron, maid headdress" --json
```

中/日文别名复用 `tag-library/cn_char_map.yaml`，查询只读。
先用上游名称核实匹配，再通过现有脚本补录；不要直接写标签库 YAML：

```bash
uv run scripts/resolve_cn_character.py "砂狼白子" --set "shiroko_(blue_archive)" --json
```

这条映射针对上述上游数据中实际存在的名称；不要把对话中的示意名字当作已核实 tag。
写入操作备份原文件为 `.yaml.bak`。

角色精确匹配使用 `extra_characters.csv` > 官方 JSON（以 `name||copyright` 为键）
> 角色 JS 索引 > 可选 `danbooru_character.csv`。每个角色/作品组合只返回最高优先级来源。
手工 CSV 是完整记录覆盖，不会混入官方 JSON 的衣服。大小写、全角字符、下划线/空格统一匹配。
匹配角色名时不使用外观字段，以免因为“长发”错误命中角色。

角色查询状态：

| status | 处理方式 |
|---|---|
| found | 唯一精确匹配，可使用 results[0] |
| ambiguous | 多个同名角色；根据作品消歧，不自动选第一个 |
| candidates | 只有部分名称/作品命中；核对完整名字后重查 |
| alias_only | 仅有本地别名；只核实了 trigger，缺失资料继续后续来源查询 |
| not_found | 无可验证记录，不能编造角色 trigger/默认服装 |
| error | 配置/网络等错误，查看 error 字段 |

`--limit` 只截断显示，不改变歧义判定；`total` 给出完整候选数量。

返回的角色字段：

- `trigger`：角色名与作品标签，放 identity/count 槽位；`gender` 单独提供人数候选。
- `identity`：已去重并精简的外观；`identity_candidates` 保留原始外观候选；
  `alternatives` 记录竞争的发色、瞳色、发长、发型、体型。
- `default_outfit`：从来源 tags 中识别的可穿戴标签，**并不证明是官方默认服装**。
- `other_tags`：道具或无法可靠分类的标签，不自动用于换装。
- `all_tags`：参考集合，不能直接当成最终 prompt；用户描述仍有最高优先级。

上游官方数据也可能混合不同同人图的外观和服装（例如普通白子记录含泳装），
所以有用户衣服描述时必须舍弃 `default_outfit`；无描述时也要核对明显异常。
竞争颜色优先选 JS 索引中已出现的候选，否则用来源中的第一个；发长/发型/体型各保留一个。
明确的异色瞳、多色头发保留相应多色候选，不随机挑选颜色。

## 服装校验与换装

`clothing` 接受逗号分隔的英文候选 tags。中文由 Agent 转候选，`--search` 还可搜配方的中文名称。
`verified` 仅表示标签确实存在于本地 attire 的分类数组/`vocabulary`，不是全球 Danbooru 完整验证。
`unverified` 表示未收录，不意味着错误；`suggestions` 只是字面搜索结果，不自动替换。
`blocked` 使用现有 `check_nsfw.py` 的关键词表，`--nsfw` 明确放行。
此表是既有检测能力，不能保证所有上游配方都适合 SFW，配方仍须按用户模式筛选。

`--search` 返回 `tags` 和 `recipes`。`clothing_data.js` 是策划配方源，里面的所有 tags
不能直接视为已核实；每个配方都附带自己的 `verified` / `unverified`。
找不到服装库时返回 `unavailable`，不会用配方数据冒充 Danbooru 服装词表。

`outfit_swap.py` 要求唯一精确角色及全部已收录的新服装；未知衣服会返回
`clothing_unverified`，不会输出一条看似完成、实际缺衣服的 prompt。
先重新查询候选或由 Agent 用英文自然语言补充未收录细节，然后继续正常槽位工作流。

```bash
uv run scripts/outfit_swap.py --character "初音未来" \
  --clothing "maid, apron, maid headdress" --identity "pink hair, green eyes" --json
```

`--identity` 只接受外观覆盖，竞争的旧颜色/发型等会被移除。
输出 `removed_default_outfit`、`omitted_other_tags` 和换装后的 `prompt` **角色片段**。
片段不包含场景/动作/镜头；多人时不要逐人复制 gender 到总人数槽位。
继续组装最终 prompt 并执行 `check_prompt.py`。

## 在线回退与 Agent 查询顺序

Skill 要求 Agent 在未确定角色时依次查询：**本地 → Bangumi → Danbooru → 通用网络搜索**。
任一步已核实唯一角色且数据足够即可停止；用户要求离线时不执行在线步骤。
脚本本身默认离线，统一查询无写库副作用；Agent 在对应步骤显式加参数：

```bash
uv run scripts/anima_lookup.py character "冷门中文名" --json
uv run scripts/anima_lookup.py character "冷门中文名" --bangumi --json
uv run scripts/anima_lookup.py character "known_character_tag" --online --json
```

有已核实的英文作品名时，各步都可加 `--copyright "<作品名>"`；中文作品名不由此参数自动翻译。
Bangumi 的名称候选尚未确定时，先用用户提供的作品核对候选关联作品和完整姓名，不按排名选择。
第三步用已核实的名称候选查询 Danbooru 的角色 tag、作品 tag 和 wiki；没有精确 tag 候选时，
Agent 使用搜索/浏览工具直接查 Danbooru，因为 `--online` 不提供模糊姓名搜索或 wiki 查询。

同时传入 `--bangumi --online` 时，只有 Bangumi 精确角色具备罗马字且本地匹配失败，
才会尝试该罗马字的 Danbooru 精确 tag。其他提前返回的候选/失败状态需要 Agent 继续第三步，
不能把一次组合命令当成完整回退流程。

Danbooru 仍无法解决时，Agent 再以“作品名 + 角色名”和已知日文/英文别名进行通用网络搜索。
优先官方角色页和设定资料，必要时参考可靠角色资料页；分别核对身份、外观与服装/版本，记录来源链接。
新找到的 tag 需返回 Danbooru 核实；网页中的外观文字不是标签存在的证明，未核实细节用英文自然语言表达。
仍无法确定角色时报告歧义或缺失信息，不编造 trigger/默认服装；请求失败记录原因后继续下一来源，
没有搜索/浏览工具时说明限制。通用搜索是 Agent 工作流，不是 `anima_lookup.py` 的脚本功能。

`--bangumi` 先按 Bangumi 名称、中文名和别名查找唯一完整名称匹配，不按搜索排名选第一个。
没有精确名称或出现多个同名角色时，返回 `bangumi_candidates` / `bangumi_total`，
需要完整姓名或核实后补录别名；显示 `--limit 1` 也不会把歧义变成匹配成功。

唯一完整名称匹配后读取该角色的关联作品，再以罗马字/英文名与作品同时匹配本地标签。
关联作品中的完整英文词组可与本地作品名匹配，包括混合日文/英文标题；
本地角色可以使用完整罗马字、姓名词序差异或罗马字的末尾名字，匹配必须保持词边界。
只去掉与作品一致的括号后缀，保留泳装等版本限定，不拿普通角色冒充指定版本。
不含可核实英文作品名、多个候选或仍无名称对应时，不自动认定为 `found`。

例如 `龙华妃咲` → Bangumi `竜華キサキ` / `Ryuuge Kisaki` → 关联作品 `Blue Archive`
→ 本地 `kisaki_(blue_archive)`。结果仍保留 `translated_name=ryuuge_kisaki`，
用 `bangumi` 提供角色 ID/名称及关联作品，用 `match_basis` 说明匹配依据。
这是一般名称/作品匹配，不包含针对这个角色的硬编码别名。

统一入口不写别名缓存。独立 `resolve_cn_character.py --bangumi` 也只选唯一完整名称，
但保留自动备份并写缓存的行为；保存的是罗马字候选，不保证等于 Danbooru canonical tag。
已核实本地标准名称时，仍可使用 `--set` 保存映射，后续直接离线查询。

`--online` 仅在本地没有唯一精确记录时调用 Danbooru：精确核实 category=4 角色 tag，
最多取 20 张 general 评级、solo、仅此角色的图片；过滤 alternate_costume/cosplay/parody/
crossover/genderswap/chibi，再取出现比例至少 60% 的身份/服装 tags。
`source=danbooru-online-sample` 和 `sample_count` 标明统计来源。结果是推断，不是官方设定。
服装分类仍依赖本地 attire 词表/服装名称特征；没有样本时只返回已核实的角色 trigger。
Bangumi 搜索及关联作品请求各设 10 秒超时，Danbooru 请求设 15 秒超时；
错误报告一次，不无限重试，不自动下载 CSV。

## 验证

```bash
uv run scripts/test_anima_lookup.py
```

测试使用临时数据和网络响应样例，不需要 ComfyUI 或另一台电脑。
将配置迁移到实际安装电脑后，再执行上面的角色/服装/换装查询验证本机版本适配。
