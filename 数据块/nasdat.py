#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nasdat.py — MiniNAS 数据块还原工具
==================================

MiniNAS 不把文件原样存在磁盘上。它把每个文件切块，写成 `nas`、`nas1`、`nas2`……
这样的"数据块"文件，然后在一份 `index.json` 里记下：谁叫什么、多大、由哪几块拼成。

所以磁盘上你看到的是一堆 nasN，看不到一张照片。这个脚本就是干这事的：
照着 index.json，把数据块按顺序拼回去，还原成能打开的原文件。

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
    python nasdat.py info                     概览：多少文件、多少块、缺多少
    python nasdat.py list                     列出全部条目（含缺失标记）
    python nasdat.py list --tree               按目录树列出
    python nasdat.py check                    体检：逐条核对数据块
    python nasdat.py extract -o 还原           全部还原到 ./还原
    python nasdat.py extract -o 还原 --only 塔菲     只还原路径含"塔菲"的
    python nasdat.py extract --dry-run         只演算，不写盘

    --data 数据目录     all/ 所在位置（默认自动查找）
    --overwrite        覆盖已存在的同名文件
    --partial          块不全时也输出残缺文件（默认跳过）
    --quiet            安静模式，只打结果

--------------------------------------------------------------------------
数据目录结构（解压 all.zip 之后）
--------------------------------------------------------------------------
    all/
      C/NAS/index.json       ← 索引
      C/NAS/nas  nasx ...    ← 数据块
      D/NAS/nas  nas1 ...
      E的NAS/nas9 ...

脚本会自动在 all/ 下面找所有名字带「NAS」的目录，按首字母认盘符
（`E的NAS` 这种改了名的也能认出来）。

--------------------------------------------------------------------------
关于完整性
--------------------------------------------------------------------------
index.json 里记的是 NAS 曾经有过的**全部**文件（本包约 6.1 GB）。
但数据块只打包了一部分（约 456 MB），所以很多条目是拼不出来的。
`check` 会把能还原的 / 缺块的分开列清楚。缺块不是 bug，就是没打包进来。

