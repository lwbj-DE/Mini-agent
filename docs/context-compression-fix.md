# 上下文压缩信息丢失问题：根因分析与修复

## 目录

1. [问题背景](#1-问题背景)
2. [复现步骤](#2-复现步骤)
3. [根因分析](#3-根因分析)
4. [修复方案](#4-修复方案)
5. [代码改动详解](#5-代码改动详解)
6. [验证方法](#6-验证方法)
7. [涉及的边界情况](#7-涉及的边界情况)

---

## 1. 问题背景

### 1.1 什么是上下文压缩

大语言模型（LLM）一次能处理的文字数量是有限的，这个限制叫**上下文窗口**（context window）。比如 MiMo v2.5-pro 的上下文窗口是 32768 个 token（约 2-3 万汉字）。

当用户和 AI 聊天越来越长，所有历史消息的总字数迟早会超过这个上限。**上下文压缩**（context compression）就是在超过上限之前，把早期的对话"浓缩"成一段摘要，用摘要代替原文，腾出空间给后续对话。

### 1.2 这个问题是怎么被发现的

我们做了一个测试：

1. 在聊天开始时，告诉 AI 一段详细的背景信息（包含人名、项目名、技术选型、数字指标、个人偏好等）
2. 连续聊 3 个长话题，触发 3 次上下文压缩
3. 用模糊的提示去问 AI："之前提到有个同事，在数据库选型上有自己的想法，你还记得什么吗？"

AI 回答：**"这是我们第一次对话，我不知道。"**

即使把提示加强到明确写出项目名"Nightingale"，AI 仍然说不知道。这意味着经过 3 次压缩后，早期的对话信息**完全丢失了**。

---

## 2. 复现步骤

### 2.1 环境准备

为了加快复现速度，先将压缩阈值调低（`.env`）：

```bash
compression_trigger_fraction=0.25   # 只要 token 使用量达到模型上限的 25% 就触发压缩
compression_keep_messages=8         # 压缩后只保留最近 8 条消息
model_max_input_tokens=8192         # 降低上下文窗口上限
```

这样压缩触发点 = 8192 × 0.25 ≈ 2048 tokens，大约 2000-3000 个中文字符就触发一次。

### 2.2 测试流程

**第 1 步：植入信息**

用 Plan-Execute 模式发送一条包含丰富背景信息的消息：

```
我在跟一个项目叫「夜莺计划」（Nightingale），
后端负责人是张明远，他之前在阿里做中间件，2023 年跳过来的。
技术栈选了 Rust + Tokio 做后端，数据库用的 CockroachDB
（他说 PostgreSQL 分区表太麻烦），前端用 Leptos 这个 Rust 的 Wasm 框架，
部署在 AWS ECS 上。现在最大问题是冷启动要 4 秒，客户要求 500ms 以内。
我们上周试了 Firecracker microVM，延迟反而涨了。
张明远喜欢手冲咖啡，工位上摆了整套 V60 器具。
先帮我制定一个了解 Rust 异步编程的计划。
```

**第 2 步：填充对话，触发 3 次压缩**

连续发送 3 条长回答的请求（每条等 AI 回复完再发下一条）：

1. "详细对比一下 CockroachDB 和 PostgreSQL 的区别……"
2. "帮我写一份 AWS ECS 的部署最佳实践……"
3. "给我推荐 5 本关于系统设计的书……"

观察后端终端日志，确认出现 3 次 `触发压缩: N 条 → 摘要`。

**第 3 步：递进式验证**

用 4 个层级的提示测试，从最模糊到最明确：

| 层级 | 提示语 | 期望回忆的点 |
|------|--------|-------------|
| L1 | 之前提到有个做后端的同事对数据库选型有自己的想法，你还记得他为什么不选 PostgreSQL 吗？ | 张明远、CockroachDB、"分区表太麻烦" |
| L2 | 我们团队在搞冷启动优化，上次试了一个方案效果不好反而更慢了，你觉得问题出在哪？ | 4 秒→500ms、Firecracker 试过不行 |
| L3 | 帮我理一下 Nightingale 现在的技术栈全貌和当前的卡点 | Rust+Tokio, Leptos, ECS, 冷启动问题 |
| L4 | 我想给那个喜欢咖啡的同事挑个礼物，你有什么建议？ | 张明远、V60 手冲 |

### 2.3 复现结果

修复前：L1-L4 全部失败。所有回答都类似"这是我们第一次对话，我不知道"——即使 L3 明确提到了"Nightingale"。

---

## 3. 根因分析

修复前，压缩逻辑在 `backend/agent_modes/react_mode.py` 的 `_maybe_compress` 方法和 `_generate_summary` 方法。三个问题叠加导致了信息丢失。

### 3.1 问题一：摘要覆盖，而非累积

**这是最致命的问题。**

原始代码（已删除）的核心逻辑：

```python
# 第 214-217 行（修复前）
summary = self._generate_summary(to_compress)
session.messages = [
    {"role": "system", "content": f"[对话摘要] {summary}"}
] + recent
```

它做了一件事：用**一行摘要**替换掉**所有被压缩的消息**。

让我们追踪 3 次压缩的全过程：

```
初始状态:
  [user: "夜莺计划...张明远...CockroachDB...V60咖啡..." (300字)]
  [assistant: "好的，我帮你制定计划..." (1500字)]
  [user: "继续..." ...]
  [assistant: ...]
  ...共 40 条消息...

═══════════════ 第 1 次压缩 ═══════════════
LLM 收到:
  "把这 32 条消息（含夜莺计划原文）浓缩成 200 字摘要，
   保留: 需求、任务、决策"

LLM 输出摘要 (约 120 字):
  "用户要求制定 Rust 异步编程学习计划，涵盖 Tokio 基础、
   async/await 模式、错误处理等。"

压缩后消息列表:
  [system: "[对话摘要] 用户要求制定 Rust 异步编程学习计划..."]
  [msg_33] [msg_34] ... [msg_40]  ← 最近 8 条

观察:
  ❌ "张明远" 不在摘要里 — 因为他不是"需求"
  ❌ "CockroachDB" 不在 — 因为不是"任务"或"决策"
  ❌ "V60 咖啡" 不在 — 和主线任务无关
  ❌ "夜莺计划" 也很可能不在 — 只是背景信息

═══════════════ 第 2 次压缩 ═══════════════
LLM 收到:
  "把这 20 条消息浓缩成 200 字摘要:
   [system: '摘要1: 用户要求制定 Rust 计划']
   [msg_33]: '详细对比一下 CockroachDB...'
   [msg_34]: 'CockroachDB 和 PostgreSQL 的区别是...'
   ...
   保留: 需求、任务、决策"

LLM 输出摘要 (约 140 字):
  "用户先学习了 Rust 异步编程，然后要求对比 CockroachDB
   和 PostgreSQL 数据库。"

压缩后消息列表:
  [system: "[对话摘要] 用户先学习 Rust，后对比数据库..."]
  [msg_35] ... [msg_42]  ← 新的最近 8 条

观察:
  ❌ 摘要 1 里就没有"张明远"，摘要 2 的来源里也没有
  ❌ 原始信息的任何碎片在第二次压缩后彻底消失

═══════════════ 第 3 次压缩 ═══════════════
LLM 收到:
  "把这 20 条消息浓缩成 200 字摘要:
   [system: '摘要2: 用户学习 Rust，对比数据库']
   [msg_37]: '帮我写 AWS ECS 部署最佳实践...'
   [msg_38]: 'AWS ECS 的部署要点如下...'
   ..."

LLM 输出摘要 (约 130 字):
  "用户先后学习了 Rust 异步编程、对比了数据库、
   了解了 AWS ECS 部署，最近在寻找系统设计书籍推荐。"

压缩后消息列表:
  [system: "[对话摘要] 用户先后学习 Rust、对比数据库..."]
  [msg_41] ... [msg_48]

结论:
  ❌❌❌ 原始信息中的"张明远、夜莺计划、CockroachDB、
  V60 咖啡、冷启动 4 秒"——全部丢失。三次有损编码后归零。
```

**关键机制**：这本质上是**多代有损编码**（generational loss）。就像把一张图片反复截图——每一代都比上一代模糊一点。200 字的摘要压缩 30 条消息，信息损失率可能高达 80%；再压缩包含这个摘要的 20 条消息，剩余碎片再丢 80%。三次之后，原始信息残留不到 1%。

### 3.2 问题二：摘要 Prompt 丢弃了非任务信息

原始摘要 prompt（第 223-226 行，修复前）：

```
将以下对话历史浓缩为一段简短的中文摘要（不超过200字），
保留关键信息：用户的需求、已完成的任务、未完成的任务、
重要决策和结论。
```

**这四个关键词构成了一个"白名单"**：

| 允许保留的 | 不允许保留的（被丢弃） |
|-----------|---------------------|
| 用户的需求 | 用户名、同事名、人物关系 |
| 已完成的任务 | 项目名称、代号 |
| 未完成的任务 | 技术选型原因（"PostgreSQL 分区表太麻烦"） |
| 重要决策和结论 | 性能指标（"冷启动 4 秒，目标 500ms"） |
| | 个人偏好（"喜欢手冲咖啡"） |
| | 试错记录（"Firecracker 试过但不行"） |

LLM 严格按照这个白名单做摘要。"张明远"不是需求、不是任务、不是决策，所以被当作背景闲聊丢弃了。

### 3.3 问题三：200 字上限太紧

200 个中文字符 ≈ 130 个 token。要装下 30+ 条消息的有效信息，LLM 必须做极为激进的取舍。哪怕摘要 prompt 要求保留更多信息，空间本身就不够。

### 3.4 三个问题的叠加效应

```
信息损失 = 白名单过滤 × 多次覆盖 × 空间不足

第 1 代: 原始信息(100%) → 白名单丢弃 60% → 剩余 40% → 压缩到 200 字 → 剩余 ~25%
第 2 代: 残影(25%)    → 覆盖重写 → 剩余 ~8%
第 3 代: 残影(8%)     → 覆盖重写 → 剩余 ~2%
```

到第 3 代，哪怕 LLM 能力再强，残存的 2% 信息量也无法支持哪怕最明显的提示词唤醒。

---

## 4. 修复方案

### 4.1 核心思路：两层记忆分离

把原来"一个摘要覆盖一切"的设计，改成**两层记忆分开存储**：

```
修复前（单层覆盖）:
  [system: "[对话摘要] 一个混合了任务进度和背景信息的摘要"]
  [最近的消息...]
  ↓ 下次压缩时
  [system: "[对话摘要] 一个新的摘要，旧摘要被覆盖"]

修复后（两层分离）:
  [system: "📋 已记录事实：人名、项目、技术选型..."]  ← 只增不减
  [system: "📝 对话摘要：任务进度..."]                   ← 滚动更新
  [最近的消息...]
  ↓ 下次压缩时
  [system: "📋 已记录事实：（合并后更丰富的事实列表）"]  ← 永远不会被删除
  [system: "📝 对话摘要：（新的任务进度）"]              ← 正常滚动
```

### 4.2 第一层：📋 Fact Memory（事实记忆）—— 只增不减

专门存储用户分享过的**背景事实**：

- 人名（张明远）
- 项目名称（夜莺计划 / Nightingale）
- 技术选型（Rust+Tokio, CockroachDB, Leptos, AWS ECS）
- 数字指标（冷启动 4 秒，目标 500ms，2023 年跳槽）
- 个人偏好（手冲咖啡，V60 器具）
- 组织架构（之前在阿里中间件）
- 试错记录（Firecracker microVM 试过但效果不好）

这一层的核心行为：

- **累加合并**：每次压缩时，从对话中提取新的事实，和已有事实比对合并（新增的补充，重复的保留，冲突的以新信息为准）
- **永远不会被删除**：不管压缩多少次，fact memory 只增不减
- **有自己的 LLM 提取逻辑**：用专门的 prompt 提取背景事实，不受"任务/决策"白名单限制

### 4.3 第二层：📝 Rolling Summary（对话摘要）—— 滚动更新

处理**任务进度**：

- 用户问了什么
- 完成了哪些步骤
- 下一步是什么
- 重要结论

和修复前一样滚动更新，但关键变化是：**明确告诉 LLM 不要在摘要里重复背景事实**，因为它们在 fact memory 里。

### 4.4 为什么要两层

如果只改 prompt（让摘要也保留背景事实），还是解决不了覆盖问题——第 2 次压缩时，第 1 次的摘要仍会被覆盖。背景事实和任务信息**衰减速度不同**：

| 信息类型 | 衰减特征 | 策略 |
|---------|---------|------|
| 任务进度 | 随着对话推进自然更新，旧任务信息可以丢弃 | 滚动覆盖 |
| 背景事实 | 对话中随时可能被引用，需要长期保留 | 只增不减 |

分两层存储 = 对不同衰减特征的信息使用不同的保留策略。

---

## 5. 代码改动详解

### 5.1 涉及的文件

| 文件 | 改动内容 |
|------|---------|
| `backend/agent_modes/react_mode.py` | 重写压缩逻辑：3 个新方法 + 1 个修改 |
| `backend/config.py` | 新增 1 个配置项 |
| `.env` / `.env.example` | 新增 1 行配置 |

### 5.2 改动一：`config.py` — 新增配置项

```python
# 第 36 行，新增
compression_summary_max_chars: int = 500   # max chars for rolling summary
```

**为什么需要**：原来摘要长度硬编码为 200 字。改为可配置后，默认 500 字，给滚动摘要更多空间。同时这也意味着 fact memory 不受此限制（fact memory 的长度由 LLM 自然输出决定）。

### 5.3 改动二：`_maybe_compress` — 重写主流程

修复前（已删除的代码）：

```python
# 旧的逻辑：一次压缩 → 一个摘要 → 覆盖
summary = self._generate_summary(to_compress)
session.messages = [
    {"role": "system", "content": f"[对话摘要] {summary}"}
] + recent
```

修复后（第 203-244 行）：

```python
def _maybe_compress(self, session, session_id, step):
    # 1. 触发条件检查（和修复前一样）
    if not self._cfg.compression_enabled:
        return
    if len(session.messages) <= self._cfg.compression_keep_messages:
        return
    est = estimate_tokens(session.messages)
    if est < self._cfg.compression_trigger_tokens:
        return

    keep = self._cfg.compression_keep_messages
    to_compress = session.messages[:-keep]   # 需要压缩的旧消息
    recent = session.messages[-keep:]         # 保留的最近消息

    try:
        # 2. 从旧消息中提取已有的两层记忆
        existing_facts, existing_summary = \
            self._extract_existing_memory(to_compress)

        # 3. 第一层：提取新事实 + 合并旧事实 → 只增不减
        fact_memory = self._extract_and_merge_facts(
            to_compress, existing_facts
        )

        # 4. 第二层：生成新的任务进度摘要 → 滚动更新
        rolling_summary = self._generate_rolling_summary(
            to_compress, existing_summary
        )

        # 5. 组装：fact memory → summary → 最近消息
        new_messages = []
        if fact_memory:
            new_messages.append(
                {"role": "system", "content": fact_memory}
            )
        if rolling_summary:
            new_messages.append(
                {"role": "system", "content": rolling_summary}
            )
        session.messages = new_messages + recent

    except Exception as exc:
        # 降级：压缩失败时跳过，不破坏现有消息
        logger.warning(f"压缩失败，跳过: {exc}")
```

**关键变化**：

1. 从"一次 LLM 调用 → 一个摘要"变为"提取已有记忆 → 两次 LLM 调用 → 两层记忆"
2. 消息结构从 `[系统: 摘要] + 最近消息` 变为 `[系统: 事实] + [系统: 摘要] + 最近消息`
3. 异常降级：任何一步失败都跳过压缩，不破坏现有消息列表

### 5.4 改动三：`_extract_existing_memory` — 新增方法

第 250-262 行：

```python
def _extract_existing_memory(self, messages):
    """从系统消息中扫描已有的 fact memory 和 summary"""
    facts = ""
    summary = ""
    for m in messages:
        if m.get("role") != "system":
            continue
        content = m.get("content", "")
        if content.startswith("📋 已记录事实"):
            facts = content
        elif content.startswith("📝 对话摘要") or \
             content.startswith("[对话摘要]"):
            summary = content
    return facts, summary
```

**为什么需要**：当第 2 次压缩触发时，`to_compress` 消息列表中同时包含旧的 fact memory、旧的 summary 和普通的 user/assistant 消息。这个方法负责**识别并提取**前两层记忆，让后续方法可以分别处理它们。

**向后兼容**：`[对话摘要]` 是修复前使用的旧前缀。如果消息列表中还留有旧格式的摘要（比如在修复后第一次压缩时），这个方法会将它当作 summary 处理，不会丢失。

### 5.5 改动四：`_extract_and_merge_facts` — 新增方法（最核心）

第 264-308 行：

```python
def _extract_and_merge_facts(self, messages, existing_facts):
    """提取背景事实并与已有 fact memory 合并"""

    # ----- 构建提取 prompt -----
    prompt = (
        "从以下对话中提取用户分享过的所有背景事实信息，"
        "包括但不限于：人名、项目名称、技术选型、数字指标、"
        "个人偏好、组织架构、业务背景。\n\n"
        "要求：\n"
        "1. 保留原话中的具体名称和数字，不要泛化"
        "   （如「张明远」不要写成「某同事」）\n"
        "2. 只记录事实，不要记录任务进度或对话流程\n"
        "3. 用简洁的要点形式输出，每行一个事实\n"
        "4. 如果信息在对话中被否定或更新过，记录最新状态"
    )

    # ----- 如果有已有事实，追加合并指令 -----
    if existing_facts:
        clean = existing_facts
        # 去掉 "📋 已记录事实：" 前缀，让 LLM 看到纯净的事实列表
        if clean.startswith("📋 已记录事实"):
            clean = clean[len("📋 已记录事实"):].lstrip("：:\n ")
        prompt += (
            f"\n\n以下是之前已记录的事实，请合并："
            f"新增的事实补充进去，不变的事实保留原文，"
            f"有冲突的以新信息为准。\n\n{clean}"
        )

    # ----- 准备对话内容 -----
    user_content = json.dumps(
        [{"role": m.get("role", "?"),
          "content": m.get("content", "")[:500]}
         for m in messages
         if m.get("role") in ("user", "assistant")],
        ensure_ascii=False,
    )

    # ----- 调用 LLM 提取 -----
    try:
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
        )
        facts = response.choices[0].message.content.strip()
        return f"📋 已记录事实：\n{facts}"
    except Exception:
        # 降级：LLM 调用失败时保留已有事实，不丢数据
        logger.warning("事实提取失败，保留已有事实")
        return existing_facts
```

**逐行解释**：

**Prompt 设计（第 271-290 行）**：

prompt 的开头明确定义了"背景事实"的范围——人名、项目名、技术选型、数字、偏好、组织——这和旧 prompt 的"需求、任务、决策"完全不一样，专门覆盖旧 prompt 丢弃的信息。

第 277 行 `不要泛化` 是关键——它强制 LLM 保留原文中的专有名词和数字，防止"张明远"被写成"某同事"、"CockroachDB"被写成"一种分布式数据库"。

**合并逻辑（第 281-290 行）**：

如果有旧的 fact memory，LLM 会看到完整的历史事实列表。prompt 给出了明确的合并规则：

- "新增的事实补充进去" — 如果这次对话出现了新的事实（比如聊到了新同事），追加到列表里
- "不变的事实保留原文" — 之前记录的事实如果这次没被修改，原封不动保留
- "有冲突的以新信息为准" — 如果用户纠正了之前的信息（比如"冷启动其实已经优化到 2 秒了"），用新信息替换

前缀剥离（第 283-285 行）：去掉 `📋 已记录事实：` 这个展示用的前缀再传给 LLM，让 LLM 看到的是纯净的事实列表，避免前缀干扰它的理解。

**消息截断（第 292-296 行）**：

每条消息只取前 500 个字符（`[:500]`）。因为压缩时 `to_compress` 可能有几十条消息，全量发送会浪费 token 在已经不重要的大段回复上。500 字符足够覆盖用户的原始输入和 AI 回复的核心内容。

只传 `user` 和 `assistant` 角色的消息，跳过 `system` 和 `tool` 消息——因为事实信息只存在于对话中，不在系统指令或工具返回结果里。

**降级策略（第 306-308 行）**：

```python
except Exception:
    logger.warning("事实提取失败，保留已有事实")
    return existing_facts
```

如果 LLM 调用失败（网络问题、API 限流等），不抛异常，而是**保留已有的 fact memory**，同时打一个 warning 日志。这样即使压缩暂时失败，已有的背景事实也不会丢失。下次压缩时会再次尝试提取。

### 5.6 改动五：`_generate_rolling_summary` — 新增方法

第 310-345 行：

```python
def _generate_rolling_summary(self, messages, existing_summary):
    """生成任务进度摘要。背景事实已单独记录，摘要中不重复。"""

    max_chars = self._cfg.compression_summary_max_chars  # 默认 500

    prompt = (
        f"将以下对话历史浓缩为一段中文摘要"
        f"（不超过{max_chars}字）。\n"
        "保留：用户的需求、任务进展、待办事项、重要决策和结论。\n"
        "注意：用户的背景事实（人名、项目名、技术选型等）"
        "已单独记录，摘要中不需要重复。"
    )

    # ----- 如果有旧摘要，追加合并指令 -----
    if existing_summary:
        clean = existing_summary
        # 去掉所有可能的前缀
        for pfx in ("📝 对话摘要：", "📝 对话摘要:",
                     "[对话摘要] "):
            clean = clean.replace(pfx, "")
        prompt += f"\n\n之前的对话摘要（请合并）：{clean}"

    # ----- 准备对话内容（只取最近 30 条）-----
    user_content = json.dumps(
        [{"role": m.get("role", "?"),
          "content": m.get("content", "")[:300]}
         for m in messages
         if m.get("role") in ("user", "assistant")][-30:],
        ensure_ascii=False,
    )

    try:
        response = self.llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
        )
        summary = response.choices[0].message.content.strip()
        return f"📝 对话摘要：{summary}"
    except Exception:
        # 降级：保留已有摘要
        logger.warning("摘要生成失败，保留已有摘要")
        return existing_summary or \
               f"📝 对话摘要：（压缩失败）"
```

**和 `_extract_and_merge_facts` 的区别**：

| 维度 | Fact Memory | Rolling Summary |
|------|------------|-----------------|
| 关注内容 | 背景事实（who, what, how） | 任务流程（what was asked, what was done） |
| 更新策略 | 合并（累加） | 重写（滚动） |
| 截断策略 | 每条消息 500 字符 | 每条消息 300 字符 |
| 历史取用 | 所有 user/assistant 消息 | 最近 30 条 user/assistant 消息 |
| 旧记忆处理 | 合并为新列表 | 作为上下文辅助新摘要生成 |
| 长度限制 | 无硬限制 | `compression_summary_max_chars`（默认 500） |

**"最近 30 条"截断的合理性**：滚动摘要只关心任务进度，30 条消息已经覆盖了自上次压缩以来的所有新对话。超过 30 条的更早信息要么已经在上次摘要中，要么已经进 fact memory 了。

**前缀兼容**：第 325-327 行处理了三种可能的前缀格式——`📝 对话摘要：`（新格式）、`📝 对话摘要:`（英文冒号）、`[对话摘要] `（旧格式）——确保无论是修复前还是修复后的摘要，都能被正确剥离前缀后作为上下文传入。

### 5.7 改动六：`.env` / `.env.example` — 新增配置行

```bash
compression_summary_max_chars=500
```

### 5.8 消息结构的完整演变

用测试场景演示修复前后的消息结构变化：

**修复前（3 次压缩后）**：
```
[
  {"role": "system", "content": "[对话摘要] 用户先后学习 Rust、对比数据库、
   了解 ECS 部署，最近在找书。"},
  {"role": "user", "content": "给我推荐 5 本关于系统设计的书..."},
  {"role": "assistant", "content": "以下是 5 本推荐..."},
  ...(最近 8 条)
]
```
→ 只记得最近做了什么任务，完全不知道张明远是谁。

**修复后（3 次压缩后）**：
```
[
  {"role": "system", "content": "📋 已记录事实：
    - 项目「夜莺计划」(Nightingale)，后端负责人张明远
    - 张明远之前在阿里中间件，2023 年加入
    - 技术栈：Rust + Tokio, CockroachDB（PostgreSQL 分区表太麻烦），
      Leptos (Rust Wasm), AWS ECS
    - 冷启动 4 秒，目标 500ms，Firecracker microVM 试过但延迟反而涨了
    - 张明远喜欢手冲咖啡，工位有整套 V60 器具"},
  {"role": "system", "content": "📝 对话摘要：用户先后要求制定 Rust 异步编程
    学习计划、对比 CockroachDB 和 PostgreSQL、了解 AWS ECS 部署、
    获得系统设计书籍推荐。"},
  {"role": "user", "content": "给我推荐 5 本关于系统设计的书..."},
  {"role": "assistant", "content": "以下是 5 本推荐..."},
  ...(最近 8 条)
]
```
→ fact memory 保留所有背景信息，即使压缩 100 次也不会丢。

---

## 6. 验证方法

### 6.1 功能验证

按第 2 节的步骤操作后，用递进式提示测试：

- **L1 通过** → fact memory 正确保留了人名和项目细节
- **L2 通过** → 数字指标（4 秒、500ms）和试错记录被保留
- **L3 通过** → 即使事实和摘要分离，AI 仍能综合两层信息回答
- **L4 通过** → 最无关的个人偏好（咖啡）也被保留——说明 fact memory 的提取范围足够广

### 6.2 日志验证

每次压缩时，后端终端会打印：

```
[abc12345] 步骤3 触发压缩: 25 条 → 摘要 (估算 2340/8192 tokens)
[abc12345] 压缩完成: 25 条 → 事实 312 字符 + 摘要 187 字符
```

关注：
- "事实 X 字符"：应该随压缩次数增加而增长（因为 fact memory 累加）
- "摘要 Y 字符"：应该在 `compression_summary_max_chars` 范围内波动

### 6.3 回归验证

确认以下功能没有被破坏：

1. **ReAct 模式正常对话**：快速对话模式能正常问答
2. **Plan-Execute 模式正常执行**：多步计划能正常制定和执行
3. **压缩降级**：如果 LLM 在压缩时调用失败，对话不中断（打印 warning 跳过压缩）
4. **工具调用正常**：calculator、search、todo、MCP 工具仍可正常使用
5. **会话持久化**：关闭页面后重开会话，fact memory 和对话摘要都能恢复

---

## 7. 涉及的边界情况

### 7.1 旧格式兼容

`_extract_existing_memory` 方法同时识别：
- `📋 已记录事实`（新前缀）
- `📝 对话摘要`（新前缀）
- `[对话摘要]`（旧前缀，修复前的格式）

如果在修复前已经有压缩过的会话，修复后第一次压缩时会正确处理旧的 `[对话摘要]` 格式。

### 7.2 LLM 调用失败的降级

两层记忆各自有独立的异常处理：

- **事实提取失败** → 返回 `existing_facts`（已有的 fact memory 保留，本次不更新）
- **摘要生成失败** → 返回 `existing_summary`（已有的 summary 保留），如果连已有摘要都没有，返回"压缩失败"标记

两种情况都不会中断主流程，`_maybe_compress` 的外层 `try/except` 作为最后兜底。

### 7.3 首次压缩（无已有记忆）

第一次压缩时，`_extract_existing_memory` 返回两个空字符串。两个生成方法都处理了这种情况：

- `_extract_and_merge_facts`：`existing_facts` 为空时，不追加合并指令，纯粹从对话中提取
- `_generate_rolling_summary`：`existing_summary` 为空时，不追加合并指令，纯粹生成新摘要

### 7.4 Fact memory 为空的情况

`_maybe_compress` 第 232-234 行：

```python
if fact_memory:
    new_messages.append(...)
```

如果 `_extract_and_merge_facts` 返回空字符串（对话中没有可提取的事实），fact memory 消息**不会被添加到消息列表中**，避免发送无意义的空系统消息给 LLM。

### 7.5 压缩触发时的消息数刚好等于 keep_messages

压缩的触发条件之一是：
```python
if len(session.messages) <= self._cfg.compression_keep_messages:
    return
```

如果消息总数 ≤ `keep_messages`（默认 8 条），直接跳过压缩。这确保总有足够消息保留在最近窗口内，不会出现 `to_compress` 为空的情况。

### 7.6 PlanExecute 子循环中的压缩

PlanExecute 模式的子循环创建 `ReactMode` 实例时传入了 `max_steps_override=8`。子循环中的压缩行为和外层完全一致——也会分层存储 fact memory 和 rolling summary。但子循环结束后，这些系统消息会随子循环的会话一起保存，外层继续执行时会看到它们。
