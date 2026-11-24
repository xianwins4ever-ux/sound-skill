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

**格式差异值得注意**：Mixkit 下载的是完整 `.wav`（网页卡片只挂 mp3 预览，脚本换成了 WAV 路径）；Kenney 是 `.ogg`，`get` 会自动用 ffmpeg 转 mp3；Pixabay 与 Freesound 给 mp3。

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--license cc0` | 仅搜索 CC0（仅 Freesound 支持） |
| `--license by` | 搜索 CC0 和 Attribution（仅 Freesound） |
| `--urls` | 显示试听链接 |
| `-n 5` | 最多显示 5 条结果，默认 8 条 |
| `--sort relevance` | 取相关结果后按下载量重排，默认方式（Freesound） |
| `--pages 3` | 从起始页抓取的页数，Pixabay 每页 20、Freesound 每页 15 |
| `-p 2` | 从第 2 页开始搜索，默认第 1 页 |

## 许可证与署名

每条音效的许可证可能不同。Pixabay License 与 Kenney 的 CC0 无需署名；Mixkit 免费商用；Freesound 默认 `any` 可能返回 BY-NC，商业用途前应检查。

对于非 CC0 音效，`get` 会输出作者署名提示。这只是作者信息提示，交付时还应保留音效来源与许可证信息，按对应条目的要求补全署名。

## 网络排查

- **Freesound / Pixabay 直连可用**，本机实测无需代理。Freesound 单连接限速约 80 KB/s，所以把多个 ID 放进同一个 `get` 并发拉取。
- **Pixabay 在 Cloudflare 后面**：裸 `urllib` 会拿到 "Just a moment…"（HTTP 403），脚本用 `curl_cffi` 伪装 Chrome 的 TLS 指纹绕过去。若某天又开始 403，说明 Cloudflare 收紧了，只能退回手工读搜索页。
- Kenney 打包下载需要带 `Referer` 头，否则 403；脚本已处理，包只下一次，之后离线可搜。
- [`references/local-setup.md`](references/local-setup.md) 和 [`scripts/clash_freesound.py`](scripts/clash_freesound.py) 针对作者的 macOS / ClashX Meta 配置。辅助脚本的 `--fix` 会修改本机 Clash 配置并切换节点，仅在环境匹配且需要调整代理时使用；Windows 上它什么都不做。
