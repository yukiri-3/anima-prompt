# 可选代理集成

仅在已有 OpenCode/Hermes 代理环境、用户要求代理集成时查阅。普通生成无需加载。
示例中的 Skill 路径、并发数应按实际环境填写；模板命令不能证明外部环境已安装。

## OPENCODE SUBAGENTS（可选安装）

将 外部 `agents/` 模板（本仓库未附带；仅在已有这些文件时）复制到 `.opencode/agents/` 即可注册为 OpenCode subagent：

```bash
cp agents/anima-engineer.md .opencode/agents/
cp agents/anima-checker.md .opencode/agents/
```

之后可在 OpenCode 中通过 `@anima-engineer` 调用端到端生成、通过 `@anima-checker` 调用仅校验。

## HERMES SUBAGENTS

Hermes Agent 通过 `delegate_task` 调用本技能的三个子代理，覆盖完整链路：
**Builder（生成 prompt）→ Checker（校验）→ Drawer（调用 API 出图）**。

### anima-prompt-builder — 生成 prompt

**触发条件**：用户要求"生成 prompt / 写提示词 / Anima 出图描述 / 标签转写"

| delegate_task 参数 | 值 |
|---|---|
| `goal` | Generate a one-line Anima3 prompt from a Chinese scene description |
| `role` | leaf |

**context 模板**（`{NSFW_FLAG}` 和 `{USER_INPUT}` 由主代理填充）：

> Skill directory: `C:\Users\ros\AppData\Local\hermes\skills\creative\anima-prompt`
> All relative paths are from that directory. Run scripts with `uv run scripts/xxx.py`.
>
> NSFW mode: {NSFW_FLAG}
>
> ## USER'S SCENE DESCRIPTION
> {USER_INPUT}
>
> ## WORKFLOW
> 1. Load skill 'anima-prompt' via skill_view
> 2. Use the inline SFW decision tree in SKILL.md; load references/nsfw-primer.md only in NSFW mode
> 3. Use the inline slot order and conflict rules in SKILL.md
> 4. Generate by the inline slot order; verify clothing candidates with anima_lookup.py clothing
> 5. For a named character: `uv run scripts/anima_lookup.py character "(name)" --json`. Require a unique exact match. Place trigger in identity, identity in appearance, and default_outfit in clothing only when the user has not specified clothing. For a swap, verify new clothing and omit all default_outfit/other_tags. User appearance overrides take precedence.
> 6. For special themes (NTR/BDSM/etc): read references/nsfw-primer.md; detailed recipes in references/special-themes.md only as needed
> 7. Assemble: all lowercase, tags joined with ", ", **one line**. Multi-character: use BREAK
> 8. Validate: `uv run scripts/check_prompt.py "(prompt)" [--nsfw]`
> 9. Fix validation failures → re-validate until `passed: true`
> 10. If user says "保存": `uv run scripts/warehouse.py add "(desc)" "(prompt)" --type (type)`
>
> ## OUTPUT CONSTRAINT
> **CRITICAL: After validation passes, output ONLY the prompt line.**
> ENTIRE response = **ONE LINE** of plain text — the prompt only.
> NO "All checks passed", NO status messages, NO explanations.
> No greetings. No markdown. No code fences.

**⚠️ Pitfalls:**

- **Generic-catgirl syndrome**: 用户描述了具体角色（如「迷迭香」「初音未来」）但没有在 prompt 里显式写角色名 → 子代理跳过 step 6 → 出图变成随机角色。**主代理必须检查用户输入是否包含角色名，若有则显式填入 `{USER_INPUT}` 提醒子代理执行角色解析**，不得依赖子代理自行判断。
- **NSFW 标签检测**: `check_nsfw.py` 的 JSON 输出会列出具体命中的标签名。SFW 场景下若被误杀，用同义安全标签替换或用自然语言短句替代。
- **路径断裂**: skill directory 含反斜杠长路径时可能出现换行断裂。主代理填入 context 时使用正斜杠格式 `C:/Users/ros/...`。

### anima-checker — 校验 prompt

**触发条件**：用户要求"检查 prompt / 校验标签 / 有没有冲突"

| delegate_task 参数 | 值 |
|---|---|
| `goal` | Validate an existing Anima prompt and return the check report |
| `role` | leaf |

**context 模板**：

