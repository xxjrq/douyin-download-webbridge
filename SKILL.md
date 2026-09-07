---
name: douyin-download-webbridge
description: 免费下载抖音视频和图文图片，不用注册第三方下载站，也不需要 TikHub、redfox 等第三方 API Key。用户提供抖音分享短链、长链或作品 ID，要求下载视频、保存图文图片、获取高清素材时使用。通过 Easy WebBridge 复用用户已授权的浏览器；公开作品可直接处理，遇到抖音登录墙时停止并请用户在自己的浏览器登录。视频默认选择最高可用分辨率并优先 H.264，图文支持多张图片按顺序保存。
---

# 免费抖音下载支持视频图片

## 先说亮点

- **免费**：开源使用，不按次数收费。
- **免额外登录**：不用注册第三方下载网站；公开作品可以直接处理，抖音出现登录墙时再登录抖音。
- **免 Key**：不需要申请 TikHub、redfox 或其他第三方内容接口的 API Key。
- **视频、图片都支持**：既能保存视频，也能按顺序保存多张图文图片。

通过 Easy WebBridge 复用用户已经打开并授权的浏览器，把抖音作品保存到本地。

## 1. 一键命令

```bash
python3 scripts/douyin_download.py "https://v.douyin.com/xxxxx/"          # 默认下载目录
python3 scripts/douyin_download.py 7669474316672716066                    # 作品 ID 也认
python3 scripts/douyin_download.py "<链接>" -o /path/to/dir               # 指定输出目录
python3 scripts/douyin_download.py "<链接>" --browser 自媒体               # 指定浏览器
python3 scripts/douyin_download.py "<链接>" --quality worst               # 最小体积预览
```

**默认即最高清**，不用加任何参数：视频取最大分辨率且同分辨率优先 H.264，图文逐张取 `原图 > JPEG > WebP`。
`--quality worst` 只用于「快速看一眼」的预览场景。

脚本自动完成：依赖探测 → bridge 检查 → 短链解析 → 打开页面 → 取最高清直链 → 下载 → 校验 → 关闭标签组。

## 2. 前置门禁

执行前必须全部通过，任一失败即停止并报告原因：

1. **easy-webbridge CLI** 存在。按序探测：
   - 环境变量 `EASY_WEBBRIDGE_CLI` 指定的路径。
   - 本 Skill 同级的 `easy-webbridge/cli/easy-webbridge.mjs`。
   - `~/.agents/skills/easy-webbridge/cli/easy-webbridge.mjs` 等常见 Agent Skill 目录。
   - `~/.workbuddy/skills/easy-webbridge-browser__skillhub/scripts/easy-webbridge.mjs`
   - 任一可用即可。
2. **bridge 服务在线**：`127.0.0.1:17777` 可访问，token 读自 `~/.easy-webbridge/bridge-token`。
3. **至少一个浏览器 online**：默认挑 displayName 为 `自媒体` 的实例，找不到时退选第一个在线浏览器并告警。

服务未启动时不要手工拉起其他工具顶替，先按 `easy-webbridge` skill 的方式启动服务。

## 3. 输入解析

接受三种输入：分享短链、长链、纯数字 modal_id。

- 短链用 `curl -sIL ... -w '%{url_effective}'` 跟重定向，从结果里正则提取 `/video/{id}` 或 `/note/{id}`。
- **`/note/` 是图文作品**，不是视频，走第 5 节分支。
- 提取不到作品 ID 立即失败，不猜、不兜底。

## 4. 视频下载

### 4.1 取直链（关键）

**禁止直接读 `video.src`** —— 页面默认只给 540p 档（576×1024）。必须在页面内 fetch detail 接口拿全量码率档位：

```javascript
(async () => {
  const url = `https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id=${awemeId}`;
  const j = await (await fetch(url, { credentials: "include" })).json();
  const v = j.aweme_detail.video;
  return (v.bit_rate || []).map(b => ({
    gear: b.gear_name,
    w: b.play_addr.width,
    h: b.play_addr.height,
    url: b.play_addr.url_list[0],
  }));
})()
```

按 `w × h` 排序选最大档。抖音常见档位：`normal_1080_0`(1080×1920) / `normal_720_0` / `normal_540_0`。

### 4.2 下载

必须带移动端 UA 与 `Referer: https://www.douyin.com/`，否则可能 403。

### 4.3 校验

下载后用 `ffprobe` 输出真实分辨率、编码、时长、体积。**ffprobe 不在 PATH**，固定用 `/opt/homebrew/bin/ffprobe`。

## 5. 图文（note）下载

### 5.1 类型判定（不能只看链接）

**短链路径不可靠**：图文作品的分享链接同样走 `/share/video/{id}`，只有打开后看页面实际跳转与有无 `video` 元素才准：

```javascript
(() => ({
  href: location.href,
  hasVideo: !!document.querySelector("video"),
}))()
```

`href` 含 `/note/` 或 `hasVideo` 为假 → 图文。视频取流失败时自动兜底走图文分支。

### 5.2 取图：detail 定清单 + DOM 补签名

**禁止只从 DOM 抓 `<img>`** —— 会混进推荐位、评论区的缩略图（实测抓到 11 张，正文其实只有 1 张）。正确做法是两边配合：

1. detail 接口取 `aweme_detail.images[]`，拿到**准确的正文图片清单**、宽高，以及每张的**全部** `url_list` 档位。
2. DOM 取页面 `<img>` 的 src，拿到**带有效签名的 URL**。
3. 按图片 ID 匹配：从 URL 正则 `/\/([A-Za-z0-9_-]{20,})[~?]/` 提取 ID，同 ID 的候选里**优先挑 `~noop`（原图）**。