--------------------------------------------------------------------------
"""

import argparse
import json
import ntpath
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

if os.name == 'nt':
    try:
        os.system('')          # 打开 Windows 控制台的 ANSI 转义支持
    except Exception:
        pass


# ── 路径安全 ────────────────────────────────────────────────────────────────
_ILLEGAL = '<>:"|?*'


def safe_relpath(name):
    """把索引里的 name 变成安全的相对路径。

    索引里 name 长这样：'塔菲/1788424020795.jpeg'、'线框图/2026年9月5日NAS'
    统一用 '/' 分隔。这里防一下 .. 穿越和 Windows 非法字符。
    """
    parts = []
    for seg in str(name).replace('\\', '/').split('/'):
        seg = seg.strip()
        if not seg or seg in ('.', '..'):
            continue
        for ch in _ILLEGAL:
            seg = seg.replace(ch, '_')
        seg = seg.rstrip(' .')
        if seg:
            parts.append(seg)
    return os.path.join(*parts) if parts else ''


# ── 索引 ────────────────────────────────────────────────────────────────────
def find_data_root(explicit=None):
    """定位数据目录（也就是 all/ 那一层）。"""
    here = os.path.dirname(os.path.abspath(__file__))

    if explicit:
        p = os.path.abspath(explicit)
        if not os.path.isdir(p):
            die('数据目录不存在：%s' % p)
        return p

    # 1) 脚本旁边常见的几个位置
    for cand in (os.path.join(here, 'all'),
                 os.path.join(here, '数据块', 'all'),
                 os.path.join(os.path.dirname(here), 'all'),
                 here):
        if os.path.isfile(os.path.join(cand, 'index.json')):
            return cand
        for sub in os.listdir(cand) if os.path.isdir(cand) else []:
            if os.path.isfile(os.path.join(cand, sub, 'index.json')):
                return cand

    # 2) 往下找 index.json（最多 5 层）
    for base in (here, os.path.dirname(here)):
        for root, dirs, files in os.walk(base):
            depth = root[len(base):].count(os.sep)
            if depth > 5:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if 'index.json' in files and 'nas' in ''.join(
                    os.listdir(root)).lower().replace('index.json', ''):
                up = root
                for _ in range(3):
                    if os.path.basename(up).upper().startswith(('C', 'D', 'E')) or \
                       'NAS' in os.path.basename(up).upper():
                        up = os.path.dirname(up)
                return up or base

    die('找不到数据目录（含 index.json 的 all/）。用 --data 手动指定。')


def load_index(data_root):
    """读 index.json，返回 (记录列表, index 文件路径)。"""
    path = None
    direct = os.path.join(data_root, 'index.json')
    if os.path.isfile(direct):
        path = direct
    else:
        for root, _dirs, files in os.walk(data_root):
            if 'index.json' in files:
                path = os.path.join(root, 'index.json')
                break
    if not path:
        die('数据目录里没有 index.json：%s' % data_root)

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        records = list(raw.values())
    elif isinstance(raw, list):
        records = raw
    else:
        die('index.json 格式不认识：%s' % type(raw).__name__)

    out = []
    for r in records:
        if not isinstance(r, dict):
            continue
        out.append({
            'id':       r.get('id', ''),
            'name':     str(r.get('name', '')),
            'size':     int(r.get('size') or 0),
            'chunks':   [str(c) for c in (r.get('chunks') or [])],
            'time':     float(r.get('time') or 0),
            'is_dir':   bool(r.get('is_dir')),
        })
    return out, path


# ── 数据块定位 ──────────────────────────────────────────────────────────────
def build_chunk_map(data_root):
    """扫描数据目录，建立 {盘符: {块名: 路径}} 和 {块名: [路径...]}。

    索引里记的块路径是绝对路径（'C:\\NAS\\nas'），搬到别处就失效了，
    所以按"盘符 + 文件名"重新对应，而不是照抄原路径。
    """
    by_drive = {}
    by_name = {}

    for root, dirs, files in os.walk(data_root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        own = os.path.basename(root)
        upper = own.upper()
        if 'NAS' not in upper:
            continue

        # 认盘符。两种目录形态：
        #   all/C/NAS     → 目录自己就叫 NAS，盘符在上层 'C'
        #   all/E的NAS    → 目录名带盘符，取首字母 'E'
        drive = None
        if upper == 'NAS':
            par = os.path.basename(os.path.dirname(root))
            if par and len(par) <= 3 and par[0].isalpha():
                drive = par[0].upper()
        if drive is None:
            for ch in own:
                if ch.isalpha():
                    drive = ch.upper()
                    break
        for fn in files:
            if fn in ('index.json', 'track.json', 'track.json.tmp',
                      '.token_salt', 'index.json.tmp'):
                continue
            if fn.endswith(('.log', '.json', '.py', '.md', '.txt', '.html',
                            '.css', '.js', '.bat', '.yml', '.gz', '.exe')):
                continue
            full = os.path.join(root, fn)
            if not os.path.isfile(full):
                continue
            by_name.setdefault(fn, []).append(full)
            if drive:
                by_drive.setdefault(drive, {}).setdefault(fn, full)

    return by_drive, by_name


def resolve_chunk(chunk_path, by_drive, by_name):
    """把索引里的块路径解析成本地真实文件。返回 (路径 或 None, 原因)。"""
    drive_ms, rest = ntpath.splitdrive(chunk_path)
    base = ntpath.basename(rest or chunk_path)
    drive = drive_ms.rstrip(':').upper() if drive_ms else None

    if drive and drive in by_drive and base in by_drive[drive]:
        return by_drive[drive][base], ''

    hits = by_name.get(base) or []
    if len(hits) == 1:
        return hits[0], ''
    if len(hits) > 1:
        # 同名不同盘，宁可报错也不猜——猜错会拼出损坏的文件
        return None, '同名块有 %d 个，无法确定用哪个' % len(hits)
    return None, '块文件不存在（未打包）'


# ── 块内部格式 ──────────────────────────────────────────────────────────────
#
#   MiniNAS 的块不是裸数据，每块都套了一层壳（见 nas_server.py 开头注释）：
#
#       [n"文件名"] <二进制内容> [ed]
#        └─ 仅首块 ─┘            └ 4 字节尾标，每块都有 ┘
#
#   续写块没有头部，只有内容 + [ed]。
#   所以还原时必须先把这两层壳剥掉，否则拼出来的是文件名和 [ed] 混在数据里的废物。
#
HEADER_RE = re.compile(rb'^\[n("(?:\\.|[^"\\])*")\]', re.S)
ED_TAIL = b'[ed]'


def inspect_chunk(path, is_first):
    """量一个块里真正属于文件内容的有多少字节。返回 (载荷大小, 头里记的名字)。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0, None

    head_len = 0
    header_name = None
    tail_len = 0

    try:
        with open(path, 'rb') as f:
            if is_first:
                head = f.read(8192)
                m = HEADER_RE.match(head)
                if m:
                    head_len = m.end()
                    try:
                        header_name = json.loads(m.group(1).decode('utf-8'))
                    except Exception:
                        header_name = None
            if size >= 4:
                f.seek(size - 4)
                if f.read(4) == ED_TAIL:
                    tail_len = 4
    except OSError:
        return 0, None

    return max(size - head_len - tail_len, 0), header_name


