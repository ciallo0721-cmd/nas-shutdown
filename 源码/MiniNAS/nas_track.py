# -*- coding: utf-8 -*-
"""
nas_track.py - MiniNAS 访客追踪 (永久ID / 行为审计 / 截图溯源)

设计目标
--------
* 每个访客发一个**永久 ID**(U000001 形式), 写进长期 cookie(10年), 前端水印也用它。
* 清 cookie 也跑不掉: 新访客进来若 IP+UA 命中历史用户(90天内), 直接**召回旧 ID**。
* 记录: 首次/最近访问时间、IP(含历史)、浏览器信息(UA + 屏幕/时区/语言/核数)、
        最近干了什么(滚动 200 条)、总共干了什么(分类计数)、删除了什么、上传了什么。
* 零第三方依赖, 存储 = 单文件 JSON(track.json), 原子写。

由 nas_server.py 调用:
    nas_track.bind(lambda: os.path.join(nas_dir(drives()[0]), 'track.json'))
    uid, is_new = nas_track.identify(ip, ua, cookie_uid)
    nas_track.note(uid, 'upload', 'xx.mp4 (12.3MB)', ip, ua, '/api/upload')
"""
import json
import os
import threading
import time

# ================= 容量上限 (防止无限膨胀) =================
MAX_RECENT = 200      # 每人最近动作条数
MAX_USERS = 800       # 最多记多少访客(超了淘汰最久未见的)
MAX_DELETES = 300     # 每人删除记录条数
MAX_UPLOADS = 200     # 每人上传记录条数
MAX_UAS = 12          # 每人见过的 UA 种类
MAX_IPS = 20          # 每人见过的 IP 数量
RECALL_DAYS = 90      # cookie 丢了, 多久之内同 IP+UA 还能召回旧 ID

_lock = threading.RLock()
_cache = None
_path_fn = None


def bind(path_getter):
    """注入存储路径获取函数 (返回 track.json 的绝对路径, 或 None)"""
    global _path_fn
    _path_fn = path_getter


def _path():
    try:
        return _path_fn() if _path_fn else None
    except Exception:
        return None


def human(n):
    """字节 -> 人类可读"""
    try:
        n = float(n)
    except Exception:
        return '?'
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or u == 'TB':
            return ('%.0f%s' % (n, u)) if u == 'B' else ('%.1f%s' % (n, u))
        n /= 1024


def fmt_time(ts):
    """时间戳 -> 本地可读字符串"""
    if not ts:
        return '-'
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(ts)))
    except Exception:
        return str(ts)


# ================= 读写 =================

def _blank():
    return {'seq': 0, 'users': {}, 'created': time.time(), 'version': 1}


def load(force=False):
    """读取追踪库 (带内存缓存)"""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        p = _path()
        d = None
        if p and os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    d = json.load(f)
            except Exception:
                d = None
        if not isinstance(d, dict) or not isinstance(d.get('users'), dict):
            d = _blank()
        d.setdefault('seq', 0)
        d.setdefault('users', {})
        d.setdefault('version', 1)
        _cache = d
        return _cache


def save():
    """原子落盘 (先写 .tmp 再 replace, 断电不会写坏)"""
    with _lock:
        d = _cache
        p = _path()
        if d is None or not p:
            return False
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
            return True
        except Exception:
            return False


# ================= ID =================

def _next_id(db):
    db['seq'] = int(db.get('seq', 0)) + 1
    return 'U%06d' % db['seq']


def _new_user(db, ip, ua):
    uid = _next_id(db)
    now = time.time()
    db['users'][uid] = {
        'id': uid,
        'first_seen': now,
        'last_seen': now,
        'first_ip': ip,
        'last_ip': ip,
        'ips': {ip: {'n': 1, 'first': now, 'last': now}},
        'ua': ua,
        'ua_first': ua,
        'uas': [ua] if ua else [],
        'fp': {},
        'acts': {},
        'recent': [],
        'deletes': [],
        'uploads': [],
        'hits': 0,          # 总请求数
        'flags': [],        # 可疑标记(蜜罐命中/越权等)
    }
    return uid


def _recall(db, ip, ua):
    """cookie 丢了: 同 IP + 同 UA 且有近期活动 -> 认回老 ID (清 cookie 也没用)"""
    if not ip or ip == '?':
        return None
    deadline = time.time() - RECALL_DAYS * 86400
    best, best_t = None, 0
    for uid, u in db['users'].items():
        if float(u.get('last_seen', 0)) < deadline:
            continue
        same_ip = (u.get('last_ip') == ip) or (ip in (u.get('ips') or {}))
        same_ua = bool(ua) and (ua in (u.get('uas') or []) or u.get('ua') == ua)
        if same_ip and same_ua and float(u.get('last_seen', 0)) > best_t:
            best, best_t = uid, float(u.get('last_seen', 0))
    return best


