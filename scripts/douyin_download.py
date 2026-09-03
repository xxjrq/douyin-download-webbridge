#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频 / 图文下载器（Easy WebBridge 路径）

无需 TikHub / redfox API key，复用本地已登录浏览器抓取直链。

用法:
    python3 douyin_download.py "https://v.douyin.com/xxxxx/"
    python3 douyin_download.py 7669474316672716066
    python3 douyin_download.py "<链接>" -o /Users/myd/Downloads/QoderVideos
    python3 douyin_download.py "<链接>" --browser 自媒体
    python3 douyin_download.py "<链接>" --quality worst   # 只下最小体积（快速预览）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

# ---------- 常量（改这里即可） ----------

FFMPEG_BIN = "/opt/homebrew/bin/ffprobe"          # homebrew 的 ffmpeg 不在默认 PATH
BRIDGE_URL = "http://127.0.0.1:17777"
BRIDGE_TOKEN_FILE = os.path.expanduser("~/.easy-webbridge/bridge-token")
DEFAULT_OUT_DIR = "/Users/myd/Downloads/QoderVideos"

# easy-webbridge CLI 候选路径（按优先级探测）
CLI_CANDIDATES = [
    os.path.expanduser(
        "~/develop/selfmedia/skills/easy-webbridge/skills/easy-webbridge/scripts/easy-webbridge.mjs"
    ),
    os.path.expanduser(
        "~/.workbuddy/skills/easy-webbridge-browser__skillhub/scripts/easy-webbridge.mjs"
    ),
]

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"

OK, FAIL, INFO, WARN = "[OK]", "[FAIL]", "[..]", "[!!]"


def log(symbol, msg):
    print(f"{symbol} {msg}", flush=True)


