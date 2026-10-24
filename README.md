# nas.ciallo0721-cmd.top — 停机页面与存档

2026 年 10 月 24 日，MiniNAS 永久停止服务。

这个仓库是它的墓碑，也是它的档案柜：停服页、全部源码、以及抢救出来的那部分数据。

> 灯关了，人还在屋里。

---

## 为什么停了

1. **老笔记本撑不住了** —— 那台机器跑了太久，真的到极限了。
2. **没人来，没人看，全是机器人** —— 本来是给人用的，结果每天来的只有爬虫。
3. **致想用这个的学生们：抱歉，用不了了。**

---

## 仓库里有什么

```
index.html          停服页（GitHub Pages 托管 nas.ciallo0721-cmd.top）
CNAME               自定义域名
源码/               MiniNAS 完整源码
   MiniNAS/         主服务：Flask + 自研分块存储 + Cloudflare Tunnel
   FTP/             局域网 FTP 服务
数据块/             数据块还原工具与说明
   nasdat.py        把 nasN 拼回原文件的工具
   README.md        数据包说明 + 块格式文档
```

数据包本体（456 MB）不在 git 里，在 [Releases](https://github.com/ciallo0721-cmd/nas-shutdown/releases)。

---

## 关于 MiniNAS

一台跑在旧笔记本上的家庭 NAS。因为笔记本本身撑不住大流量，也没有公网 IP，所以设计得挺拧巴，但能跑：

- **文件切块存**：每个文件切成块，写成 `nas`、`nas1`、`nas2`…，每块套一层 `[n"路径"]内容[ed]` 的壳，靠 `index.json` 索引还原。见 [`数据块/README.md`](数据块/README.md)。
- **按盘分配**：C/D/E 三个盘轮流写，C 盘有 100 MB 兜底上限（怕把系统盘塞爆）。
- **自研鉴权**：手写 AES-256-CBC 做管理员口令加密，PBKDF2 派生密钥，令牌签名密钥的盐存在数据目录而不是源码里（`nas_auth.py` 里有注释，是 10 月 18 日加固时改的）。
- **访客追踪**：`nas_track.py` + `idinfo.py`，记录访客、蜜罐命中、猜口令行为。
- **公网入口**：Cloudflare Named Tunnel，不带公网 IP 也能有固定域名。

技术栈：Python 3.9 / Flask / waitress / pyftpdlib。没有数据库，索引就是一个 JSON。

---

## ⚠️ 源码已脱敏

这是公开仓库，所以下面几处原值被换掉了。**拿这份代码去跑之前必须先改回来**，否则起不来或直接裸奔：

| 位置 | 原值 | 现在 |
|---|---|---|
| `MiniNAS/nas_auth.py` `_SALT` | 固定盐 | 占位串，换随机值 |
| `MiniNAS/nas_auth.py` `ADMIN_CIPHER` | 管理员口令密文 | `'PENDING'`，首次启动引导设置 |
| `FTP/ftp_server.py` `PASS` | 明文密码 | 读环境变量 `FTP_PASS` |
| `MiniNAS/cloudflared.exe` | 55 MB 二进制 | 已移出，自行下载 |

另外，数据包里带着 `.token_salt`。**如果你把这份源码和那个数据包一起重新跑起来**，记得换掉 `_SALT` 并删掉旧 `.token_salt`——两者凑一起能推导出签发管理员令牌的密钥。服务已经停了，所以现在无所谓，但别带着旧值复活。

`MiniNAS.log` 和 `_cf_h2_err.log` 也从仓库里剔了，里面是真实访客 IP，不该公开。

---

## 许可

源码随便看随便抄，出了事别找我。

里面那些照片和视频是我的，别搬。

---

ciallo0721-cmd · 2026-10-24
