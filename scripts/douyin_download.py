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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ---------- 常量（改这里即可） ----------

def find_media_tool(name):
    """Find ffmpeg/ffprobe through PATH, with the Apple Silicon Homebrew fallback."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "darwin":
        homebrew_path = os.path.join("/opt/homebrew/bin", name)
        if os.path.isfile(homebrew_path):
            return homebrew_path
    return None


FFMPEG_BIN = find_media_tool("ffmpeg")
FFPROBE_BIN = find_media_tool("ffprobe")
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
ACCESS_BARRIER_TEXT = re.compile(
    r"请先登录|请登录后|登录后(?:继续|查看|访问)|扫码登录|短信验证码|"
    r"安全验证|请完成验证|完成验证后|滑块验证|验证码|"
    r"(?:sign[ -]?in|log[ -]?in|captcha|security challenge|verify to continue)",
    re.IGNORECASE,
)

OK, FAIL, INFO, WARN = "[OK]", "[FAIL]", "[..]", "[!!]"


def log(symbol, msg):
    print(f"{symbol} {msg}", flush=True)


class AccessBarrierError(RuntimeError):
    """Raised when Douyin requires manual login or a human verification step."""


def is_access_barrier_text(value):
    return bool(ACCESS_BARRIER_TEXT.search(str(value or "")))


def is_access_barrier_url(value):
    return bool(re.search(r"(?:login|passport|captcha|verify|challenge)", str(value or ""), re.I))


def is_access_barrier_payload(payload):
    """Inspect structured API errors without interpreting ordinary post text."""
    if not isinstance(payload, dict):
        return False
    for key in ("login_required", "need_login", "verify_required", "captcha_required"):
        if payload.get(key) is True:
            return True
    messages = [payload.get(key) for key in (
        "status_msg", "message", "error", "error_description", "err",
    )]
    if any(is_access_barrier_text(message) for message in messages if message):
        return True
    for key in ("status_code", "status", "code"):
        value = payload.get(key)
        if value not in (None, 0, "0", 200, "200", "success", "ok"):
            if any(is_access_barrier_text(message) for message in messages if message):
                return True
    return False


def raise_if_access_barrier_payload(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return
    if is_access_barrier_payload(payload):
        raise AccessBarrierError("抖音要求登录或人工验证")
    if isinstance(payload, dict):
        for key in ("status_code", "status_code_v2"):
            status = payload.get(key)
            if status not in (None, 0, "0", 200, "200", "success", "ok"):
                raise AccessBarrierError("抖音详情接口返回受限或异常状态")
        if payload.get("detailReady") is False:
            raise AccessBarrierError("无法确认详情接口访问状态")
        error_code = re.sub(r"[^a-z0-9]+", "_", str(payload.get("err") or "").lower()).strip("_")
        if error_code == "no_aweme_detail":
            raise AccessBarrierError("无法确认详情接口访问状态")


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
    check_page_access_barrier(browser_id, tab_id)
    res = wb(browser_id, "evaluate", {"tabId": tab_id, "code": code})
    if not res or not res.get("ok"):
        check_page_access_barrier(browser_id, tab_id)
        return None
    result = res.get("result")
    try:
        raise_if_access_barrier_payload(result)
    finally:
        check_page_access_barrier(browser_id, tab_id)
    return result


def check_page_access_barrier(browser_id, tab_id):
    """Detect explicit login/challenge pages before running another extraction."""
    code = (
        '(()=>{const url=location.href||"",title=document.title||"";'
        'const dialogs=[...document.querySelectorAll('
        '"[role=dialog], [aria-modal=true], [class*=captcha], [class*=verify], "+'
        '"[class*=login], [class*=passport], iframe[src*=captcha], iframe[src*=verify]")];'
        'const text=[title,...dialogs.map(x=>x.innerText||"")].join("\\n");'
        'const body=(document.body?.innerText||"").slice(0,5000);'
        'const urlBlocked=/\\/(?:login|passport|captcha|verify|challenge)(?:[/?#]|$)/i.test(url);'
        'const textBlocked=/请先登录|请登录后|登录后(?:继续|查看|访问)|扫码登录|短信验证码|安全验证|请完成验证|完成验证后|滑块验证|验证码|(?:sign[ -]?in|log[ -]?in|captcha|security challenge|verify to continue)/i.test(text);'
        'const bodyBlocked=/请先登录|请登录后|登录后继续|扫码登录|安全验证|请完成验证|完成验证后|滑块验证|security challenge|verify to continue/i.test(body);'
        'return JSON.stringify({blocked:urlBlocked||textBlocked||bodyBlocked,href:url,title:title})})()'
    )
    res = wb(browser_id, "evaluate", {"tabId": tab_id, "code": code})
    if not res or not res.get("ok"):
        raise AccessBarrierError("无法确认当前页面是否出现登录或验证拦截")
    raw = res.get("result")
    try:
        state = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        raise AccessBarrierError("页面状态检查返回了无法解析的结果")
    if not isinstance(state, dict) or type(state.get("blocked")) is not bool:
        raise AccessBarrierError("页面状态检查结果缺少有效的 blocked 布尔值")
    if state["blocked"]:
        raise AccessBarrierError("检测到抖音登录墙或验证墙")


# ---------- 取直链 ----------

def fetch_video_detail(browser_id, tab_id, aweme_id):
    """在页面内 fetch detail 接口，拿全部码率档位 + 标题。
    注意：不要直接读 video.src —— 那只给 540p。"""
    js = (
        '(async()=>{try{'
        f'const url="https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={aweme_id}";'
        'const j=await(await fetch(url,{credentials:"include"})).json();'
        'const status_code=j.status_code??j.status_code_v2??0,status_msg=j.status_msg||"";'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({status_code:status_code,status_msg:status_msg,err:"no aweme_detail"});'
        'const v=d.video||{};'
        'const brs=(v.bit_rate||[]).map(b=>({gear:b.gear_name,w:(b.play_addr||{}).width||0,'
        'h:(b.play_addr||{}).height||0,url:((b.play_addr||{}).url_list||[])[0]||""})).filter(b=>b.url);'
        'return JSON.stringify({status_code:status_code,status_msg:status_msg,desc:d.desc||"",duration:v.duration||0,brs:brs})'
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
        'const status_code=j.status_code??j.status_code_v2??0,status_msg=j.status_msg||"";'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({detailReady:false,status_code:status_code,status_msg:status_msg});'
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
        'hasImages:hasImages,hasVideo:hasVideo,status_code:status_code,status_msg:status_msg})'
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

    页面首屏可能先没有 ``<video>``，因此先读取详情接口判型。详情状态
    无法确认时停止；不以 DOM 推荐图或模糊状态补猜媒体类型。
    """
    for wait in (0, 1, 2):
        probe = fetch_kind_probe(browser_id, tab_id, aweme_id, wait=wait)
        if probe is None:
            raise AccessBarrierError("无法读取作品详情并确认访问状态")
        kind = classify_media_probe(probe)
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
        'const status_code=j.status_code??j.status_code_v2??0,status_msg=j.status_msg||"";'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({status_code:status_code,status_msg:status_msg,err:"no aweme_detail"});'
        'const ims=(d.images||[]).map(im=>({w:im.width||0,h:im.height||0,'
        'urls:im.url_list||[]})).filter(x=>x.urls.length);'
        'return JSON.stringify({status_code:status_code,status_msg:status_msg,desc:d.desc||"",imgs:ims})'
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
        'const status_code=j.status_code??j.status_code_v2??0,status_msg=j.status_msg||"";'
        'const d=j.aweme_detail;if(!d)return JSON.stringify({status_code:status_code,status_msg:status_msg,err:"no aweme_detail"});'
        'const v=d.video||{},m=d.music||{},p=m.play_url||{};'
        'let extra={};try{extra=typeof m.extra==="string"?JSON.parse(m.extra):(m.extra||{})}catch(_){}'
        'const images=Array.isArray(d.images)?d.images:[];'
        'return JSON.stringify({desc:d.desc||"",aweme_type:d.aweme_type,'
        'kind:images.length?"note":"video",music_title:m.title||"",music_author:m.author||"",'
        'offline_desc:m.offline_desc||"",'
        'video_play_urls:((v.play_addr||{}).url_list||[]),'
        'music_play_urls:(p.url_list||[]),'
        'music_original_urls:extra.original_song_url?[extra.original_song_url]:[],status_code:status_code,status_msg:status_msg})'
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