def run(cmd, desc=""):
    """执行命令，返回 (returncode, stdout, stderr)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout: {desc}"
    except FileNotFoundError as e:
        return -1, "", str(e)


def find_cli():
    for path in CLI_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def find_node():
    for node in [
        os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2-2/bin/node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ]:
        if os.path.isfile(node):
            return node
    return "node"  # 交给 PATH


# ---------- 前置检查 ----------

def check_bridge():
    """确认 bridge 服务在线，返回在线浏览器列表"""
    if not os.path.isfile(BRIDGE_TOKEN_FILE):
        log(FAIL, f"找不到 bridge token: {BRIDGE_TOKEN_FILE}")
        return None
    with open(BRIDGE_TOKEN_FILE) as f:
        token = f.read().strip()
    rc, out, err = run(
        ["curl", "-s", "--max-time", "5", "-H", f"Authorization: Bearer {token}",
         f"{BRIDGE_URL}/v1/browsers"]
    )
    if rc != 0 or not out:
        log(FAIL, "Easy WebBridge 服务未运行（127.0.0.1:17777 无响应）")
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        log(FAIL, f"bridge 返回非 JSON: {out[:200]}")
        return None
    browsers = [b for b in data.get("browsers", []) if b.get("online")]
    return browsers


# ---------- 解析输入 ----------

def parse_input(user_input):
    """返回 (aweme_id, kind)，kind ∈ {video, note}；失败返回 (None, None)"""
    s = user_input.strip()

    # 纯数字 = modal_id
    if re.fullmatch(r"\d{10,25}", s):
        return s, "video"

    # 提取 URL
    m = re.search(r"https?://[^\s]+", s)
    url = m.group(0) if m else s

    # 已经是长链
    long_m = re.search(r"douyin\.com/(share/)?(video|note)/(\d+)", url)
    if long_m:
        return long_m.group(3), long_m.group(2)

    # 短链：跟随重定向拿真实地址
    rc, out, _ = run(
        ["curl", "-sIL", url, "-o", "/dev/null", "-w", "%{url_effective}",
         "-A", UA_MOBILE]
    )
    effective = out.strip().splitlines()[-1] if out.strip() else ""
    if not effective:
        log(FAIL, f"短链解析失败，没拿到跳转地址: {url}")
        return None, None
    log(INFO, f"短链 → {effective}")

    m2 = re.search(r"douyin\.com/(share/)?(video|note)/(\d+)", effective)
    if m2:
        return m2.group(3), m2.group(2)

    log(FAIL, f"无法从地址里提取作品 ID: {effective}")
    return None, None


# ---------- 浏览器操作 ----------

def wb(cli, node, browser_id, action, payload=None):
    """调用 easy-webbridge CLI"""
    cmd = [node, cli]
    if action == "navigate":
        url = payload.pop("_url")
        cmd += ["navigate", browser_id, url]
        for k in ("session", "group-title"):
            if k in payload:
                cmd += [f"--{k}", payload[k]]
        if payload.get("new_tab"):
            cmd.append("--new-tab")
    else:
        cmd += ["command", browser_id, action, json.dumps(payload, ensure_ascii=False)]
    rc, out, err = run(cmd)
    if rc != 0:
        log(FAIL, f"CLI {action} 执行失败: {err[:300]}")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        log(FAIL, f"CLI {action} 返回非 JSON: {out[:300]}")
        return None


def navigate_to(cli, node, browser_id, aweme_id, session):
    url = f"https://www.douyin.com/video/{aweme_id}"
    res = wb(cli, node, browser_id, "navigate", {
        "_url": url, "new_tab": True, "session": session, "group-title": "抖音下载",
    })
    if not res or not res.get("ok"):
        return None
    r = res.get("result", {})
    log(OK, f"已打开作品页 tabId={r.get('tabId')}")
    return r.get("tabId")


def evaluate(cli, node, browser_id, tab_id, code, wait=0):
    if wait:
        time.sleep(wait)
    res = wb(cli, node, browser_id, "evaluate", {"tabId": tab_id, "code": code})
    if not res or not res.get("ok"):
        return None
    return res.get("result")


# ---------- 取直链 ----------

def fetch_video_detail(cli, node, browser_id, tab_id, aweme_id):
    """在页面内 fetch detail 接口，拿全部码率档位 + 标题。
    注意：不要直接读 video.src —— 那只给 540p。"""
    js = (
        '(async()=>{try{'
        f'const url="https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}";'
        'const j=await(await fetch(url,{credentials:"include"})).json();'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({err:"no aweme_detail"});'
        'const v=d.video||{};'
        'const brs=(v.bit_rate||[]).map(b=>({gear:b.gear_name,w:(b.play_addr||{}).width||0,'
        'h:(b.play_addr||{}).height||0,url:((b.play_addr||{}).url_list||[])[0]||""})).filter(b=>b.url);'
        'return JSON.stringify({desc:d.desc||"",duration:v.duration||0,brs:brs})'
        '}catch(e){return JSON.stringify({err:String(e)})}})()'
    )
    raw = evaluate(cli, node, browser_id, tab_id, js, wait=3)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log(FAIL, f"detail 解析失败: {str(raw)[:300]}")
        return None


def detect_kind(cli, node, browser_id, tab_id):
    """打开页面后按实际内容判定类型。

    不能只信短链路径：图文作品的分享链接也可能走 /share/video/，
    只有打开后看页面实际跳转与有无 video 元素才可靠。
    """
    js = (
        '(()=>{const v=document.querySelector("video");'
        'return JSON.stringify({href:location.href,'
        'hasVideo:!!v,vidCount:document.querySelectorAll("video").length})})()'
    )
    raw = evaluate(cli, node, browser_id, tab_id, js, wait=2)
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "video"
    if "/note/" in (d.get("href") or ""):
        return "note"
    if not d.get("hasVideo"):
        return "note"
    return "video"


def _img_key(url):
    """提取图片唯一 ID，用于把 detail 的图片列表和 DOM 的带签名 URL 对上。

    抖音图 URL 形如 /tos-cn-i-xxxx/<ID>~tplv-...?x-signature=...
    ID 就是 <ID> 这一段。
    """
    m = re.search(r"/([A-Za-z0-9_-]{20,})[~?]", url or "")
    return m.group(1) if m else None


def fetch_note_detail(cli, node, browser_id, tab_id, aweme_id):
    """优先走 detail 接口取正文图，避免 DOM 抓取混入推荐位/评论的小图。

    返回每张图的**全部** url_list 档位（通常有 webp / jpeg 两种），
    由 pick_image 挑选最清晰的；只取 url_list[0] 会固定拿到压缩率更高的 webp。

    注意：不要用 download_url_list —— 那是带水印版本（抖音「保存图片」用的）。
    """
    js = (
        '(async()=>{try{'
        f'const url="https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}";'
        'const j=await(await fetch(url,{credentials:"include"})).json();'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({err:"no aweme_detail"});'
        'const ims=(d.images||[]).map(im=>({w:im.width||0,h:im.height||0,'
        'urls:im.url_list||[]})).filter(x=>x.urls.length);'
        'return JSON.stringify({desc:d.desc||"",imgs:ims})'
        '}catch(e){return JSON.stringify({err:String(e)})}})()'
    )
    raw = evaluate(cli, node, browser_id, tab_id, js, wait=2)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def fetch_note_images(cli, node, browser_id, tab_id):
    """从 DOM 提取图片 URL，主要用于捞 ~noop 原图。

    只有当前轮播显示的那张图才会渲染 ~noop 原图 URL，其余是压缩档 —— 所以
    翻不动轮播时（实测点击/键盘都无效）只能拿到部分原图，拿不到就退回 jpeg。
    """
    js = (
        '(()=>{const out=[...document.querySelectorAll("img")]'
        '.map(i=>i.src||i.getAttribute("data-src")||"")'
        '.filter(s=>/aweme-images|~noop|tplv-dy-orig|image-cut-tos/.test(s))'
        '.filter(s=>!/avatar|100x100|cropcenter|resize/.test(s));'
        'return JSON.stringify([...new Set(out)])})()'
    )
    raw = evaluate(cli, node, browser_id, tab_id, js, wait=2)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def get_title(cli, node, browser_id, tab_id):
    raw = evaluate(cli, node, browser_id, tab_id, "document.title")
    if not raw:
        return ""
    return re.sub(r"\s*-\s*抖音\s*$", "", str(raw)).strip()


def _codec_rank(url):
    """从直链 cs 参数推断编码：cs=0 是 H.264，cs=2 是 HEVC。
    同分辨率下优先 H.264 —— 剪辑工具链兼容性最好。"""
    m = re.search(r"[?&]cs=(\d+)", url or "")
    return int(m.group(1)) if m else 9


def pick_bitrate(brs, quality="best"):
    """按分辨率降序选档；分辨率相同时优先 H.264（cs 值小的）"""
    if not brs:
        return None

    def key(b):
        area = (b.get("w") or 0) * (b.get("h") or 0)
        return (area, -_codec_rank(b.get("url")))

    ordered = sorted(brs, key=key)
    pick = ordered[-1] if quality == "best" else ordered[0]
    pick["codec"] = "h264" if _codec_rank(pick.get("url")) == 0 else "hevc"
    return pick


# ---------- 下载 ----------

def safe_filename(name, fallback="douyin"):
    """清理文件名：去话题标签、emoji、非法字符"""
    name = re.sub(r"#\S+", "", name)                      # 去 #话题
    name = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", name)    # 只留中英数/下划线/连字符/空格
    name = re.sub(r"\s+", " ", name).strip(" -_")
    return name[:40] or fallback


def download(url, out_path, referer=REFERER):
    rc, out, err = run(
        ["curl", "-s", "-A", UA_MOBILE, "-e", referer, url, "-o", out_path,
         "-w", "%{http_code} %{size_download}"]
    )
    parts = out.strip().split()
    if len(parts) >= 2 and parts[0] == "200":
        size = int(parts[1])
        log(OK, f"下载完成 {size/1024/1024:.2f} MB → {os.path.basename(out_path)}")
        return size > 0
    log(FAIL, f"下载失败 http={parts[0] if parts else '?'} {err[:200]}")
    return False


def probe(path):
    if not os.path.isfile(FFMPEG_BIN):
        return None
    rc, out, _ = run(
        [FFMPEG_BIN, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path]
    )
    if rc != 0 or not out:
        return None
    try:
        d = json.loads(out)
        fmt = d.get("format", {})
        vs = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
        return {
            "w": vs.get("width"), "h": vs.get("height"), "codec": vs.get("codec_name"),
            "dur": round(float(fmt.get("duration") or 0), 1),
            "mb": round(int(fmt.get("size") or 0) / 1024 / 1024, 2),
        }
    except (json.JSONDecodeError, ValueError):
        return None


# ---------- 两个下载分支 ----------

def try_video(cli, node, browser_id, tab_id, aweme_id, args):
    """视频分支：从 detail 接口取全码率档位，选最高清（同分辨率优先 H.264）"""
    detail = fetch_video_detail(cli, node, browser_id, tab_id, aweme_id)
    if not detail or detail.get("err") or not detail.get("brs"):
        log(WARN, f"视频取流失败: {(detail or {}).get('err', '无码率档位')}")
        return []

    brs = detail["brs"]
    log(INFO, "可用档位: " + ", ".join(f'{b["w"]}x{b["h"]}' for b in brs))
    pick = pick_bitrate(brs, args.quality)
    log(OK, f"选中 {pick['w']}x{pick['h']} ({pick.get('gear', '')}) "
            f"编码={pick.get('codec', '?')}")

    title = detail.get("desc") or get_title(cli, node, browser_id, tab_id)
    base = safe_filename(title, aweme_id)
    out_path = os.path.join(args.out, f"{base}.mp4")
    if not download(pick["url"], out_path):
        return []

    info = probe(out_path)
    if info:
        log(OK, f"校验 {info['w']}x{info['h']} {info['codec']} "
                f"| {info['dur']}s | {info['mb']}MB")
    return [out_path]


def pick_image(urls, noop_map):
    """在单张图的档位里挑最清晰的：原图(noop) > JPEG > WebP。

    实测同分辨率（1080×1440）下：q75.webp 53KB / q75.jpeg 113KB，
    JPEG 压缩损失明显更小、文字更清楚，且通用性最好。
    """
    key = _img_key(urls[0])
    if key and key in noop_map:
        return noop_map[key], "原图"
    jpeg = next((u for u in urls if ".jpeg" in u or ".jpg" in u), None)
    if jpeg:
        return jpeg, "高清"
    return urls[0], "标准"


def try_note(cli, node, browser_id, tab_id, aweme_id, args):
    """图文分支：detail 接口定图片清单，逐张挑最清晰档位落地"""
    imgs, title = [], ""

    detail = fetch_note_detail(cli, node, browser_id, tab_id, aweme_id)
    dom_imgs = fetch_note_images(cli, node, browser_id, tab_id)

    # DOM 里带签名的 ~noop 原图（按图片 ID 索引）
    noop_map = {}
    for u in dom_imgs:
        if "~noop" in u:
            k = _img_key(u)
            if k:
                noop_map[k] = u

    if detail and not detail.get("err") and detail.get("imgs"):
        title = detail.get("desc") or ""
        for item in detail["imgs"]:
            url, tier = pick_image(item["urls"], noop_map)
            imgs.append((url, tier))
        log(INFO, f"detail 接口取到 {len(imgs)} 张正文图")
    elif dom_imgs:
        log(WARN, "detail 无 images 字段，退回 DOM 抓取（可能混入推荐位小图）")
        imgs = [(u, "未知") for u in dom_imgs]

    if not imgs:
        log(FAIL, "没提取到图文大图（页面未加载完，或类型判断有误）")
        return []

    if not title:
        title = get_title(cli, node, browser_id, tab_id)
    base = safe_filename(title, aweme_id)

    tiers = {}
    for _, t in imgs:
        tiers[t] = tiers.get(t, 0) + 1
    log(INFO, f"图文共 {len(imgs)} 张 | 档位: "
              + " ".join(f"{k}×{v}" for k, v in tiers.items()))

    saved = []
    for i, (url, _) in enumerate(imgs, 1):
        if ".jpeg" in url or ".jpg" in url:
            ext = ".jpeg"
        elif ".png" in url:
            ext = ".png"
        else:
            ext = ".webp"
        out_path = os.path.join(args.out, f"{base}_{i:02d}{ext}")
        if download(url, out_path):
            saved.append(out_path)
    return saved


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="抖音视频/图文下载（Easy WebBridge）")
    ap.add_argument("input", help="抖音分享短链 / 长链 / modal_id")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT_DIR, help="输出目录")
    ap.add_argument("--browser", default="自媒体", help="浏览器显示名（默认：自媒体）")
    ap.add_argument("--quality", default="best", choices=["best", "worst"], help="清晰度")
    args = ap.parse_args()

    # 1. 依赖探测
    cli = find_cli()
    if not cli:
        log(FAIL, "找不到 easy-webbridge CLI，检查路径：\n  " + "\n  ".join(CLI_CANDIDATES))
        return 1
    node = find_node()
    log(OK, f"CLI: {cli}")

    # 2. bridge + 浏览器
    browsers = check_bridge()
    if not browsers:
        return 1
    target = next((b for b in browsers if b.get("displayName") == args.browser), None)
    if not target:
        target = browsers[0]
        log(WARN, f"没找到浏览器「{args.browser}」，改用「{target.get('displayName')}」")
    browser_id = target["browserId"]
    log(OK, f"浏览器: {target.get('displayName')} ({browser_id})")

    # 3. 解析输入（类型只是初判，以打开后的实际页面为准）
    aweme_id, kind = parse_input(args.input)
    if not aweme_id:
        return 1

    # 4. 打开页面
    session = f"douyin-dl-{time.strftime('%m%d%H%M%S')}"
    tab_id = navigate_to(cli, node, browser_id, aweme_id, session)
    if not tab_id:
        return 1

    kind = detect_kind(cli, node, browser_id, tab_id)
    log(OK, f"作品 ID: {aweme_id} | 实际类型: {'图文' if kind == 'note' else '视频'}")

    os.makedirs(args.out, exist_ok=True)
    saved = []

    try:
        # 5. 视频分支
        if kind != "note":
            saved += try_video(cli, node, browser_id, tab_id, aweme_id, args)

        # 6. 图文分支：初判为图文，或视频取流失败时兜底
        if not saved:
            if kind != "note":
                log(WARN, "视频取流失败，改为按图文提取")
            saved += try_note(cli, node, browser_id, tab_id, aweme_id, args)
    finally:
        # 6. 清理标签组
        wb(cli, node, browser_id, "close_session", {"session": session})
        log(INFO, "已关闭浏览器标签组")

    if not saved:
        log(FAIL, "没有成功保存任何文件")
        return 1
    log(OK, f"完成，共 {len(saved)} 个文件 → {args.out}")
    for p in saved:
        print(f"    {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
