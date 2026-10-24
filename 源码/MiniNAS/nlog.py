# -*- coding: utf-8 -*-
"""
nlog.py - MiniNAS 全项目统一彩色日志库
格式规范(用户钦定)：
  [2026-09-06-17:24] GET "/api/xxx" [200] [OK]
  时间戳=白  方法(GET/POST)=绿  路径=白(带引号)
  [OK]=绿  [Err]=红  [WARNING]=黄
  状态码: 2xx=绿 3xx=黄 4xx=红 5xx=高亮红

特性:
  - Windows 下 ctypes 开启 VT(ANSI), 开不了自动降级纯文本
  - 所有日志同时追加写入日志文件(默认 ./MiniNAS.log, 可用环境变量 NLOG_FILE 覆盖)
  - 控制台输出带 ANSI 彩色, 文件里存的是去色纯文本
"""
import os
import re
import sys
import datetime

try:
    import ctypes
    _hdl = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    _mode = ctypes.c_uint32()
    if ctypes.windll.kernel32.GetConsoleMode(_hdl, ctypes.byref(_mode)):
        ctypes.windll.kernel32.SetConsoleMode(
            _hdl, _mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        _VT = True
    else:
        _VT = False
except Exception:
    _VT = False

# ---- ANSI 色板 ----
RESET = '\033[0m'
WHITE = '\033[97m'    # 时间戳 / 路径 / 正文
GREEN = '\033[32m'    # [OK] / 请求方法 / 2xx
YELLOW = '\033[33m'   # [WARNING] / 3xx
RED = '\033[31m'      # [Err] / 4xx
BRED = '\033[91m'     # 5xx (最严重的红, 最扎眼)
CYAN = '\033[36m'     # 模块名/标签
DIM = '\033[90m'      # 次要说明(灰)

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# 日志文件: 默认当前目录 MiniNAS.log, 可用 NLOG_FILE 环境变量改路径
LOG_FILE = os.environ.get('NLOG_FILE') or 'MiniNAS.log'

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def _c(text, code=WHITE):
    """上色(终端不支持 VT 时原样输出)"""
    if not _VT:
        return text
    return code + text + RESET


def _ts():
    return datetime.datetime.now().strftime('[%Y-%m-%d-%H:%M]')


def _plain(text):
    """去掉 ANSI 颜色码 -> 纯文本"""
    return _ANSI_RE.sub('', text)


def _out(colored):
    """统一出口: 彩色打屏 + 去色落盘"""
    print(colored, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(_plain(colored) + '\n')
    except Exception:
        pass  # 文件写不了不致命


# ================= 通用 =================

def info(msg):
    """普通信息: [时间] 消息"""
    _out('%s %s' % (_c(_ts()), _c(msg)))


def detail(msg):
    """次要/深挖信息(灰字, 用于"非常详细"的细节行)"""
    _out('%s %s' % (_c(_ts(), DIM), _c(msg, DIM)))


def ok(msg):
    """成功: [时间] 消息 [OK]"""
    _out('%s %s %s' % (_c(_ts()), _c(msg), _c('[OK]', GREEN)))


def warn(msg):
    """警告: [时间] 消息 [WARNING]"""
    _out('%s %s %s' % (_c(_ts()), _c(msg), _c('[WARNING]', YELLOW)))


def err(msg):
    """失败: [时间] 消息 [Err]"""
    _out('%s %s %s' % (_c(_ts()), _c(msg, RED), _c('[Err]', RED)))


def line(ch='=', n=46):
    """分隔线"""
    _out(_c(ch * n, DIM))


def tag(label, msg, ok_=True):
    """带模块标签: [时间] [模块] 消息 [OK/Err]"""
    flag = _c('[OK]', GREEN) if ok_ else _c('[Err]', RED)
    _out('%s %s %s %s' % (_c(_ts()), _c('[' + label + ']', CYAN), _c(msg), flag))


def http(method, path, code):
    """
    HTTP 访问日志(用户钦定格式):
    [时间] METHOD "path" [状态码] [OK/Err]
    """
    method = (method or '?').upper()
    if 200 <= code < 300:
        c_code, flag = GREEN, _c('[OK]', GREEN)
    elif 300 <= code < 400:
        c_code, flag = YELLOW, _c('[WARNING]', YELLOW)
    elif 400 <= code < 500:
        c_code, flag = RED, _c('[Err]', RED)
    else:
        c_code, flag = BRED, _c('[Err]', BRED)
    _out('%s %s %s %s %s' % (
        _c(_ts()),                      # [时间]          白
        _c(method, GREEN),              # GET/POST        绿
        _c('"%s"' % path, WHITE),       # "/api/xxx"      白
        _c('[%d]' % code, c_code),      # [200]           按状态码
        flag,                            # [OK]/[Err]     按状态码
    ))


def banner(title, subtitle='', ch='=', n=46):
    """开机横幅"""
    line(ch, n)
    _out(_c(title, CYAN))
    if subtitle:
        _out(_c(subtitle, DIM))
    line(ch, n)
