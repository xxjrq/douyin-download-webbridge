<div align="center">

<img src="assets/icon-512.png" width="112" height="112" alt="Free Douyin video and image downloader icon">

# Free Douyin Downloads for Videos and Images

## Free · no extra downloader account · no third-party API key

Give an Agent a Douyin link and it saves the video or image post locally. You do not need to register with a third-party downloader or request an API key. Public works can usually be handled directly; sign in to Douyin only if Douyin itself shows a login wall.

[简体中文](README.md) | [English](README.en.md)

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-2563EB?style=flat-square)](https://agentskills.io/)
[![Easy WebBridge](https://img.shields.io/badge/runtime-Easy%20WebBridge-111827?style=flat-square)](https://github.com/xxjrq/easy-webbridge)
[![GitHub Stars](https://img.shields.io/github/stars/xxjrq/douyin-download-webbridge?style=flat-square)](https://github.com/xxjrq/douyin-download-webbridge/stargazers)
[![skills.sh](https://skills.sh/b/xxjrq/douyin-download-webbridge)](https://skills.sh/xxjrq/douyin-download-webbridge)
[![License](https://img.shields.io/badge/license-MIT-16A34A?style=flat-square)](LICENSE)

</div>

## Highlights

- **Free and open source:** no per-download charge.
- **No extra login:** no third-party downloader account; it keeps using your own browser.
- **No third-party key:** no TikHub, redfox, or similar content API token.
- **Videos and images:** selects the highest available video quality and saves multi-image posts in order.

## What it does

- Downloads Douyin videos by reading available bitrate variants from the work detail page.
- Chooses the highest resolution by default and prefers H.264 when resolutions match.
- Downloads Douyin image posts from the detail image list, with numbered files for multi-image posts.
- Accepts share links, long URLs, and numeric work IDs.
- Keeps each run in its own browser task group and closes only that group afterward.
- Creates readable filenames from the work title and prints saved paths plus basic media information.
- Free to use and does not require TikHub, redfox, or another third-party API key.

“No extra login” means no third-party downloader account. “No key” means no token for a third-party content API. The local runtime still needs Easy WebBridge, Node.js, Python, and a Chromium browser. If Douyin shows a login wall, sign in to Douyin in that browser.

This is a downloader and organizer, not an editor or watermark-removal service. It saves content you are authorized to use and does not upload, publish, or operate your account.

## How it works with Easy WebBridge

```text
Claude Code / Codex / OpenCode / WorkBuddy
                    |
       douyin-download-webbridge Skill
              download + organize
                    |
          Easy WebBridge 127.0.0.1:17777
                    |
       browser extension + public Douyin work
```

This repository owns the Douyin download workflow. [Easy WebBridge](https://github.com/xxjrq/easy-webbridge) connects the real browser. They are independent repositories linked through the local HTTP Bridge, with no author-specific filesystem path. Install Easy WebBridge once and reuse it from other business Skills.

## Install

### 1. Install Easy WebBridge once

```bash
git clone https://github.com/xxjrq/easy-webbridge.git
cd easy-webbridge
npm install
node cli/easy-webbridge.mjs start
```

Load the Easy WebBridge `extension/` directory in a Chromium browser, then confirm that the Bridge sees it. Public works can usually be handled directly; sign in to Douyin only when Douyin shows a login wall.

### 2. Install this Skill

```bash
npx skills add xxjrq/douyin-download-webbridge
```

Universal manual location:

```bash
git clone https://github.com/xxjrq/douyin-download-webbridge.git ~/.agents/skills/douyin-download-webbridge
```

## Use it

After Easy WebBridge is connected, ask any compatible Agent:

```text
Use douyin-download-webbridge to download this Douyin work: https://v.douyin.com/xxxxx/
```

Or run the script directly:

```bash
python3 scripts/douyin_download.py "https://v.douyin.com/xxxxx/"
python3 scripts/douyin_download.py "https://www.douyin.com/video/1234567890" -o ~/Downloads/douyin
python3 scripts/douyin_download.py 7669474316672716066 --browser Creator
python3 scripts/douyin_download.py "<link>" --quality worst
```

Options:

| Option | Purpose |
| --- | --- |
| First argument | Douyin share link, long URL, or work ID |
| `-o, --out` | Output directory; defaults to `~/Downloads/DouyinDownloads` |
| `--browser` | Browser display name; defaults to `自媒体` |
| `--quality best` | Default mode; choose the highest available quality |
| `--quality worst` | Choose the smallest variant for a quick preview |

## Requirements

- Python 3.9+, Node.js 20+, and `curl`.
- Easy WebBridge running at `127.0.0.1:17777` by default.
- At least one Chromium browser online; sign in to Douyin if the page shows a login wall.
- On macOS, `/opt/homebrew/bin/ffprobe` is used for video checks. Downloads still work without ffprobe, but media inspection is skipped.

The script checks the CLI, Bridge, and online browsers before opening the work. If the browser named `自媒体` is unavailable, it reports the fallback browser it selected. It never silently starts a new browser.

## Output

- Videos are saved as `.mp4` files named from the work title.
- Image posts are saved as `_01.jpeg`, `_02.jpeg`, and so on, preferring original, JPEG, then WebP variants.
- The default output directory is `~/Downloads/DouyinDownloads`; use `-o` to change it.
- Douyin media URLs expire. If a download returns 403, run the command again to obtain a fresh URL.

## Boundaries

The Skill stops at login walls and risk-control pages. It does not bypass CAPTCHA, access controls, or platform restrictions. It does not upload, publish, comment, send messages, or collect post-publication metrics.

Only download content you created, have permission to use, or are otherwise legally allowed to save. Follow Douyin's terms, copyright rules, and privacy requirements.

## License

[MIT](LICENSE)