def iter_chunk_payload(path, is_first):
    """流式吐出块里的真实内容（已剥壳）。大文件不会一次读进内存。"""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        start = 0
        if is_first:
            head = f.read(8192)
            m = HEADER_RE.match(head)
            if m:
                start = m.end()

        tail = 0
        if size >= 4:
            f.seek(size - 4)
            if f.read(4) == ED_TAIL:
                tail = 4

        f.seek(start)
        left = max(size - start - tail, 0)
        while left > 0:
            buf = f.read(min(1048576, left))
            if not buf:
                break
            left -= len(buf)
            yield buf


# ── 显示 ────────────────────────────────────────────────────────────────────
def human(n):
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return ('%.0f%s' % (n, unit)) if unit == 'B' else ('%.1f%s' % (n, unit))
        n /= 1024
    return '%.1fGB' % n


def fmt_time(ts):
    if not ts:
        return '-'
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
    except Exception:
        return '-'


def die(msg):
    sys.stderr.write('错误：%s\n' % msg)
    sys.exit(1)


# ── 命令 ────────────────────────────────────────────────────────────────────
def cmd_info(args):
    data_root = find_data_root(args.data)
    records, ipath = load_index(data_root)
    by_drive, by_name = build_chunk_map(data_root)

    files = [r for r in records if not r['is_dir']]
    dirs = [r for r in records if r['is_dir']]
    declared = sum(r['size'] for r in files)

    total_chunks = sum(len(r['chunks']) for r in files)
    have = 0
    for r in files:
        for c in r['chunks']:
            p, _ = resolve_chunk(c, by_drive, by_name)
            if p:
                have += 1

    packed = 0
    chunk_count = 0
    for hits in by_name.values():
        for p in hits:
            chunk_count += 1
            packed += inspect_chunk(p, True)[0]

    print('数据目录  : %s' % data_root)
    print('索引文件  : %s' % ipath)
    print('条目      : %d 个（文件 %d / 目录 %d）' % (len(records), len(files), len(dirs)))
    print('索引声明  : %s（NAS 上曾经有的全部内容）' % human(declared))
    print("实有数据块: %d 个文件，有效内容 %s" % (chunk_count, human(packed)))
    print('块覆盖    : %d / %d 块可用（%.1f%%）'
          % (have, total_chunks, (have * 100.0 / total_chunks) if total_chunks else 0))
    print()
    print('能完整还原的文件比索引少，是正常的：这个包只打包了一部分数据块。')
    print('跑 `python nasdat.py check` 看具体哪些能还原。')


def cmd_list(args):
    data_root = find_data_root(args.data)
    records, _ = load_index(data_root)
    by_drive, by_name = build_chunk_map(data_root)

    def ok(r):
        if r['is_dir']:
            return True
        return all(resolve_chunk(c, by_drive, by_name)[0] for c in r['chunks'])

    if args.tree:
        nodes = {}
        for r in records:
            rel = safe_relpath(r['name'])
            if not rel:
                continue
            parts = rel.split(os.sep)
            cur = nodes
            for p in parts[:-1]:
                cur = cur.setdefault(p + '/', {})
            cur[parts[-1] + ('/' if r['is_dir'] else '')] = r
        print_tree(nodes, '', ok)
        return

    for r in sorted(records, key=lambda x: x['name']):
        mark = 'DIR ' if r['is_dir'] else ('  ok' if ok(r) else '  --')
        if not r['is_dir'] and not ok(r) and not args.missing:
            pass
        print('%s  %10s  %-16s  %s'
              % (mark, '-' if r['is_dir'] else human(r['size']),
                 fmt_time(r['time']), r['name']))
    print()
    print('标记：ok = 数据齐全  -- = 缺块（未打包）  DIR = 目录')


