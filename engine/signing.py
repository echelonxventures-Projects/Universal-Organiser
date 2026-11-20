"""Signed updates: every release's SHA256SUMS is signed with the publisher's private key (RSA-3072, PKCS#1 v1.5,
SHA-256; made with `openssl dgst -sha256 -sign`). The public keys below are built into the program, so a release
that was not signed by the publisher is refused, even if it comes from the right address or a hacked account.
Checking needs nothing but Python (no extra packages). The private key never goes into the repository: it lives
in the publisher's own safe place and in the release workflow's secret UPDATE_SIGNING_KEY.

Several keys may be listed (a new key is added here one release before the old one is retired)."""
import hashlib, hmac

PUBLIC_KEYS = {
    "uo-2026": (int(
    "da9a3df1cdbeff6a8fcd1d329aae5078cef75cd2a261142e2dbede4475f3b4a75b9ced1b509b678977bbc05c9ce98d7e"
    "e067509083233fa6010eb2be143d13b80fd55ca25b1c2e53f9de5a0b549410ffe51b30495cc877a6a3e271a7cb3fe9bc"
    "c8a3fa84289c6d82393b32cc6ca5dbff66c003ed6df80b72bb9ff5e41730f00fdcf03155bdbe43a5d3e88a2f4058fed4"
    "fb0445bb0a1eadc8cb4415648f395d0c9030b45547089eedbdd6cbdd3d1eb6e11b0a09769db69b09c122dff825006afa"
    "c7cfb32fb109ea390509b12c830ccc818eef8423eb0730074ca96555629b3fdbfc62ed029248c9c4de5a82a2584a2512"
    "b1a52dc4ec9e2dff986186e26a713f87d138d4ddaa5e42f5caff41ad7cb03394053578f33eccc0c6288756ea9faf70fd"
    "d110a870315bd09480b596979b971b6f6d2c60c5a05e5c51a832985f9dcd9b2a254fd2301b836f47185a2f49b0932b0d"
    "5520113a7a1c43e2391ed4bfd16838cb81263f78327f6a7b41ee49ffe73939b24d4996af75b738b806ed69e68e536159", 16), 65537),
}
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")  # "this is a SHA-256 hash", in DER


def verify(data, signature, keys=None):
    """True when `signature` (bytes) is a valid signature of `data` (bytes) by one of the built-in keys."""
    for n, e in (keys or PUBLIC_KEYS).values():
        k = (n.bit_length() + 7) // 8
        if len(signature) != k:
            continue
        m = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
        want = b"\x00\x01" + b"\xff" * (k - 3 - len(_DIGEST_INFO) - 32) + b"\x00" + _DIGEST_INFO + hashlib.sha256(data).digest()
        if hmac.compare_digest(m, want):
            return True
    return False


def sign_file(path, key_file):
    """Write path + '.sig' with OpenSSL (publisher side: `uo package --feed … --sign KEY`)."""
    import subprocess
    r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_file, "-out", path + ".sig", path],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("Signing failed: " + (r.stderr.strip() or "openssl is needed"))
    with open(path, "rb") as f, open(path + ".sig", "rb") as s:
        if not verify(f.read(), s.read()):
            raise SystemExit("Signed, but the signature does not match the program's built-in keys: wrong key file?")
    return path + ".sig"
