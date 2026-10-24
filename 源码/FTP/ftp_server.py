# -*- coding: utf-8 -*-
"""
MiniNAS-FTP - 局域网FTP服务器 (文件互传用)   v2
改动:
  1) 已删除"必须输密码"的限制 -> 支持匿名登录(免密), 同时也保留原账号兼容
  2) 不再只限 users 文件夹 -> 根目录下自动生成 C盘/D盘/E盘 快捷入口(junction),
     登录后点 C盘/D盘/E盘 即可访问整个盘符
账号: 匿名(无密码) 或 ciallo0721_cmd/<你的密码>   端口: 21
"""
import os
import subprocess
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from pyftpdlib.filesystems import AbstractedFS

PORT = 21
ROOT = r'C:\Users\ciallo0721_cmd'      # FTP 根目录(匿名登录后看到的顶层)
USER = 'ciallo0721_cmd'                # 保留原账号(兼容旧客户端)
PASS = os.environ.get('FTP_PASS', 'change-me')   # 公开仓库已脱敏：用环境变量 FTP_PASS 传
PERM = 'elradfmwMT'                    # 读+写+删+改名+续传+建目录+改权限, 全开
PASV_START, PASV_END = 20000, 20050    # 被动模式端口区间

# 关闭 realpath 越狱检查: 允许通过 junction 进入其他盘符
class OpenFS(AbstractedFS):
    def validpath(self, path):
        return True


def make_drive_links(root):
    """在 FTP 根目录下建 C盘/D盘/E盘 junction 入口(指向对应盘符根)"""
    links = {
        'C盘': 'C:\\',
        'D盘': 'D:\\',
        'E盘': 'E:\\',
    }
    for name, target in links.items():
        if not os.path.isdir(target):
            continue
        link = os.path.join(root, name)
        if os.path.isdir(link) or os.path.islink(link):
            continue
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            r = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                               capture_output=True, creationflags=flags, timeout=10)
            print('created drive link: %s -> %s  (%s)' % (link, target, r.stdout.decode('gbk', 'replace').strip()))
        except Exception as e:
            print('create link failed %s: %s' % (name, e))


def main():
    os.makedirs(ROOT, exist_ok=True)
    make_drive_links(ROOT)

    authorizer = DummyAuthorizer()
    # 免密匿名: 登录时用户名填 anonymous / 或直接回车
    authorizer.add_anonymous(ROOT, perm=PERM)
    # 保留原账号作为兼容选项
    authorizer.add_user(USER, PASS, ROOT, perm=PERM)

    class Handler(FTPHandler):
        abstracted_fs = OpenFS

    handler = Handler
    handler.authorizer = authorizer
    handler.passive_ports = range(PASV_START, PASV_END)
    handler.banner = 'MiniNAS-FTP ready (anonymous ok / C盘 D盘 E盘 at root). Hi ciallo!'

    server = FTPServer(('0.0.0.0', PORT), handler)
    print('=' * 52)
    print('  MiniNAS-FTP v2 已启动!')
    print('  匿名免密:  可登录')
    print('  原账号:    %s / %s' % (USER, PASS))
    print('  根目录:    %s' % ROOT)
    print('  盘符入口:  根目录下 C盘/D盘/E盘 (junction)')
    print('  本机:      ftp://localhost/')
    print('  局域网:    ftp://192.168.18.67/  (端口%d)' % PORT)
    print('  被动端口:  %d-%d' % (PASV_START, PASV_END))
    print('  按 Ctrl+C 停止')
    print('=' * 52)
    server.serve_forever()


if __name__ == '__main__':
    main()
