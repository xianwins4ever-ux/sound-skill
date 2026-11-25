# sound-skill

给 AI agent 用的音效检索 skill：一句话找音效，四个源并排比较，下完告诉你真实时长和有没有削波。

## 付费版完整功能，免费

vibe-motion 的 Sound Skill 付费版卖三件事：更多来源的音效、生成背景音乐、混音。这三件事的能力，作者本人都已在个人账号公开实现——只是分散在三个仓库里，而且只在他的 macOS 环境跑得通。

本仓库做的是把其中最常用的**音效检索**整合成一个能直接用的 skill，补齐 Windows 支持，并修掉 25 个 bug。

- 四源检索：[sxhzju/sound](https://github.com/sxhzju/sound)（作者个人号，bio 写明 `->@vibe-motion`）
- 音乐生成：[sxhzju/sound/procedural-audio](https://github.com/sxhzju/sound/tree/main/procedural-audio)
- 混音：[sxhzju/sound/audio-mixing](https://github.com/sxhzju/sound/tree/main/audio-mixing)

商业版仓库本身没写许可证，本仓库因此只借用解析思路、全部重写实现，来源逐条列在 [CREDITS.md](CREDITS.md)。

## 和付费版卖点的对应关系

| 付费版宣称 | 本仓库 | 在哪 |
|---|---|---|
| 查找与下载更多来源的音效 | **四个源**：Pixabay / Freesound / Mixkit / Kenney | 本仓库 |
| 生成背景音乐和音效 | 作者已开源，需另装 Surge XT / sfizz | 上游 `procedural-audio` |
| 人声、配乐与音效混音 | 作者已开源，纯 FFmpeg 无依赖 | 上游 `audio-mixing` |

## 和原版有什么不同

原版只能查 Freesound 一个源。这份加到了四个，并修掉一批会让它在 Windows 上直接趴下的问题。

**四源分工**

| 源 | 人耳信号 | 拿到什么格式 | 许可证 |
|---|---|---|---|
| Pixabay | 点赞、下载量 | 完整 mp3 | 无需署名 |
| Freesound | 下载量、评分(人数)、上传者描述 | mp3 预览 | CC0 / BY / BY-NC |
| Mixkit | 只有标题和时长 | **完整 wav** | 免费商用 |
| Kenney | 只有文件名 | ogg → 自动转 mp3 | CC0 |

**排序不是按人气就完事**

四个源都按人气排，但人气对短促音效是**反向指标**：一个 55 秒的翻纸循环，点赞比 0.45 秒的翻页音多得多。所以加了 `--max-dur` 先卡时长，再看人气。

**列表上的时长全是假的**

| 显示 | 实测 | 偏差 |
|---|---|---|
| `1s` | 0.575s | 少报 43% |
| `1s` | 1.200s | 多报 20% |
| `0:01s` | 0.452s | 少报 55% |
| `0:01s` | 1.334s | 多报 33% |
| Kenney | `?` | 根本没有 |

所以 `get` 下完会用 ffprobe 量一遍，直接打出来：

```
px_382724_Simple-Whoosh.mp3                    0.575s  -2.3dB
fs_260614_Pop-wav.mp3                          0.128s  -5.4dB  [credit kwahmah_02]
kn_interface-sounds_toggle_001.mp3             0.158s  -1.0dB
mk_1492_Cinematic-whoosh-fast-transition.wav   1.334s  -0.5dB
```

峰值超过 `-0.1dB` 会标 `CLIPPING`。实测有个热门 Pixabay whoosh 是 `+1.5dB CLIPPING`——列表里完全看不出来，丢进混音就爆。

## 修的 25 个 bug

原版在 Windows 上基本跑不起来。这些是实测出来的，不是猜的。

**会直接崩的**

- `--help` 崩：`UnicodeEncodeError: gbk`。docstring 里有 ♥↓★→，而 `--help` 在 `parse_args()` 内部就打印了，UTF-8 修复写在它之后等于没写
- `--pages 0` 崩：`max_workers must be greater than 0`
- venv 建好一半时 `import curl_cffi` 会成功（Python 3 把缺 `__init__.py` 的目录当 namespace package），但一用就 `DLL load failed`，且健康检查永远通过、永不自愈

**会静默毁数据的**

- 索引文件读坏时返回空字典，下一次保存就把整个缓存覆盖掉。实测 599 条缓存一次全丢
- 8 个进程同时写索引，4 条更新静默消失，全部 exit 0
- 两个下载线程写同一个 `.part` 临时文件，交错后落成"长度正确、内容是垃圾"的音频，而 `exists()` 会把它永久当成已下载

**会给你错结果的**

- 中文查询不报错，返回完全无关的音频（"关门声" → "Confused Male Voice Huh"），看起来像真结果
- 某个源解析失败时返回空列表，分不清"确实没结果"和"站点改版了"
- Mixkit 的完整 WAV 有时 403，不回退到预览 mp3 就永远下不下来
- Kenney 搜 `switch` 返回 `click1-4`（字母序把 38 个 switch 全挤掉）
- `--max-dur 0.8` 会把 0.479 秒的卡片弹出滤掉，因为列表把它印成 `0:01s`

**安全问题**

- `kn:` 键可以路径穿越，`kn:../../../.gitconfig` 能把任意文件复制出来

完整清单和每条的实测证据在提交记录里。

## 安装

```bash
git clone https://github.com/xianwins4ever-ux/sound-skill.git ~/.agents/skills/sound
```

需要 Python 3。Pixabay 在 Cloudflare 后面，首次调用会自动装 `curl_cffi` 到一个私有 venv（约 10 秒，不动系统环境）。ffmpeg / ffprobe 可选——没有的话 Kenney 的 ogg 不转码，时长显示 `?s`，其余功能正常。

## 用法

```bash
# 装在 ~/.agents/skills/sound（上面的安装命令就是这个位置）
S=~/.agents/skills/sound/scripts/sfx.py
# 装在别处就把这行换成实际路径，命令都一样

# 四源并排，按画面动作自动决定优先级
python $S search "soft whoosh" -n 3 --urls

# 只要 0.8 秒以内的短音
python $S search "card pop" --max-dur 0.8

# 单个源
python $S pixabay "cinematic impact" --urls
python $S freesound "paper slide" --license cc0 --urls
python $S kenney "toggle"          # 本地索引，离线可用
python $S kenney --packs           # 列 10 个 CC0 音频包
python $S kenney "impact" --fetch impact-sounds   # 按需拉新包

# 下载，6 路并发，下完打印实测时长和峰值
python $S get ./sfx px:382724 fs:260614 mk:1492 kn:ui-audio/Audio/click1.ogg
```

在 Claude Code / Codex 里不用敲命令，直接说"给这个开关找一个 0.1 秒的点击音，要 CC0"，skill 会自己走完检索、筛选、下载。

几个容易踩的点：

- 查询词必须是英文。四个源都只索引英文，中文不会报错，只会给你不相干的结果
- `kn:` 的 key 要带 `Audio/` 段，直接复制搜索输出里的那串最稳
- `--pages` 上限 20。再深就会触发限流，而且后面的页基本是重复的

## 许可证

本仓库 MIT。下载到的音效遵循各自来源的许可证，商用前看一眼 [CREDITS.md](CREDITS.md) 里的表格——Freesound 默认可能返回 BY-NC，那个不能商用。