def print_tree(nodes, prefix, okf):
    keys = sorted(nodes.keys(), key=lambda k: (not k.endswith('/'), k.lower()))
    for i, k in enumerate(keys):
        last = (i == len(keys) - 1)
        branch = '└── ' if last else '├── '
        node = nodes[k]
        if k.endswith('/'):
            print(prefix + branch + k)
            print_tree(node, prefix + ('    ' if last else '│   '), okf)
        else:
            r = node
            mark = '' if okf(r) else '   [缺块]'
            print('%s%s%s  (%s)%s' % (prefix, branch, k, human(r['size']), mark))


def cmd_check(args):
    data_root = find_data_root(args.data)
    records, _ = load_index(data_root)
    by_drive, by_name = build_chunk_map(data_root)
    files = [r for r in records if not r['is_dir']]

    full, partial, missing = [], [], []
    for r in files:
        resolved = [(c,) + resolve_chunk(c, by_drive, by_name) for c in r['chunks']]
        got = [x for x in resolved if x[1]]
        if not resolved:
            # 空文件（size 0）没有块，也算还原得出来
            (full.append((r, got)) if r['size'] == 0 else missing.append((r, resolved)))
        elif len(got) == len(resolved):
            avail = sum(inspect_chunk(x[1], i == 0)[0] for i, x in enumerate(got))
            if avail >= r['size']:
                full.append((r, got))
            else:
                partial.append((r, got, '块里只有 %s 有效内容，文件需要 %s'
                                % (human(avail), human(r['size']))))
        elif got:
            partial.append((r, got, '缺 %d / %d 块' % (len(resolved) - len(got), len(resolved))))
        else:
            missing.append((r, resolved))

    full_size = sum(r['size'] for r, _ in full)
    print('可完整还原 : %d 个文件，共 %s' % (len(full), human(full_size)))
    print('块不全     : %d 个' % len(partial))
    print('完全没打包 : %d 个' % len(missing))
    print()

    if full and not args.quiet:
        print('── 可完整还原 ──')
        for r, got in full[:args.show]:
            print('  %10s  %s' % (human(r['size']), r['name']))
        if len(full) > args.show:
            print('  …… 还有 %d 个' % (len(full) - args.show))

    if partial and not args.quiet:
        print()
        print('── 块不全（%d 个）──' % len(partial))
        for r, got, why in partial[:args.show]:
            print('  %10s  %s  ← %s' % (human(r['size']), r['name'], why))
        if len(partial) > args.show:
            print('  …… 还有 %d 个' % (len(partial) - args.show))

    if missing and not args.quiet:
        print()
        print('── 完全没打包（前 %d 个）──' % min(len(missing), 12))
        for r, _res in missing[:12]:
            print('  %10s  %s' % (human(r['size']), r['name']))
        if len(missing) > 12:
            print('  …… 还有 %d 个' % (len(missing) - 12))


