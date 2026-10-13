"""AES 加密：复现认证页前端（CryptoJS）的密码加密逻辑。

认证页 main.js 里的加密（Bn.aesEncrypt）：
    AES-ECB 模式 + PKCS7 填充，密钥为 base64 编码的 16 字节（croypto），
    明文为 UTF-8，输出为 base64。

依赖 pycryptodome（仅加密认证需要；未安装时降级为明文/占位，不崩溃）。
"""
from __future__ import annotations

import base64

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    _HAS_PYCRYPTODOME = True
except ImportError:  # pragma: no cover
    _HAS_PYCRYPTODOME = False


def has_crypto() -> bool:
    return _HAS_PYCRYPTODOME


def aes_ecb_pkcs7_encrypt_b64(key_b64: str, plaintext: str) -> str:
    """AES-128/192/256-ECB-PKCS7 加密，密钥与密文均为 base64。

    等价于 CryptoJS：CryptoJS.AES.encrypt(plaintext, CryptoJS.enc.Base64.parse(key_b64),
    {mode: ECB, padding: Pkcs7}).toString()
    """
    if not _HAS_PYCRYPTODOME:
        raise RuntimeError("未安装 pycryptodome，无法进行 AES 加密")
    key = base64.b64decode(key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    data = pad(plaintext.encode("utf-8"), AES.block_size)
    return base64.b64encode(cipher.encrypt(data)).decode("ascii")


def aes_ecb_pkcs7_decrypt_b64(key_b64: str, ciphertext_b64: str) -> str:
    """AES-ECB-PKCS7 解密（密钥与密文均为 base64），用于自测与逆向验证。"""
    from Crypto.Util.Padding import unpad
    key = base64.b64decode(key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    data = base64.b64decode(ciphertext_b64)
    return unpad(cipher.decrypt(data), AES.block_size).decode("utf-8")