**绝不能自己把 `~tplv-xxx` 改写成 `~noop.jpeg`**：抖音的 `x-signature` 是针对完整 URL（含 `~tplv-` 段）计算的，改了必然 403。只有页面正在用的那个 URL 签名才有效。

### 5.3 单张图的档位选择：原图 > JPEG > WebP

`images[].url_list` 通常给 3 个 URL：`q75.webp`(p3) / `q75.webp`(p9) / `q75.jpeg`(p3)。
**只取 `url_list[0]` 会固定拿到体积最小、损失最大的 webp。**

实测同一张 1080×1440 图：

| 档位 | 体积 | 结论 |
|---|---|---|
| `~noop.jpeg` 原图 | 169 KB | 最优，但只有当前轮播显示的那张才有 |
| `q75.jpeg` | 113 KB | **常规最优解**，文字清晰、通用性最好 |
| `q75.webp` | 54 KB | 压缩损失明显，作兜底 |

选择逻辑见 `pick_image`：DOM 里有同 ID 的 `~noop` 就用它，否则退 `q75.jpeg`，再退 `q75.webp`。

**不要用 `images[].download_url_list`** —— 那是抖音「保存图片」用的**带水印**版本（`~tplv-dy-water-v2:...`）。

**原图拿不全的原因**：图文是懒加载轮播，只有当前显示的那张会渲染 `~noop` URL。实测轮播**翻不动**——JS `.click()`、键盘 `ArrowRight`、CDP `Input.dispatchMouseEvent` 全部无效（点击后累计 noop 数始终不变），所以多图作品通常只能拿到 `q75.jpeg` 档。脚本会打印每张图的档位分布，能直观看出是否拿到了原图。

### 5.4 落地

多张图按 `_01` `_02` 顺序编号，扩展名按 URL 后缀取 `.webp` / `.jpeg` / `.png`。

## 6. 输出合同

- 输出目录默认 `~/Downloads/DouyinDownloads`，不存在时自动创建。
- 文件名取作品 desc，清理规则：去 `#话题`、去 emoji 与非法字符、限长 40 字；清理后为空则用 modal_id。
- 视频扩展名 `.mp4`；图文按 URL 后缀取 `.jpeg` / `.png` / `.webp`。
- 结束时打印实际保存的文件绝对路径。

## 7. 踩坑清单

| 坑 | 现象 | 处理 |
|---|---|---|
| ffmpeg/ffprobe 不在 PATH | `which ffmpeg` not found | 固定用 `/opt/homebrew/bin/ffmpeg`、`/opt/homebrew/bin/ffprobe` |
| 直接读 `video.src` | 只拿到 540p | 必须走 detail 接口取 `bit_rate[]` |
| 只按 `w×h` 选档 | 同分辨率选到 HEVC，剪辑软件兼容性差 | 同分辨率优先 `cs=0`（H.264），见 `_codec_rank` |
| 用短链路径判类型 | 图文也走 `/share/video/`，误判成视频 | 打开页面后按 `location.href` + `hasVideo` 判 |
| DOM 直抓 `<img>` | 混入推荐位小图（实测 11 张里只有 1 张是正文） | detail 的 `images[]` 定清单，DOM 只用于补签名 URL |
| 自己改写 `~noop.jpeg` | 签名失效，下载 403 | 只能用页面原有的 URL，按图片 ID 匹配 |
| 只取 `images[].url_list[0]` | 固定拿到 54KB 的 `q75.webp` | 遍历全部 url_list，优先 `.jpeg`（113KB，质量翻倍） |
| 用 `download_url_list` | 下下来的图**带抖音水印** | 那是「保存图片」专用，改用 `url_list` |
| 想翻轮播补齐原图 | JS 点击 / 键盘 / CDP 真实点击**全部无效** | 放弃，接受 `q75.jpeg` 档 |
| bridge network 抓包取响应体 | `responseBody` 恒为空 | 改用页面内 `fetch` |
| 下载报 403 | 直链过期或缺 Referer | 带移动端 UA + Referer |
| 直链有时效 | 隔一段时间后 403 | 重新跑一次脚本拿新链 |

## 8. 边界

- 只下载，不做剪辑、转码、加水印、去水印。
- 不上传平台、不操作账号、不采集发布后数据。
- 遇到风控验证页（滑块/登录墙）时停止，不绕过。

## 9. 与工作台候选池协作

当素材来自“内容来源采集器”或工作台“热点候选池”时，遵循下面的边界：

1. 候选池只保存人工待筛选的抖音视频/图文，不是正式内容，也不会自动创建 `projects/` 目录。
2. 工作台的“加入下载队列”接口（`POST /api/source-candidates/batch-download`）目前只登记 `pending` 下载任务；它不会在接口请求中直接下载文件。下载 Skill 或后续 Worker 必须逐项读取候选的 `canonical_url`，调用本 Skill 的一键命令，并在完成后回写真实输出路径和结果。
3. 下载前必须由用户确认候选项。批量任务按候选逐项执行，不能把失败项标成成功；失败原因和路径要分别保留。
4. 视频候选使用 `content_type=video`，图文候选使用 `content_type=post`。图文按第 5 节落地多张图片，不能把图文当成空视频文件。
5. 建议输出到对应内容单元的 `assets/raw/` 或用户指定的素材目录；不得把素材、缓存或下载任务元数据写入正式 `发布成品/`。
6. 候选池支持抖音以外的平台字段，但本 Skill 只处理抖音。小红书、B 站等平台必须由各自下载 Skill 负责，不能套用抖音直链规则。

候选池状态与下载状态分离：`collected/shortlisted/promoted/rejected` 表示人工筛选进度；`none/queued/processing/completed/failed` 表示下载进度。只有实际文件通过 `ffprobe` 或图片完整性检查后，才能回写 `completed`。
