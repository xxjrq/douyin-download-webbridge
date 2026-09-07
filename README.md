<div align="center">

<img src="assets/icon-512.png" width="112" height="112" alt="免费抖音下载支持视频图片图标">

# 免费抖音下载支持视频图片

## 免费 · 免额外登录 · 免第三方 API Key

把抖音链接交给 Agent，就能把视频或图文图片保存到本地。不用注册第三方下载站，不用申请接口 Key，公开作品可以直接处理；只有抖音自己弹出登录墙时，才需要在你的浏览器里登录抖音。

[简体中文](README.md) | [English](README.en.md)

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-2563EB?style=flat-square)](https://agentskills.io/)
[![Easy WebBridge](https://img.shields.io/badge/runtime-Easy%20WebBridge-111827?style=flat-square)](https://github.com/xxjrq/easy-webbridge)
[![GitHub Stars](https://img.shields.io/github/stars/xxjrq/douyin-download-webbridge?style=flat-square)](https://github.com/xxjrq/douyin-download-webbridge/stargazers)
[![skills.sh](https://skills.sh/b/xxjrq/douyin-download-webbridge)](https://skills.sh/xxjrq/douyin-download-webbridge)
[![License](https://img.shields.io/badge/license-MIT-16A34A?style=flat-square)](LICENSE)

</div>

## 四个亮点

- **免费**：项目开源，不按次数收费。
- **免额外登录**：不用注册第三方下载网站，继续使用自己的浏览器。
- **免第三方 Key**：不需要 TikHub、redfox 或其他下载接口的 Token。
- **视频图片都支持**：视频默认选择最高可用清晰度，图文作品按顺序保存多张图片。

## 它能做什么

- 下载抖音视频：从作品详情页取得可用码率，默认按分辨率选择最高档，同分辨率优先 H.264。
- 下载抖音图文：识别图文作品，按正文图片清单逐张下载，支持多图编号保存。
- 接受分享短链、作品长链和纯数字作品 ID。
- 自动创建本次任务的浏览器标签组，完成后只关闭自己的标签组。
- 用作品标题生成文件名，并在保存后输出文件路径和基础媒体信息。
- 免费使用，不需要 TikHub、redfox 或其他第三方 API Key。

这里的“免额外登录”是指不需要注册第三方下载站。“免 Key”是指不需要第三方内容接口的 Token。运行时仍需要 Easy WebBridge、Node.js、Python 和一个 Chromium 浏览器；公开作品通常可以直接处理，遇到抖音登录墙时需要先登录抖音。

这不是剪辑器，也不是“去水印”服务。它只负责把你有权使用的抖音视频或图文保存到本地，不上传平台、不操作账号。

## 与 Easy WebBridge 的关系

```text
Claude Code / Codex / OpenCode / WorkBuddy
                    |
       douyin-download-webbridge Skill
              下载 + 文件整理
                    |
          Easy WebBridge 127.0.0.1:17777
                    |
       浏览器扩展 + 抖音公开作品页
```

本仓库是独立业务 Skill，负责“抖音作品下载”；[Easy WebBridge](https://github.com/xxjrq/easy-webbridge) 负责连接真实浏览器。两者通过本机 HTTP Bridge 配合，不引用作者电脑上的绝对路径。Easy WebBridge 安装一次后，可以被多个业务 Skill 共用。

## 安装

### 1. 安装 Easy WebBridge（只需一次）

```bash
git clone https://github.com/xxjrq/easy-webbridge.git
cd easy-webbridge
npm install
node cli/easy-webbridge.mjs start
```

在 Chrome、Edge、QQ 浏览器或其他 Chromium 浏览器中加载 Easy WebBridge 的 `extension/` 文件夹，并确认 Bridge 能看到该浏览器。公开作品可直接处理；如果抖音显示登录墙，再在这个浏览器里登录抖音。

### 2. 安装本 Skill

```bash
npx skills add xxjrq/douyin-download-webbridge
```

没有安装器时，也可以手动放到通用 Skill 目录：

```bash
git clone https://github.com/xxjrq/douyin-download-webbridge.git ~/.agents/skills/douyin-download-webbridge
```

## 直接使用

先确认 Easy WebBridge 已经连接浏览器，然后对任意支持 Agent 说：

```text
使用 douyin-download-webbridge 下载这个抖音作品：https://v.douyin.com/xxxxx/
```

也可以直接运行脚本：

```bash
python3 scripts/douyin_download.py "https://v.douyin.com/xxxxx/"
python3 scripts/douyin_download.py "https://www.douyin.com/video/1234567890" -o ~/Downloads/douyin
python3 scripts/douyin_download.py 7669474316672716066 --browser 自媒体
python3 scripts/douyin_download.py "<链接>" --quality worst
```

参数说明：

| 参数 | 作用 |
| --- | --- |
| 第一个参数 | 抖音分享短链、长链或作品 ID |
| `-o, --out` | 输出目录，默认 `~/Downloads/DouyinDownloads` |
| `--browser` | 浏览器显示名，默认 `自媒体` |
| `--quality best` | 默认模式，选择最高可用清晰度 |
| `--quality worst` | 选择最小档，仅适合快速预览 |

## 运行前需要什么

- Python 3.9+、Node.js 20+ 和 `curl`。
- Easy WebBridge Bridge 正在运行，默认地址为 `127.0.0.1:17777`。
- 至少一个 Chromium 浏览器在线；抖音出现登录墙时需要在该浏览器登录。
- macOS 默认使用 `/opt/homebrew/bin/ffprobe` 检查视频；没有 ffprobe 时仍可下载，但不会输出媒体校验信息。

脚本会先检查 CLI、Bridge 和在线浏览器。找不到默认名为“自媒体”的浏览器时，会提示并使用第一个在线环境；无法连接时直接停止，不会偷偷打开新的浏览器。

## 文件输出

- 视频保存为 `.mp4`，文件名来自作品标题。
- 图文保存为 `_01.jpeg`、`_02.jpeg` 等顺序文件，优先原图，其次 JPEG，再次 WebP。
- 默认输出目录是 `~/Downloads/DouyinDownloads`，也可以用 `-o` 指定。
- 抖音直链有时效，遇到 403 时重新运行一次即可；不要长期保存直链。

## 常见问题

### 为什么没有拿到视频？

先确认浏览器已经登录抖音、Bridge 在线，并且页面没有登录墙或风控验证。脚本不绕过滑块、验证码或访问限制。

### 为什么图文不是一张文件？

图文作品会按正文图片逐张保存，多图文件名带 `_01`、`_02` 编号，方便继续整理。

### 能不能批量下载？

当前入口一次处理一个作品。批量任务可以由 Agent 逐个调用，并继续复用同一个浏览器环境和任务标签组，避免打开大量窗口。

### 会自动发布到抖音吗？

不会。本 Skill 只下载和保存文件，不上传、不发布、不评论、不私信，也不读取发布后的数据。

## 版权与使用边界

请只下载你自己发布、已获授权或依法可以保存的内容，并遵守抖音服务条款、版权和隐私要求。不要把下载功能用于绕过访问控制、批量抓取他人隐私或重新分发未经授权的作品。

## 开源协议

[MIT](LICENSE)
