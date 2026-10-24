# -*- coding: utf-8 -*-
"""
idinfo.py - MiniNAS 访客档案查询 (给管理员用)

用法
----
    python idinfo.py                    # 所有访客概览表
    python idinfo.py U000001            # 单个访客的完整档案
    python idinfo.py U000001 --tail 80  # 档案 + 最近 80 条动作
    python idinfo.py --ip 192.168.1.5   # 按 IP 反查是谁
    python idinfo.py --tail 40          # 全局最近动作流(所有人混在一起)
    python idinfo.py --bad              # 只看可疑的(蜜罐命中 / 越权 / 猜口令)
    python idinfo.py --file D:\\NAS\\track.json   # 手动指定追踪库
    python idinfo.py --json             # 输出原始 JSON(给程序用)

追踪库默认位置: C:\\NAS\\track.json -> D:\\NAS\\track.json -> E:\\NAS\\track.json
"""
import json
import os
import sys
import time

# Windows 控制台默认 GBK, 中文和框线会乱码 -> 尽量切成 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ACT_LABEL = {
    'view': '打开页面', 'list': '刷新列表', 'preview': '在线预览',
    'download': '下载', 'upload': '上传', 'mkdir': '新建文件夹',
    'delete': '删除', 'login': '管理员登录', 'login_fail': '登录失败',
    'logout': '退出登录', 'admin': '访问管理页', 'honeypot': '⚡扫描器蜜罐',
    'blocked': '⛔越权被拒', 'disk': '查看磁盘',
}
DRIVES = ['C', 'D', 'E']


# ================= 工具 =================

def human(n):
    try:
        n = float(n)
    except Exception:
        return '?'
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or u == 'TB':
            return ('%.0f%s' % (n, u)) if u == 'B' else ('%.1f%s' % (n, u))
        n /= 1024


def ts(t):
    if not t:
        return '-'
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(t)))
    except Exception:
        return str(t)