def select_note_images(detail, dom_images):
    """Use the requested work's detail list as the only image source.

    DOM images may include recommendations and comments. They are allowed to
    supply a signed original URL only when its stable image ID matches a URL
    already present in the work detail response.
    """
    if not isinstance(detail, dict) or detail.get("err"):
        return [], ""
    detail_images = detail.get("imgs")
    if not isinstance(detail_images, list) or not detail_images:
        return [], detail.get("desc") or ""
    noop_map = {}
    for url in dom_images if isinstance(dom_images, list) else []:
        if isinstance(url, str) and "~noop" in url:
            key = _img_key(url)
            if key:
                noop_map[key] = url
    images = []
    for item in detail_images:
        urls = item.get("urls") if isinstance(item, dict) else None
        if not isinstance(urls, list) or not urls:
            continue
        url, tier = pick_image(urls, noop_map)
        images.append((url, tier))
    return images, detail.get("desc") or ""


def get_title(browser_id, tab_id):
    raw = evaluate(browser_id, tab_id, "document.title")
    if not raw:
        return ""
    return re.sub(r"\s*-\s*抖音\s*$", "", str(raw)).strip()


def select_browser(browsers, requested=None):
    """Select only an explicit browser or an unambiguous default environment."""
    if not browsers:
        return None
    if requested:
        matches = [b for b in browsers if requested in (
            b.get("displayName"), b.get("browserId"), b.get("id"),
        )]
        return matches[0] if len(matches) == 1 else None
    preferred = [b for b in browsers if b.get("displayName") == "自媒体"]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        return None
    return browsers[0] if len(browsers) == 1 else None


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
         "-w", "%{http_code}\\t%{size_download}\\t%{redirect_url}\\t%{content_type}"]
    )
    parts = out.rstrip("\r\n").split("\t")
    status = parts[0] if parts else "?"
    redirect_url = parts[2] if len(parts) >= 3 else ""
    content_type = parts[3].lower() if len(parts) >= 4 else ""
    if status in ("401", "403", "429") or (status.startswith("3") and is_access_barrier_url(redirect_url)):
        if os.path.isfile(out_path):
            os.unlink(out_path)
        raise AccessBarrierError(f"下载请求返回访问限制 HTTP {status}")
    if status == "200" and content_type.startswith("text/html"):
        if os.path.isfile(out_path):
            os.unlink(out_path)
        raise AccessBarrierError("下载请求返回验证或登录页面，而不是媒体文件")
    if len(parts) >= 2 and status == "200":
        size = int(parts[1])
        log(OK, f"下载完成 {size/1024/1024:.2f} MB → {os.path.basename(out_path)}")
        return size > 0
    log(FAIL, f"下载失败 http={status} {err[:200]}")
    return False


