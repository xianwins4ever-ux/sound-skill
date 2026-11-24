# sound

一个用于视频音效选材的 [CC] Skill。从 **Pixabay、Freesound、Mixkit、Kenney** 四个来源搜索和下载音效，结合点赞数、下载量、评分人数、上传者描述、时长与许可证，帮助 Agent 为画面挑选合适的声音。

适用于转场、卡片入场、按钮点击、纸张滑动、碰撞等视频音效需求。Skill 的工作范围是音效搜索、筛选与下载；时长和能量分析可配合 FFmpeg 完成。

> 本机版本：在 vibe-motion/sound 上游基础上补齐了 Pixabay 与 Mixkit/Kenney 两源，并修掉了上游的 Windows 兼容问题。上游 SKILL.md 里的付费版推销段落已整段移除。

## 四个来源的分工

| 源 | 人耳信号 | 下载格式 | 许可证 | 适合 |
| --- | --- | --- | --- | --- |
| **Pixabay** | ♥点赞、↓下载量 | mp3（完整文件，非预览） | Pixabay License，无需署名 | 量最大，通用音效首选 |
| **Freesound** | ↓下载量、★评分(人数)、上传者描述 | mp3（预览码率） | CC0 / BY / BY-NC | 真实拟音、录音细节可考 |
| **Mixkit** | 只有标题和时长 | **wav** | Mixkit Free | 需要无损 WAV 时 |
| **Kenney** | 只有文件名 | ogg（脚本自动转 mp3） | CC0 | UI 音效、游戏音，成套一致 |

## 安装

需要 [CC]、Python 3。搜索与下载只用 Python 标准库；Pixabay 额外需要一个 `curl_cffi`，脚本首次调用时自动装进 `~/.cache/sfx-sources/venv`（约 10 秒，不动系统环境）。

```bash
git clone https://github.com/vibe-motion/sound.git .claude/skills/sound
```

核心文件：

```text
.claude/skills/sound/
├── SKILL.md                    # Agent 的技能入口与选材规则
├── scripts/
│   ├── sfx.py                  # 四源搜索与下载
│   └── clash_freesound.py      # 特定 ClashX Meta 环境的网络辅助脚本（Windows 上无效）
└── references/
    └── local-setup.md           # 作者的本地网络配置参考
```

## 在 [CC] 中使用

安装后，在视频项目中直接描述音效需求，例如：

> 用 sound 帮我找一个卡片飞入时的短 whoosh，约 0.3 秒，适合轻快的产品演示，下载到 sfx/。

> 给开关切换找一个柔和、不刺耳的点击音效。先给出候选、点赞数、下载量和试听链接。

Skill 引导 Agent：

1. 将画面动作转成英文关键词。UI 类提示词（click / switch / toggle / pop…）先走 Kenney，其余先走 Pixabay。
2. 先判断声音来源、描述和时长是否符合画面，再参考点赞数与下载量，说明推荐依据。
3. 按使用需求筛选许可证；需要人工试听时提供预览链接。
4. 下载选中的音效，必要时用 FFmpeg 检查时长与能量分布，并保留所需署名信息。

点赞数与下载量只是选材线索，不代表声音一定适合当前画面；Agent 也不应把这些信号当作已经试听过的结论。

## 直接运行脚本

脚本也可独立使用。以下命令均在项目根目录执行：

```bash
S=.claude/skills/sound/scripts/sfx.py

# 四源聚合，按画面动作的提示词自动决定优先级
python3 "$S" search "soft whoosh" -n 3 --urls

# 单源：Pixabay 按点赞排序
python3 "$S" pixabay "cinematic impact" --urls

# 单源：Freesound 只要 CC0
python3 "$S" freesound "paper slide" --license cc0 --urls

# 下载：把占位符换成搜索返回的 ID，可一次传入多个，6 路并发
python3 "$S" get sfx/ "px:<id>" "fs:<id>" "mk:<id>" "kn:<pack>/<file>"
```

搜索结果会缓存在 `~/.cache/sfx-sources/index.json`，下载依赖这份缓存。例外：Mixkit 的下载路径可由 ID 直接推导，所以旧 ID 也能下。