def cmd_extract(args):
    data_root = find_data_root(args.data)
    records, _ = load_index(data_root)
    by_drive, by_name = build_chunk_map(data_root)

    out = os.path.abspath(args.out or os.path.join(os.getcwd(), '还原'))
    only = args.only.replace('\\', '/').lower() if args.only else None

    files = [r for r in records if not r['is_dir']]
    if only:
        files = [r for r in files if only in r['name'].replace('\\', '/').lower()]

    dirs = [r for r in records if r['is_dir']]
    if only:
        dirs = [r for r in dirs if only in r['name'].replace('\\', '/').lower()]

    if not args.dry_run:
        os.makedirs(out, exist_ok=True)
        for r in dirs:
            rel = safe_relpath(r['name'])
            if rel:
                os.makedirs(os.path.join(out, rel), exist_ok=True)

    ok = skip = broken = 0
    bytes_out = 0
    problems = []

    for idx, r in enumerate(sorted(files, key=lambda x: x['name']), 1):
        rel = safe_relpath(r['name'])
        if not rel:
            problems.append((r['name'], '非法文件名'))
            broken += 1
            continue

        dest = os.path.join(out, rel)
        if os.path.exists(dest) and not args.overwrite:
            if os.path.getsize(dest) == r['size']:
                skip += 1
                continue
            problems.append((r['name'], '目标已存在且大小不符（加 --overwrite）'))
            broken += 1
            continue

        resolved = []
        for c in r['chunks']:
            p, why = resolve_chunk(c, by_drive, by_name)
            resolved.append((c, p, why))

        missing = [x for x in resolved if not x[1]]
        if missing and not args.partial:
            problems.append((r['name'], missing[0][2] or '缺块'))
            broken += 1
            if not args.quiet:
                sys.stdout.write('\r[%d/%d] 跳过（缺块）%s' % (idx, len(files), ' ' * 30))
            continue

        written = 0
        if not args.dry_run:
            os.makedirs(os.path.dirname(dest) or out, exist_ok=True)
            try:
                with open(dest, 'wb') as w:
                    for i, (_c, p, _why) in enumerate(resolved):
                        if not p:
                            continue
                        remain = r['size'] - written
                        if remain <= 0:
                            break
                        for buf in iter_chunk_payload(p, i == 0):
                            if remain <= 0:
                                break
                            if len(buf) > remain:
                                buf = buf[:remain]
                            w.write(buf)
                            remain -= len(buf)
                            written += len(buf)
            except OSError as e:
                problems.append((r['name'], '写入失败：%s' % e))
                broken += 1
                continue
        else:
            written = sum(inspect_chunk(p, i == 0)[0]
                          for i, (_c, p, _w) in enumerate(resolved) if p)

        if written == r['size']:
            ok += 1
            bytes_out += written
        else:
            problems.append((r['name'], '大小不符：写出 %d / 应为 %d' % (written, r['size'])))
            broken += 1
            if not args.dry_run and os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass

        if not args.quiet:
            sys.stdout.write('\r[%d/%d] %s%s'
                             % (idx, len(files), r['name'][:40], ' ' * 20))
            sys.stdout.flush()

    if not args.quiet:
        sys.stdout.write('\r' + ' ' * 76 + '\r')

    print('还原完成')
    print('  成功 : %d 个文件，共 %s' % (ok, human(bytes_out)))
    print('  跳过 : %d 个（已存在）' % skip)
    print('  失败 : %d 个' % broken)
    print('  输出 : %s%s' % (out, '（--dry-run，未落盘）' if args.dry_run else ''))

    if problems:
        print()
        print('── 未还原明细（前 20 条）──')
        for name, why in problems[:20]:
            print('  %-46s %s' % (name[:46], why))
        if len(problems) > 20:
            print('  …… 还有 %d 条' % (len(problems) - 20))


# ── 入口 ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        prog='nasdat',
        description='MiniNAS 数据块还原工具 — 把 nasN 切块拼回原文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例:\n'
               '  python nasdat.py info\n'
               '  python nasdat.py check\n'
               '  python nasdat.py extract -o 还原\n'
               '  python nasdat.py extract -o 还原 --only 塔菲\n')
    ap.add_argument('cmd', choices=['info', 'list', 'check', 'extract'],
                    help='info=概览  list=列条目  check=体检  extract=还原')
    ap.add_argument('--data', help='数据目录（all/ 的位置）')
    ap.add_argument('--tree', action='store_true', help='list: 树形显示')
    ap.add_argument('--missing', action='store_true', help='list: 只看缺块的')
    ap.add_argument('-o', '--out', help='extract: 输出目录（默认 ./还原）')
    ap.add_argument('--only', help='extract: 只处理路径包含该子串的条目')
    ap.add_argument('--overwrite', action='store_true', help='extract: 覆盖同名文件')
    ap.add_argument('--partial', action='store_true', help='extract: 块不全也输出残缺文件')
    ap.add_argument('--dry-run', action='store_true', help='extract: 只演算不写盘')
    ap.add_argument('--quiet', action='store_true', help='安静模式')
    ap.add_argument('--show', type=int, default=25, help='check: 每类显示条数')
    args = ap.parse_args()

    {'info': cmd_info, 'list': cmd_list,
     'check': cmd_check, 'extract': cmd_extract}[args.cmd](args)


if __name__ == '__main__':
    main()