def identify(ip, ua, cookie_uid=None):
    """确定访客身份 -> (uid, is_new)"""
    ip = ip or '?'
    ua = ua or ''
    now = time.time()
    with _lock:
        db = load()
        uid = None
        if cookie_uid and cookie_uid in db['users']:
            uid = cookie_uid                      # cookie 有效, 直接认
        if not uid:
            uid = _recall(db, ip, ua)             # 试着召回老用户
        is_new = uid is None
        if is_new:
            uid = _new_user(db, ip, ua)
            _prune(db)
        u = db['users'][uid]
        u['last_seen'] = now
        u['last_ip'] = ip
        if ua and ua not in u.get('uas', []):
            u.setdefault('uas', []).append(ua)
            del u['uas'][:-MAX_UAS]
        u['ua'] = ua or u.get('ua', '')
        ips = u.setdefault('ips', {})
        if ip in ips:
            ips[ip]['n'] = int(ips[ip].get('n', 0)) + 1
            ips[ip]['last'] = now
        else:
            ips[ip] = {'n': 1, 'first': now, 'last': now}
            if len(ips) > MAX_IPS:                # 只留最近活跃的 IP
                keep = sorted(ips.items(), key=lambda kv: kv[1].get('last', 0),
                              reverse=True)[:MAX_IPS]
                u['ips'] = dict(keep)
        u['hits'] = int(u.get('hits', 0)) + 1
        save()
        return uid, is_new


def _prune(db):
    """访客数超上限 -> 淘汰最久没露面的"""
    users = db['users']
    if len(users) <= MAX_USERS:
        return
    order = sorted(users.items(), key=lambda kv: float(kv[1].get('last_seen', 0)))
    for uid, _ in order[:len(users) - MAX_USERS]:
        users.pop(uid, None)


# ================= 记录 =================

def note(uid, act, detail='', ip='', ua='', path='', recent=True):
    """记一条行为。act 见下面 ACT_LABEL"""
    if not uid:
        return
    now = time.time()
    with _lock:
        db = load()
        u = db['users'].get(uid)
        if not u:
            return
        acts = u.setdefault('acts', {})
        acts[act] = int(acts.get(act, 0)) + 1
        u['last_seen'] = now
        if ip:
            u['last_ip'] = ip
        if recent:
            u.setdefault('recent', []).append({
                't': now, 'act': act, 'detail': detail,
                'ip': ip or u.get('last_ip', ''), 'path': path,
            })
            del u['recent'][:-MAX_RECENT]
        save()


ACT_LABEL = {
    'view': '打开页面',
    'list': '刷新文件列表',
    'preview': '在线预览',
    'download': '下载',
    'upload': '上传',
    'mkdir': '新建文件夹',
    'delete': '删除',
    'login': '管理员登录',
    'login_fail': '登录失败',
    'logout': '退出登录',
    'admin': '访问管理页',
    'honeypot': '扫描器蜜罐命中',
    'blocked': '越权被拒',
    'disk': '查看磁盘',
}


def note_upload(uid, name, size, ip='', ua=''):
    note(uid, 'upload', '%s (%s)' % (name, human(size)), ip, ua, '/api/upload')
    with _lock:
        u = (load().get('users') or {}).get(uid)
        if u is not None:
            u.setdefault('uploads', []).append(
                {'t': time.time(), 'name': name, 'size': size, 'ip': ip})
            del u['uploads'][:-MAX_UPLOADS]
            save()


def note_delete(uid, name, size=0, ip='', ua='', is_dir=False, children=0):
    d = '%s (%s)' % (name, human(size))
    if is_dir:
        d += ' [文件夹, 连带 %d 项]' % children
    note(uid, 'delete', d, ip, ua, '/api/delete')
    with _lock:
        u = (load().get('users') or {}).get(uid)
        if u is not None:
            u.setdefault('deletes', []).append(
                {'t': time.time(), 'name': name, 'size': size,
                 'ip': ip, 'is_dir': bool(is_dir), 'children': children})
            del u['deletes'][:-MAX_DELETES]
            save()


def flag(uid, why):
    """给人打可疑标记 (蜜罐命中 / 越权尝试)"""
    if not uid:
        return
    with _lock:
        u = (load().get('users') or {}).get(uid)
        if u is None:
            return
        fl = u.setdefault('flags', [])
        if why not in [f.get('why') for f in fl]:
            fl.append({'why': why, 't': time.time()})
        else:
            for f in fl:
                if f.get('why') == why:
                    f['n'] = int(f.get('n', 1)) + 1
                    f['t'] = time.time()
        save()


def set_fp(uid, fp):
    """前端上报的指纹: 屏幕/时区/语言/核心数/内存/平台"""
    if not uid or not isinstance(fp, dict):
        return
    with _lock:
        u = (load().get('users') or {}).get(uid)
        if u is None:
            return
        cur = u.setdefault('fp', {})
        for k in ('screen', 'tz', 'lang', 'cores', 'mem', 'plat', 'dpr', 'gpu', 'touch'):
            if k in fp and fp[k] not in (None, ''):
                cur[k] = str(fp[k])[:120]
        cur['updated'] = time.time()
        save()


def get(uid):
    with _lock:
        return (load().get('users') or {}).get(uid)


def all_users():
    with _lock:
        return dict((load().get('users') or {}))


def stats():
    db = load()
    us = db.get('users') or {}
    return {
        'users': len(us),
        'total_hits': sum(int(u.get('hits', 0)) for u in us.values()),
        'total_uploads': sum(len(u.get('uploads') or []) for u in us.values()),
        'total_deletes': sum(len(u.get('deletes') or []) for u in us.values()),
        'flagged': sum(1 for u in us.values() if u.get('flags')),
        'created': db.get('created'),
        'path': _path(),
    }
