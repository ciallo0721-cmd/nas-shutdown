# -*- coding: utf-8 -*-
"""
nas_auth.py - MiniNAS 管理员口令保护 (纯 Python, 零第三方依赖)

设计:
  * 口令不以任何形式明文存储。代码里只有一段 AES-256-CBC 密文(CIPHER)。
  * 校验 = 用输入口令 PBKDF2 派生出密钥 -> 解 CIPHER -> 比对固定魔数。
  * 登录成功后签发 HMAC-SHA256 签名令牌, 放 cookie, 默认 7 天。
  * AES 为 FIPS-197 标准实现(已用官方测试向量自检, 见 __main__)。
"""
import base64
import hashlib
import hmac
import os
import time

# ================= AES-256 (FIPS-197) =================

_SBOX = bytes((
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
))
_INV_SBOX = bytes(_SBOX.index(i) for i in range(256))


def _xtime(a):
    a <<= 1
    return (a ^ 0x1b) & 0xff if a & 0x100 else a


def _gmul(a, b):
    """GF(2^8) 乘法"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p


def _expand_key(key):
    """AES-256 密钥扩展 -> (w, 轮数)"""
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rc = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rc
            rc = _xtime(rc)
        elif i % nk == 4:          # AES-256 专属
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _add_round_key(s, w, rnd):
    rk = w[rnd * 4:rnd * 4 + 4]
    for c in range(4):
        for r in range(4):
            s[r + 4 * c] ^= rk[c][r]


def _encrypt_block(block, w, nr):
    s = list(block)
    _add_round_key(s, w, 0)
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]                      # SubBytes
        t = list(s)                                    # ShiftRows
        for r in range(1, 4):
            for c in range(4):
                s[r + 4 * c] = t[r + 4 * ((c + r) % 4)]
        if rnd != nr:                                  # MixColumns
            ns = list(s)
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                ns[4 * c + 0] = _gmul(a[0], 2) ^ _gmul(a[1], 3) ^ a[2] ^ a[3]
                ns[4 * c + 1] = a[0] ^ _gmul(a[1], 2) ^ _gmul(a[2], 3) ^ a[3]
                ns[4 * c + 2] = a[0] ^ a[1] ^ _gmul(a[2], 2) ^ _gmul(a[3], 3)
                ns[4 * c + 3] = _gmul(a[0], 3) ^ a[1] ^ a[2] ^ _gmul(a[3], 2)
            s = ns
        _add_round_key(s, w, rnd)
    return bytes(s)


def _decrypt_block(block, w, nr):
    s = list(block)
    _add_round_key(s, w, nr)
    for rnd in range(nr - 1, -1, -1):
        t = list(s)                                    # InvShiftRows
        for r in range(1, 4):
            for c in range(4):
                s[r + 4 * c] = t[r + 4 * ((c - r) % 4)]
        s = [_INV_SBOX[b] for b in s]                  # InvSubBytes
        _add_round_key(s, w, rnd)
        if rnd != 0:                                   # InvMixColumns
            ns = list(s)
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                ns[4 * c + 0] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
                ns[4 * c + 1] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
                ns[4 * c + 2] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
                ns[4 * c + 3] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
            s = ns
    return bytes(s)


def _cbc_encrypt(key, iv, data):
    w, nr = _expand_key(key)
    pad = 16 - (len(data) % 16)
    data = data + bytes([pad]) * pad
    out, prev = b'', iv
    for i in range(0, len(data), 16):
        prev = _encrypt_block(bytes(a ^ b for a, b in zip(data[i:i + 16], prev)), w, nr)
        out += prev
    return out


def _cbc_decrypt(key, iv, data):
    w, nr = _expand_key(key)
    out, prev = b'', iv
    for i in range(0, len(data), 16):
        c = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(c, w, nr), prev))
        prev = c
    if out:
        pad = out[-1]
        if 1 <= pad <= 16:
            out = out[:-pad]
    return out

# ================= 口令 =================

_SALT = b'CHANGE-ME__RANDOM__SALT__BEFORE_DEPLOY'   # 公开仓库已脱敏：部署前务必换成自己的随机串


def _derive(password):
    """口令 -> (加密密钥32B, MAC密钥32B)"""
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), _SALT, 60000, 96)
    return dk[:32], dk[32:64]


# 管理员口令密文 (AES-256-CBC, 明文不落盘; 修改口令用 make_cipher.py 重新生成)
ADMIN_CIPHER = 'PENDING'                             # 公开仓库已脱敏：首次启动引导设置新口令
_MAGIC = b'MiniNAS-ADMIN-VERIFY'          # 16 字节校验魔数(整块)


def _load_cipher():
    raw = base64.b64decode(ADMIN_CIPHER)
    return raw[:16], raw[16:]             # (iv, 密文)


def verify_password(password):
    """校验管理员口令"""
    if not password or ADMIN_CIPHER == 'PENDING':
        return False
    try:
        enc_key, _ = _derive(password)
        iv, ct = _load_cipher()
        return hmac.compare_digest(_cbc_decrypt(enc_key, iv, ct), _MAGIC)
    except Exception:
        return False


def make_cipher(password):
    """生成口令密文(仅供改密码时使用, 不要把结果之外的任何东西写进代码)"""
    enc_key, _ = _derive(password)
    iv = hashlib.sha256(_SALT + b'iv' + password.encode('utf-8')).digest()[:16]
    return base64.b64encode(iv + _cbc_encrypt(enc_key, iv, _MAGIC)).decode()

# ================= 会话令牌 =================

# 令牌签名盐: 运行时随机生成并落盘, 不写进源码。
# 2026-10-18 加固: 原来 _TOKEN_KEY 完全由源码常量(_SALT + ADMIN_CIPHER)派生,
# 谁拿到源码谁就能离线算出密钥、伪造 nas_admin cookie 直接进后台。
# 现在盐存在数据目录 C:\NAS\.token_salt 里(与源码分离), 源码泄露/打包也伪造不了令牌。
# 注意: _SALT 仍留着给口令校验用, 不能动(动了 ADMIN_CIPHER 就解不开了)。
_TOKEN_SALT_DIR = r'C:\NAS'
_TOKEN_SALT_FILE = os.path.join(_TOKEN_SALT_DIR, '.token_salt')


def _token_salt():
    """读取(或首次生成)令牌盐"""
    try:
        with open(_TOKEN_SALT_FILE, 'rb') as f:
            s = f.read().strip()
        if len(s) >= 32:
            return s
    except OSError:
        pass
    s = os.urandom(32).hex().encode()
    for d in (_TOKEN_SALT_DIR, os.path.dirname(os.path.abspath(__file__))):
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, '.token_salt'), 'wb') as f:
                f.write(s)
            break
        except OSError:
            continue
    return s


_TOKEN_KEY = hashlib.sha256(hashlib.sha256(_token_salt() + ADMIN_CIPHER.encode()).digest()
                            + b'nas-admin-token-v1').digest()
COOKIE_NAME = 'nas_admin'
TOKEN_DAYS = 7


def make_token(days=TOKEN_DAYS):
    exp = int(time.time()) + days * 86400
    msg = str(exp).encode()
    sig = hmac.new(_TOKEN_KEY, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + b'|' + sig).decode().rstrip('=')


def check_token(token):
    """令牌是否有效(签名对 + 没过期)"""
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
        msg, sig = raw.split(b'|', 1)
        if not hmac.compare_digest(hmac.new(_TOKEN_KEY, msg, hashlib.sha256).digest(), sig):
            return False
        return int(msg) > time.time()
    except Exception:
        return False


if __name__ == '__main__':
    # ---- FIPS-197 附录 C.3 官方测试向量自检 ----
    key = bytes(range(32))
    pt = bytes.fromhex('00112233445566778899aabbccddeeff')
    w, nr = _expand_key(key)
    got = _encrypt_block(pt, w, nr).hex()
    want = '8ea2b7ca516745bfeafc49904b496089'
    print('AES-256 Encrypt:', got, '==', want, '->', 'PASS' if got == want else 'FAIL')
    back = _decrypt_block(bytes.fromhex(got), w, nr).hex()
    print('AES-256 Decrypt:', back, '->', 'PASS' if back == pt.hex() else 'FAIL')
    # ---- CBC 往返 ----
    iv = bytes(range(16))
    for msg in (b'', b'x', b'hello world', b'A' * 33):
        assert _cbc_decrypt(key, iv, _cbc_encrypt(key, iv, msg)) == msg
    print('CBC round-trip: PASS')
    # ---- 口令 ----
    import sys
    if len(sys.argv) > 1:
        print('cipher for new password:', make_cipher(sys.argv[1]))
    else:
        print('改密码用法: python nas_auth.py <新口令>  -> 把输出的 CIPHER 填回 ADMIN_CIPHER')
