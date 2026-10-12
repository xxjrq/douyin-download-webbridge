#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费抖音下载，支持视频和图文图片（Easy WebBridge 路径）

无需注册第三方下载站，也无需 TikHub / redfox API Key。

用法:
    python3 douyin_download.py "https://v.douyin.com/xxxxx/"
    python3 douyin_download.py 7669474316672716066
    python3 douyin_download.py "<链接>" -o ~/Downloads/DouyinDownloads
    python3 douyin_download.py "<链接>" --browser 自媒体
    python3 douyin_download.py "<链接>" --quality worst   # 只下最小体积（快速预览）
    python3 douyin_download.py "<链接>" --audio-only     # 只提取作品音轨并标准化为 MP3
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ---------- 常量（改这里即可） ----------

FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"
BRIDGE_URL = "http://127.0.0.1:17777"
DEFAULT_OUT_DIR = os.path.expanduser("~/Downloads/DouyinDownloads")
BRIDGE_TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".easy-webbridge", "bridge-token")

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"
IMAGE_AWEME_TYPES = {68}

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


def bridge_request(path, body=None, timeout=10):
    """调用 EasyBR 内置的本机 WebBridge HTTP API。"""
    if not os.path.isfile(BRIDGE_TOKEN_FILE):
        raise FileNotFoundError(f"找不到 Bridge token: {BRIDGE_TOKEN_FILE}")
    with open(BRIDGE_TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------- 前置检查 ----------

def check_bridge():
    """确认 bridge 服务在线，返回在线浏览器列表"""
    try:
        data = bridge_request("/v1/browsers", timeout=5)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        log(FAIL, f"EasyBR 内置 Easy WebBridge 未运行或无法访问：{e}")
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

def wb(browser_id, action, payload=None):
    """调用 EasyBR 内置 Easy WebBridge API。"""
    try:
        return bridge_request(f"/v1/browsers/{browser_id}/commands", {
            "action": action, "args": payload or {},
        })
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        log(FAIL, f"Easy WebBridge {action} 调用失败：{e}")
        return None


def navigate_to(browser_id, aweme_id, session):
    url = f"https://www.douyin.com/video/{aweme_id}"
    res = wb(browser_id, "navigate", {
        "url": url, "newTab": True, "session": session, "groupTitle": "抖音下载",
    })
    if not res or not res.get("ok"):
        return None
    r = res.get("result", {})
    log(OK, f"已打开作品页 tabId={r.get('tabId')}")
    return r.get("tabId")


def evaluate(browser_id, tab_id, code, wait=0):
    if wait:
        time.sleep(wait)
    res = wb(browser_id, "evaluate", {"tabId": tab_id, "code": code})
    if not res or not res.get("ok"):
        return None
    return res.get("result")


# ---------- 取直链 ----------

def fetch_video_detail(browser_id, tab_id, aweme_id):
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
    raw = evaluate(browser_id, tab_id, js, wait=3)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log(FAIL, f"detail 解析失败: {str(raw)[:300]}")
        return None


def classify_media_probe(probe):
    """根据详情接口的媒体特征判型；无法确认时返回 None。"""
    if not isinstance(probe, dict) or not probe.get("detailReady"):
        return None
    if probe.get("hasImages") or probe.get("awemeType") in IMAGE_AWEME_TYPES:
        return "note"
    if probe.get("hasVideo") or probe.get("awemeType") == 0:
        return "video"
    return None


def fetch_kind_probe(browser_id, tab_id, aweme_id, wait=0):
    """从 detail 接口读取稳定的媒体类型特征，不依赖页面组件挂载时机。"""
    js = (
        '(async()=>{try{'
        f'const url="https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}";'
        'const j=await(await fetch(url,{credentials:"include"})).json();'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({detailReady:false});'
        'const ip=d.image_post_info||{};'
        'const imageLists=[d.images,d.image_list,d.image_infos,d.original_images,'
        'ip.images,ip.image_list,ip.image_infos];'
        'const hasImages=imageLists.some(x=>Array.isArray(x)&&x.length>0);'
        'const v=d.video||{};'
        'const addrs=[v.play_addr,v.play_addr_h264,v.play_addr_265,v.download_addr];'
        'const hasVideo=(Array.isArray(v.bit_rate)&&v.bit_rate.some(b=>'
        'Array.isArray((b.play_addr||{}).url_list)&&(b.play_addr||{}).url_list.length>0))||'
        'addrs.some(a=>a&&Array.isArray(a.url_list)&&a.url_list.length>0);'
        'return JSON.stringify({detailReady:true,awemeType:d.aweme_type,'
        'hasImages:hasImages,hasVideo:hasVideo})'
        '}catch(e){return JSON.stringify({detailReady:false,err:String(e)})}})()'
    )
    raw = evaluate(browser_id, tab_id, js, wait=wait)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def detect_kind(browser_id, tab_id, aweme_id):
    """打开页面后按详情接口判型，页面 URL 和 DOM 只作兜底。

    页面首屏可能先没有 ``<video>``，把“元素尚未挂载”当成图文会让视频
    错走图片分支。详情接口暂时不可用时默认先尝试视频；主流程随后仍会
    自动回退到图文，因此不会牺牲真实图文作品。
    """
    for wait in (0, 1, 2):
        kind = classify_media_probe(
            fetch_kind_probe(browser_id, tab_id, aweme_id, wait=wait)
        )
        if kind:
            return kind

    js = (
        '(()=>JSON.stringify({href:location.href,'
        'hasVideo:!!document.querySelector("video")}))()'
    )
    raw = evaluate(browser_id, tab_id, js)
    try:
        page = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        page = {}
    if "/note/" in (page.get("href") or ""):
        return "note"
    return "video"


def _img_key(url):
    """提取图片唯一 ID，用于把 detail 的图片列表和 DOM 的带签名 URL 对上。

    抖音图 URL 形如 /tos-cn-i-xxxx/<ID>~tplv-...?x-signature=...
    ID 就是 <ID> 这一段。
    """
    m = re.search(r"/([A-Za-z0-9_-]{20,})[~?]", url or "")
    return m.group(1) if m else None


def fetch_note_detail(browser_id, tab_id, aweme_id):
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
    raw = evaluate(browser_id, tab_id, js, wait=2)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def pick_audio_source(detail):
    """选择作品可播放音轨。

    图文作品的背景音乐常放在 ``video.play_addr``，即使 ``music.play_url``
    因地区版权限制为空；普通视频的同一字段则是带完整混音的低码率视频。
    两者都可以交给 ffmpeg 提取音轨。
    """
    if not isinstance(detail, dict):
        return None
    for key in ("video_play_urls", "music_play_urls", "music_original_urls"):
        urls = detail.get(key)
        if isinstance(urls, list):
            url = next((item for item in urls if isinstance(item, str) and item.startswith("http")), None)
            if url:
                return url
    return None


def fetch_audio_detail(browser_id, tab_id, aweme_id):
    """从作品详情提取可供 ffmpeg 读取的音轨源及描述信息。"""
    js = (
        '(async()=>{try{'
        f'const url="https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}";'
        'const j=await(await fetch(url,{credentials:"include"})).json();'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({err:"no aweme_detail"});'
        'const v=d.video||{},m=d.music||{},p=m.play_url||{};'
        'let extra={};try{extra=typeof m.extra==="string"?JSON.parse(m.extra):(m.extra||{})}catch(_){}'
        'const images=Array.isArray(d.images)?d.images:[];'
        'return JSON.stringify({desc:d.desc||"",aweme_type:d.aweme_type,'
        'kind:images.length?"note":"video",music_title:m.title||"",music_author:m.author||"",'
        'offline_desc:m.offline_desc||"",'
        'video_play_urls:((v.play_addr||{}).url_list||[]),'
        'music_play_urls:(p.url_list||[]),'
        'music_original_urls:extra.original_song_url?[extra.original_song_url]:[]})'
        '}catch(e){return JSON.stringify({err:String(e)})}})()'
    )
    raw = evaluate(browser_id, tab_id, js, wait=2)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def fetch_note_images(browser_id, tab_id):
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
    raw = evaluate(browser_id, tab_id, js, wait=2)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def get_title(browser_id, tab_id):
    raw = evaluate(browser_id, tab_id, "document.title")
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
    if not os.path.isfile(FFPROBE_BIN):
        return None
    rc, out, _ = run(
        [FFPROBE_BIN, "-v", "error", "-print_format", "json",
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


def probe_audio(path):
    if not os.path.isfile(FFPROBE_BIN):
        return None
    rc, out, _ = run(
        [FFPROBE_BIN, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path]
    )
    if rc != 0 or not out:
        return None
    try:
        data = json.loads(out)
        stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
        duration = float((data.get("format") or {}).get("duration") or 0)
        return {
            "codec": stream.get("codec_name"),
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "dur": round(duration, 3),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


# ---------- 两个下载分支 ----------

def try_audio_only(browser_id, tab_id, aweme_id, args):
    """提取视频混音或图文配乐，统一输出 48kHz 双声道 MP3。"""
    detail = fetch_audio_detail(browser_id, tab_id, aweme_id)
    source_url = pick_audio_source(detail)
    if not detail or detail.get("err") or not source_url:
        reason = (detail or {}).get("offline_desc") or (detail or {}).get("err") or "作品详情没有可播放音轨"
        log(FAIL, f"没有提取到作品配乐: {reason}")
        return [], detail or {}
    if not os.path.isfile(FFMPEG_BIN):
        log(FAIL, f"找不到 ffmpeg: {FFMPEG_BIN}")
        return [], detail

    stamp = int(time.time() * 1000)
    source_path = os.path.join(args.out, f".douyin-{aweme_id}-{stamp}.source")
    out_path = os.path.join(args.out, f"douyin-{aweme_id}-{stamp}-original.mp3")
    try:
        if not download(source_url, source_path):
            return [], detail
        rc, _, err = run([
            FFMPEG_BIN, "-y", "-v", "error", "-i", source_path, "-vn",
            "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-q:a", "2", out_path,
        ], "提取作品音轨")
        if rc != 0:
            log(FAIL, f"音频转码失败: {err.strip()[:400]}")
            return [], detail
        info = probe_audio(out_path)
        if not info or info["dur"] <= 0 or info["sample_rate"] != 48000 or info["channels"] != 2:
            log(FAIL, "音频校验失败，未得到 48kHz 双声道有效音轨")
            if os.path.isfile(out_path):
                os.unlink(out_path)
            return [], detail
        log(OK, f"音频校验 {info['codec']} | {info['sample_rate']}Hz | "
                f"{info['channels']}ch | {info['dur']}s")
        return [out_path], detail
    finally:
        if os.path.isfile(source_path):
            os.unlink(source_path)


def try_video(browser_id, tab_id, aweme_id, args):
    """视频分支：从 detail 接口取全码率档位，选最高清（同分辨率优先 H.264）"""
    detail = fetch_video_detail(browser_id, tab_id, aweme_id)
    if not detail or detail.get("err") or not detail.get("brs"):
        log(WARN, f"视频取流失败: {(detail or {}).get('err', '无码率档位')}")
        return []

    brs = detail["brs"]
    log(INFO, "可用档位: " + ", ".join(f'{b["w"]}x{b["h"]}' for b in brs))
    pick = pick_bitrate(brs, args.quality)
    log(OK, f"选中 {pick['w']}x{pick['h']} ({pick.get('gear', '')}) "
            f"编码={pick.get('codec', '?')}")

    title = detail.get("desc") or get_title(browser_id, tab_id)
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


def try_note(browser_id, tab_id, aweme_id, args):
    """图文分支：detail 接口定图片清单，逐张挑最清晰档位落地"""
    imgs, title = [], ""

    detail = fetch_note_detail(browser_id, tab_id, aweme_id)
    dom_imgs = fetch_note_images(browser_id, tab_id)

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
        title = get_title(browser_id, tab_id)
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
    ap.add_argument("--audio-only", action="store_true", help="只提取作品音轨，输出 48kHz 双声道 MP3")
    args = ap.parse_args()

    # 1. EasyBR 内置 Bridge + 浏览器
    browsers = check_bridge()
    if not browsers:
        return 1
    target = next((b for b in browsers if b.get("displayName") == args.browser), None)
    if not target:
        target = browsers[0]
        log(WARN, f"没找到浏览器「{args.browser}」，改用「{target.get('displayName')}」")
    browser_id = target["browserId"]
    log(OK, f"浏览器: {target.get('displayName')} ({browser_id})")

    # 2. 解析输入（类型只是初判，以打开后的实际页面为准）
    aweme_id, kind = parse_input(args.input)
    if not aweme_id:
        return 1

    # 3. 打开页面
    session = f"douyin-dl-{time.strftime('%m%d%H%M%S')}"
    tab_id = navigate_to(browser_id, aweme_id, session)
    if not tab_id:
        return 1

    kind = detect_kind(browser_id, tab_id, aweme_id)
    log(OK, f"作品 ID: {aweme_id} | 实际类型: {'图文' if kind == 'note' else '视频'}")

    os.makedirs(args.out, exist_ok=True)
    saved = []
    result_detail = {}

    try:
        if args.audio_only:
            saved, result_detail = try_audio_only(browser_id, tab_id, aweme_id, args)
        else:
            # 5. 视频分支
            if kind != "note":
                saved += try_video(browser_id, tab_id, aweme_id, args)

            # 6. 图文分支：初判为图文，或视频取流失败时兜底
            if not saved:
                if kind != "note":
                    log(WARN, "视频取流失败，改为按图文提取")
                saved += try_note(browser_id, tab_id, aweme_id, args)
    finally:
        # 6. 清理标签组
        wb(browser_id, "close_session", {"session": session})
        log(INFO, "已关闭浏览器标签组")

    if not saved:
        log(FAIL, "没有成功保存任何文件")
        return 1
    log(OK, f"完成，共 {len(saved)} 个文件 → {args.out}")
    for p in saved:
        print(f"    {p}")
    print("RESULT_JSON=" + json.dumps({
        "aweme_id": aweme_id,
        "kind": result_detail.get("kind", kind),
        "title": result_detail.get("desc", ""),
        "music_title": result_detail.get("music_title", ""),
        "music_author": result_detail.get("music_author", ""),
        "saved": [os.path.abspath(p) for p in saved],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