def probe(path):
    if not FFPROBE_BIN or not os.path.isfile(FFPROBE_BIN):
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
    if not FFPROBE_BIN or not os.path.isfile(FFPROBE_BIN):
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
    if not FFMPEG_BIN or not os.path.isfile(FFMPEG_BIN):
        log(FAIL, "找不到 ffmpeg，请安装 FFmpeg 并将其加入 PATH")
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
    dom_imgs = fetch_note_images(browser_id, tab_id) if (
        isinstance(detail, dict) and detail.get("imgs")
    ) else []
    imgs, title = select_note_images(detail, dom_imgs)
    if imgs:
        log(INFO, f"detail 接口取到 {len(imgs)} 张正文图")

    if not imgs:
        log(FAIL, "作品详情未提供可确认的正文图片清单；为避免保存推荐图，已停止图文下载")
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
    ap.add_argument("--browser", help="目标浏览器显示名或 browserId（默认优先“自媒体”，仅一个环境时可自动选择）")
    ap.add_argument("--quality", default="best", choices=["best", "worst"], help="清晰度")
    ap.add_argument("--audio-only", action="store_true", help="只提取作品音轨，输出 48kHz 双声道 MP3")
    args = ap.parse_args()

    # 1. EasyBR 内置 Bridge + 浏览器
    browsers = check_bridge()
    if not browsers:
        return 1
    target = select_browser(browsers, args.browser)
    if not target:
        if args.browser:
            log(FAIL, f"找不到在线浏览器「{args.browser}」；不会改用其他浏览器。请确认目标环境在线，或指定其 browserId。")
        else:
            names = ", ".join(
                f"{b.get('displayName')} ({b.get('browserId')})" for b in browsers
            )
            log(FAIL, f"在线浏览器无法无歧义选择（{names}）；请用 --browser 指定显示名或 browserId。")
        return 1
    browser_id = target.get("browserId") or target.get("id")
    if not browser_id:
        log(FAIL, "所选浏览器缺少 browserId，已停止。")
        return 1
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

    saved = []
    result_detail = {}
    access_barrier = False

    try:
        kind = detect_kind(browser_id, tab_id, aweme_id)
        log(OK, f"作品 ID: {aweme_id} | 实际类型: {'图文' if kind == 'note' else '视频'}")
        os.makedirs(args.out, exist_ok=True)
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
    except AccessBarrierError:
        access_barrier = True
        log(FAIL, "检测到登录/验证拦截，或无法安全确认详情访问状态；已停止后续请求和回退。请检查当前页面，必要时手动登录/完成验证后重新运行。")
        log(INFO, f"已保留当前浏览器标签供你处理：tabId={tab_id}")
        return 2
    finally:
        if not access_barrier:
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