def ago(t):
    """距现在多久"""
    if not t:
        return '-'
    d = time.time() - float(t)
    if d < 60:
        return '刚刚'
    for n, u in ((60, '分钟'), (3600, '小时'), (86400, '天'), (86400 * 30, '个月')):
        if d < n * 60 if u == '分钟' else d < n * (1 if u != '个月' else 30):
            pass
    if d < 3600:
        return '%d分钟前' % (d // 60)
    if d < 86400:
        return '%d小时前' % (d // 3600)
    if d < 86400 * 30:
        return '%d天前' % (d // 86400)
    return '%d个月前' % (d // (86400 * 30))


def width(s):
    """中文算 2 格的显示宽度"""
    w = 0
    for ch in str(s):
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def pad(s, n, align='<'):
    s = str(s)
    gap = max(0, n - width(s))
    if align == '>':
        return ' ' * gap + s
    if align == '^':
        l = gap // 2
        return ' ' * l + s + ' ' * (gap - l)
    return s + ' ' * gap


def cut(s, n):
    """按显示宽度截断"""
    s = str(s)
    out, w = '', 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > n:
            return out + '…'
        out += ch
        w += cw
    return out


def hr(ch='─', n=78):
    return ch * n


def title(s):
    print()
    print('╔' + '═' * (width(s) + 2) + '╗')
    print('║ ' + s + ' ║')
    print('╚' + '═' * (width(s) + 2) + '╝')


# ================= 定位追踪库 =================

def find_db(manual=None):
    if manual:
        return manual if os.path.exists(manual) else None
    env = os.environ.get('NAS_TRACK')
    if env and os.path.exists(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, 'track.json')]
    for d in DRIVES:
        cands.append('%s:\\NAS\\track.json' % d)
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def load_db(path):
    if not path:
        print('× 找不到 track.json —— NAS 还没被访问过, 或用 --file 手动指定路径')
        sys.exit(1)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        print('× 追踪库读不出来: %s' % e)
        sys.exit(1)
    d.setdefault('users', {})
    return d


# ================= 概览 =================

def cmd_list(db):
    users = db['users']
    if not users:
        print('\n(还没有访客记录 —— 等第一批人来访问吧喵)')
        return
    rows = sorted(users.values(), key=lambda u: float(u.get('last_seen', 0)), reverse=True)

    title('MiniNAS 访客总览 · 共 %d 人 · 库文件 %s' % (len(rows), db['_path']))
    head = [('ID', 9), ('首次访问', 19), ('最近访问', 19), ('距今', 9),
            ('最近IP', 15), ('请求', 5), ('上传', 5), ('删', 4), ('异常', 5)]
    print(' '.join(pad(h, w) for h, w in head))
    print(hr('-', 78))
    for u in rows:
        ip = u.get('last_ip', '-') or '-'
        fl = len(u.get('flags') or [])
        print(' '.join([
            pad(u.get('id', '?'), 9),
            pad(ts(u.get('first_seen')), 19),
            pad(ts(u.get('last_seen')), 19),
            pad(ago(u.get('last_seen')), 9),
            pad(cut(ip, 15), 15),
            pad(u.get('hits', 0), 5, '>'),
            pad(len(u.get('uploads') or []), 5, '>'),
            pad(len(u.get('deletes') or []), 4, '>'),
            pad(('⚠%d' % fl) if fl else '-', 5),
        ]))
    print(hr('-', 78))
    print('提示: python idinfo.py <ID> 看某个人的完整档案;  --bad 只看可疑的')
    tot_up = sum(len(u.get('uploads') or []) for u in rows)
    tot_del = sum(len(u.get('deletes') or []) for u in rows)
    ua_kinds = set()
    for u in rows:
        for a in (u.get('uas') or []):
            ua_kinds.add(a)
    print('合计: 请求 %d 次 | 上传 %d 次 | 删除 %d 次 | 不同浏览器 %d 种'
          % (sum(int(u.get('hits', 0)) for u in rows), tot_up, tot_del, len(ua_kinds)))


# ================= 单人文档 =================

def show_user(u, tail=25):
    uid = u.get('id', '?')
    title('访客档案 · %s' % uid)

    fl = u.get('flags') or []
    if fl:
        print('⚠ 可疑标记:')
        for f in fl:
            print('    · %s  (最近 %s, 命中 %d 次)' % (
                f.get('why', '?'), ts(f.get('t')), f.get('n', 1)))
        print()

    print('【身份】')
    print('  永久 ID   : %s' % uid)
    print('  首次访问  : %s  (%s)' % (ts(u.get('first_seen')), ago(u.get('first_seen'))))
    print('  最近访问  : %s  (%s)' % (ts(u.get('last_seen')), ago(u.get('last_seen'))))
    print('  总请求数  : %s 次' % u.get('hits', 0))

    print('\n【网络】')
    ips = u.get('ips') or {}
    print('  最近 IP   : %s' % (u.get('last_ip') or '-'))
    print('  首次 IP   : %s' % (u.get('first_ip') or '-'))
    if len(ips) > 1 or (ips and list(ips)[0] != u.get('last_ip')):
        print('  见过 %d 个 IP:' % len(ips))
        for ip, info in sorted(ips.items(), key=lambda kv: kv[1].get('last', 0), reverse=True):
            print('    · %-16s %3d 次   首次 %s   最近 %s' % (
                ip, info.get('n', 0), ts(info.get('first')), ts(info.get('last'))))

    print('\n【浏览器 / 设备】')
    fp = u.get('fp') or {}
    uas = u.get('uas') or ([u['ua']] if u.get('ua') else [])
    print('  UA(最近)  : %s' % (u.get('ua') or '-'))
    if len(uas) > 1:
        print('  换过的 UA : %d 种' % len(uas))
        for a in uas:
            if a != u.get('ua'):
                print('    · %s' % a)
    if fp:
        kv = []
        if fp.get('screen'):
            kv.append('屏幕 %s' % fp['screen'])
        if fp.get('dpr'):
            kv.append('像素比 %s' % fp['dpr'])
        if fp.get('plat'):
            kv.append('平台 %s' % fp['plat'])
        if fp.get('cores'):
            kv.append('CPU %s核' % fp['cores'])
        if fp.get('mem'):
            kv.append('内存 %sG' % fp['mem'])
        if fp.get('tz'):
            kv.append('时区 %s' % fp['tz'])
        if fp.get('lang'):
            kv.append('语言 %s' % fp['lang'])
        if fp.get('touch'):
            kv.append('触屏 %s' % fp['touch'])
        print('  指纹      : %s' % ' | '.join(kv))
        print('  指纹更新  : %s' % ts(fp.get('updated')))
    else:
        print('  指纹      : (前端还没上报, 只有 UA)')

    print('\n【总共干了什么】')
    acts = u.get('acts') or {}
    if acts:
        for act, n in sorted(acts.items(), key=lambda kv: -kv[1]):
            print('  %s %4d 次' % (pad(ACT_LABEL.get(act, act), 14), n))
    else:
        print('  (无记录)')

    ups = u.get('uploads') or []
    print('\n【上传过什么】(共 %d 个, 显示最近 %d)' % (len(ups), min(10, len(ups))))
    if ups:
        for x in ups[-10:][::-1]:
            print('  · %s   %s   %s' % (ts(x.get('t')), pad(human(x.get('size', 0)), 9, '>'),
                                        x.get('name', '?')))
    else:
        print('  (没传过东西)')

    dels = u.get('deletes') or []
    print('\n【删除了什么】(共 %d 个)' % len(dels))
    if dels:
        for x in dels[-20:][::-1]:
            extra = ('文件夹·连带%d项' % x.get('children', 0)) if x.get('is_dir') else human(x.get('size', 0))
            print('  · %s   %s   %s' % (ts(x.get('t')), pad(extra, 14, '>'), x.get('name', '?')))
    else:
        print('  (没删过东西)')

    recent = u.get('recent') or []
    print('\n【最近干了什么】(最近 %d 条, 倒序)' % min(tail, len(recent)))
    if recent:
        for x in recent[-tail:][::-1]:
            print('  %s  %s %s' % (
                ts(x.get('t')), pad(ACT_LABEL.get(x.get('act'), x.get('act')), 14),
                cut(x.get('detail', ''), 46)))
    else:
        print('  (无)')
    print()


def cmd_user(db, key, tail=25):
    users = db['users']
    hit = users.get(key)
    if not hit:                                  # 支持前缀/模糊匹配
        cands = [u for k, u in users.items() if k.lower().startswith(key.lower())]
        if not cands:
            cands = [u for u in users.values() if key.lower() in json.dumps(u, ensure_ascii=False).lower()]
        if len(cands) == 1:
            hit = cands[0]
        elif not cands:
            print('× 没找到 ID/IP/关键词 = %s 的访客' % key)
            print('  提示: 先跑 python idinfo.py 看看有哪些人')
            return
        else:
            print('找到 %d 个匹配, 请用更精确的 ID:' % len(cands))
            for u in cands[:15]:
                print('  %s  %s  %s' % (u.get('id'), ts(u.get('last_seen')),
                                        u.get('last_ip', '')))
            return
    show_user(hit, tail)


# ================= 其它命令 =================

def cmd_ip(db, ip):
    hits = [u for u in db['users'].values()
            if ip == u.get('last_ip') or ip == u.get('first_ip') or ip in (u.get('ips') or {})]
    if not hits:
        print('× 没有访客用过 IP %s' % ip)
        return
    print('\nIP %s 对应 %d 个访客:' % (ip, len(hits)))
    for u in sorted(hits, key=lambda x: float(x.get('last_seen', 0)), reverse=True):
        print('  %s  最近 %s  请求 %s 次' % (
            u.get('id'), ts(u.get('last_seen')), u.get('hits', 0)))
    if len(hits) == 1:
        show_user(hits[0], 15)


def cmd_tail(db, n):
    rows = []
    for u in db['users'].values():
        for x in (u.get('recent') or []):
            x = dict(x)
            x['uid'] = u.get('id')
            rows.append(x)
    rows.sort(key=lambda x: float(x.get('t', 0)))
    title('全局动作流 · 最近 %d 条 (共 %d 条记录)' % (min(n, len(rows)), len(rows)))
    for x in rows[-n:]:
        print('  %s  %s %s %s %s' % (
            ts(x.get('t')), pad(x.get('uid', '?'), 8),
            pad(ACT_LABEL.get(x.get('act'), x.get('act')), 14),
            pad(cut(x.get('ip', ''), 15), 16), cut(x.get('detail', ''), 34)))
    print()


def cmd_bad(db):
    rows = []
    for u in db['users'].values():
        fl = u.get('flags') or []
        dels = u.get('deletes') or []
        if fl or dels:
            rows.append(u)
    if not rows:
        print('\n✓ 没有任何可疑记录 —— 大家都是好孩子喵')
        return
    title('可疑访客 · %d 人' % len(rows))
    for u in sorted(rows, key=lambda x: float(x.get('last_seen', 0)), reverse=True):
        print('\n%s   IP %s   最近 %s' % (
            u.get('id'), u.get('last_ip', '-'), ts(u.get('last_seen'))))
        for f in (u.get('flags') or []):
            print('   ⚠ %s (命中 %d 次, 最近 %s)' % (
                f.get('why'), f.get('n', 1), ts(f.get('t'))))
        for x in (u.get('deletes') or [])[-5:]:
            print('   🗑 删了 %s  (%s)' % (x.get('name'), ts(x.get('t'))))
        print('   看详情: python idinfo.py %s' % u.get('id'))
    print()


# ================= 入口 =================

def main():
    args = sys.argv[1:]
    manual, tail, mode, key, tail_only = None, 25, 'list', None, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--file' and i + 1 < len(args):
            manual = args[i + 1]; i += 2; continue
        if a == '--tail' and i + 1 < len(args):
            try:
                tail = int(args[i + 1])
            except Exception:
                pass
            tail_only = True
            i += 2; continue
        if a in ('--ip',) and i + 1 < len(args):
            mode, key = 'ip', args[i + 1]; i += 2; continue
        if a == '--bad':
            mode = 'bad'; i += 1; continue
        if a == '--json':
            mode = 'json'; i += 1; continue
        if a in ('-h', '--help'):
            print(__doc__); return
        if not key:
            key = a
        i += 1
    if key and mode == 'list':
        mode = 'user'
    elif tail_only and mode == 'list':
        mode = 'tail'

    path = find_db(manual)
    db = load_db(path)
    db['_path'] = path

    if mode == 'json':
        d = dict(db); d.pop('_path', None)
        print(json.dumps(d, ensure_ascii=False, indent=1)); return
    if mode == 'list':
        cmd_list(db)
    elif mode == 'user':
        cmd_user(db, key, tail)
    elif mode == 'ip':
        cmd_ip(db, key)
    elif mode == 'tail':
        cmd_tail(db, tail)
    elif mode == 'bad':
        cmd_bad(db)


if __name__ == '__main__':
    main()