**格式差异值得注意**：Mixkit 先试完整 `.wav`，403 时回退到卡片的 `-preview.mp3`（有些 id 的 WAV 会 403，不回退就会"看起来能下、实际失败"）；Kenney 是 `.ogg`，`get` 会自动用 ffmpeg 转 mp3，文件名保留包名（`kn_ui-audio_click1.mp3`），因为两个包里存在同名文件；Pixabay 与 Freesound 给 mp3。

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--license cc0` | 仅搜索 CC0（仅 Freesound 支持） |
| `--license by` | 搜索 CC0 和 Attribution（仅 Freesound） |
| `--min-dur 0.3` | 丢掉短于该秒数的结果（未知时长的保留） |
| `--max-dur 0.8` | 丢掉长于该秒数的结果——解决"0.2 秒的卡片弹出返回 55 秒循环音" |
| `--urls` | 显示试听链接 |
| `-n 5` | 最多显示 5 条结果，默认 8 条 |
| `--sort relevance` | 取相关结果后按下载量重排，默认方式（Freesound） |
| `--pages 3` | 从起始页抓取的页数，Pixabay 每页 20、Freesound 每页 15 |
| `-p 2` | 从第 2 页开始搜索，默认第 1 页 |

`--min-dur` / `--max-dur` 只过滤打印结果，**所有结果仍然写进缓存**，所以被过滤掉的条目之后照样能按 key 下载。

## 时长不可信，务必以 `get` 的实测值为准

| 源 | 列表显示 | 实测 | 偏差 |
| --- | --- | --- | --- |
| Pixabay | `1s` | 0.552s | 少报 45% |
| Pixabay | `1s` | 1.200s | 多报 20% |
| Mixkit | `0:01s` | 0.452s | 少报 55% |
| Kenney | `?` | — | 没有 |

`get` 下载完会打印每个文件的**实测时长和峰值**（走 ffprobe / ffmpeg，找不到时显示 `?s`）。判断短促音效（卡片弹出、点击、翻页）是否合适，只看这个数字。

峰值超过 `-0.1dB` 会标 `CLIPPING` —— 该文件在 0 dB 增益下已经削波，放进混音只会更糟。实测某个热门 Pixabay whoosh 就是 `+1.5dB CLIPPING`，列表里完全看不出来。

排序同理：四个源都按人气排，而人气对短促 one-shot 是**反向指标**——55 秒的翻纸循环比 0.45 秒的翻页音点赞多得多。正确用法是 `--max-dur` 先卡时长，再看人气排序。

## 许可证与署名

每条音效的许可证可能不同。Pixabay License 与 Kenney 的 CC0 无需署名；Mixkit 免费商用；Freesound 默认 `any` 可能返回 BY-NC，商业用途前应检查。

对于非 CC0 音效，`get` 会输出作者署名提示。这只是作者信息提示，交付时还应保留音效来源与许可证信息，按对应条目的要求补全署名。

## 网络排查

- **Freesound / Pixabay 直连可用**，本机实测无需代理。Freesound 单连接限速约 80 KB/s，所以把多个 ID 放进同一个 `get` 并发拉取。
- **Pixabay 在 Cloudflare 后面**：裸 `urllib` 会拿到 "Just a moment…"（HTTP 403），脚本用 `curl_cffi` 伪装 Chrome 的 TLS 指纹绕过去。venv 首次调用时自动建在 `~/.cache/sfx-sources/venv`（约 10 秒）；若 venv 损坏，脚本会自动重建一次。若某天又开始 403，说明 Cloudflare 收紧了，只能退回手工读搜索页。
- Kenney 打包下载需要带 `Referer` 头，否则 403；脚本已处理，包只下一次，之后离线可搜。包是否装完以 `.complete` 标记为准，中断的解压会被重试而不是被误判为已完成。
- **某个源突然返回空**：解析到 0 条时会往 stderr 打警告，所以"确实没有结果"和"站点改版了"能区分开。平时能用的源突然空了，先怀疑站点改版，不要怀疑查询词。
- **商用前查许可证**：Freesound 默认 `any` 可能返回 BY-NC（不可商用），商用场景请加 `--license by` 或 `--license cc0`。Pixabay 无需署名，Kenney 全 CC0，Mixkit 免费商用。
- [`references/local-setup.md`](references/local-setup.md) 和 [`scripts/clash_freesound.py`](scripts/clash_freesound.py) 针对作者的 macOS / ClashX Meta 配置。辅助脚本的 `--fix` 会修改本机 Clash 配置并切换节点，仅在环境匹配且需要调整代理时使用；Windows 上它什么都不做。
