# 来源与致谢

本仓库不是从零开始的原创项目，它站在两个公开仓库的肩上。这里如实说明每一部分从哪来，方便你自行核查。

## 上游

| 仓库 | 作者 | 许可证 | 本仓库用到了什么 |
|---|---|---|---|
| [vibe-motion/sound](https://github.com/vibe-motion/sound) | [@vibe-motion](https://github.com/vibe-motion) | 未声明 | `freesound()` 的页面解析思路；SKILL.md 中"用人的耳朵信号代替试听"的选材方法论 |
| [sxhzju/sound](https://github.com/sxhzju/sound) | [@sxhzju](https://github.com/sxhzju) | 未声明 | `pixabay()` 的解析思路（卡片排序 → 详情页 JSON-LD）、三件套的分工设计 |
| [sxhzju/sfx](https://github.com/sxhzju/sfx) | [@sxhzju](https://github.com/sxhzju) | MIT | 早期单 skill 版本，用于对照四源的实现差异 |

`sxhzju` 是 `vibe-motion` 作者的个人账号（其 GitHub bio 写明 `vibe coding做动画->@vibe-motion`）。两个 `sxhzju` 仓库把 vibe-motion 付费版宣称的能力（四源检索、程序化音频、混音）公开实现了一遍。

## 许可证状态说明（请读）

`vibe-motion/sound` 与 `sxhzju/sound` **都没有 LICENSE 文件**。按默认版权规则，未声明许可证的代码不自动授予再分发权。本仓库因此做了两件事：

1. **只借用思路，不整段复制。** 所有函数都重写过：`mixkit()`、`kenney()`、`get()`、`search()`、`_filter_dur()`、`_peak_db()`、`_index_lock()`、`_ensure_cffi()` 等为本仓库原创；`pixabay()`、`freesound()` 沿用上游的解析策略（选哪个 HTML 片段、抓哪些字段），但实现、错误处理与降级逻辑均为重写。
2. **如实标注，随时可调整。** 如果上述任何一位作者认为本仓库越界，请开 issue，我会立刻修改或移除相关部分。

本仓库自身以 [MIT](LICENSE) 发布。

## 本仓库新增的部分

以下能力在上游任一仓库中都不存在，是本仓库为实际使用而加的：

- **Windows 支持**：上游全为 macOS 环境，`need_cffi()` 在 Windows 上会死循环重建 venv（`bin/python` 不存在）。本仓库改为跨平台路径 + 进程内导入。
- **并发安全**：索引写入加文件锁与原子替换；下载临时文件带 pid + 线程 id。
- **路径约束**：`kn:` 键限制在 Kenney 缓存目录内，防路径穿越。
- **实测时长与峰值**：`get` 下载后用 ffprobe / ffmpeg 回填真实时长，并标记削波（`CLIPPING`）。
- **时长过滤**：`--min-dur` / `--max-dur`，解决"0.2 秒的卡片弹出返回 55 秒循环音"。
- **降级可见**：任一源解析到 0 条、被限流、或详情页失败时，明确提示而不是静默返回空。
- **25 个 bug 修复**：完整清单见 README。

## 音频素材的许可证

本仓库只提供检索与下载工具，不分发音频文件。下载到的每个音效遵循其来源站的许可证：

| 源 | 许可证 | 商用 |
|---|---|---|
| Pixabay | Pixabay License | 免费商用，无需署名 |
| Freesound | CC0 / BY / BY-NC | 视条目而定，BY 需署名，BY-NC 不可商用 |
| Mixkit | Mixkit Free License | 免费商用 |
| Kenney | CC0 | 免费商用，无需署名 |