> Skill directory: `C:\Users\ros\AppData\Local\hermes\skills\creative\anima-prompt`
> NSFW mode: {NSFW_FLAG}
>
> ## PROMPT TO VALIDATE
> {USER_PROMPT}
>
> ## STEPS
> 1. Load skill 'anima-prompt' via skill_view
> 2. Run: `uv run scripts/check_prompt.py "(prompt)" [--nsfw]`
> 3. Return JSON report. If passed=false, explain which checks failed.
>
> Do **NOT** generate new prompts. Do NOT modify anything.

### anima-drawer — 调用 API 出图

**触发条件**：用户要求"画出来 / 生图 / 出图 / 调用 Anima"

| delegate_task 参数 | 值 |
|---|---|
| `goal` | Send a prompt to the Anima API and download the generated image |
| `role` | leaf |

**前置条件**：Anima API (ComfyUI) 必须在 `--api-url` 指定的地址上运行。默认 `http://localhost:8188`。

**context 模板**：

> Skill directory: `C:\Users\ros\AppData\Local\hermes\skills\creative\anima-prompt`
>
> ## PARAMETERS
> - Prompt: {PROMPT}
> - Ratio: {RATIO} (1:1 \| 16:9 \| 9:16 \| 4:3 \| 3:4 \| 3:2 \| 2:3 \| 5:4 \| 4:5)
> - API URL: {API_URL} (default: http://localhost:8188)
> - Workflow: {WORKFLOW_PATH} (default: workflows/t2i/AnimaApi.json)
> - Output dir: {OUTPUT_DIR} (default: `./outputs` under skill directory)
>
> ## STEPS
> 1. Check API reachable: `curl -s -o /dev/null -w "%{http_code}" {API_URL}` — if unreachable, report error immediately
> 2. Run: `uv run scripts/call_anima.py -p "(prompt)" --ratio {RATIO} --api-url {API_URL} -w "(workflow)" -o "(output)"`
> 3. If success: return the absolute path of the saved image
> 4. If timeout/failure: report error clearly, do **NOT** retry
>
> ## FALLBACK
> If API not reachable: report `Anima API 未就绪 (checked {API_URL}) — 请确认 ComfyUI 已启动且 AnimaApi workflow 已加载`

**⚠️ Custom workflow 陷阱**：Drawer 调用的 `call_anima.py` 依赖 workflow JSON 内存在 `__PROMPT__` 字符串。如果自定义 workflow 里 prompt 是硬编码的（如 `PrimitiveStringMultiline.value = "1girl, solo, ..."`），脚本会报错退出。**主代理必须在 context 里检查 workflow 类型**：如果是非默认 workflow，加上一步「先确认 workflow 内有 `__PROMPT__` 占位，没有则报错并提示用户修改」。

### 组合调用链

最常见模式 — Builder → Drawer 串联：

```
用户: "画一个金发女仆在教室里的图"
  → Builder (生成 prompt)  → 返回一行 prompt
  → Drawer (prompt=上一步结果, ratio=1:1) → 返回图片绝对路径
```

如需 NSFW，Builder 和 Checker 的 `{NSFW_FLAG}` 由主代理根据用户输入判断后填入。

### 批量多场景

用户要求「多看看各种姿势」时，应并行生成多个场景：

```
用户: "画的图可以有多张姿势的插图吗？"
  ┌─────────────────────────────────┐
  │  step 1: 批次 Builder（并行）    │  max_concurrent_children=3
  ├─────────────────────────────────┤
  │  Builder A (倚窗看夕阳)          │
  │  Builder B (沙发上午睡)          │
  │  Builder C (坐地毯看书)          │  ← 第一批 3 个
  └─────────────────────────────────┘
           ↓ 等待全部完成
  ┌─────────────────────────────────┐
  │  Builder D (跪坐喝抹茶)          │  ← 第二批 1 个（因上限 3）
  └─────────────────────────────────┘
           ↓ 集齐所有 prompt
  ┌─────────────────────────────────┐
  │  step 2: 批次 Drawer（并行）     │  每张图独立 drawer subagent
  └─────────────────────────────────┘
           ↓
  [图片1][图片2][图片3][图片4]
```

注意事项：
- `delegate_task` 的 `tasks` 数组上限为 `max_concurrent_children`（当前 3）。超过需分批次调用。
- Builder 的 `context` 中角色名必须显式写入用户描述（如 `{USER_INPUT}` 中含 `迷迭香`），避免 subagent 漏过专名解析。
- Drawer 可在第一批 Builder 完成后立即启动（无需等第二批），缩短总耗时。

---
