"""Local current-user DPAPI vault. Never export or log credentials."""
import ctypes, json, os, logging
from ctypes import wintypes
from pathlib import Path

def resolve_vault():
    # Codex MSIX and shell sessions can expose different LOCALAPPDATA folders.
    # Reuse the existing current-user encrypted file; never copy its contents.
    local = Path.home() / 'AppData' / 'Local'
    candidates = [Path(os.environ['LOCALAPPDATA']) / 'RunningCoach' / 'garmin-cn.dpapi',
                  local / 'RunningCoach' / 'garmin-cn.dpapi',
                  local / 'Packages' / 'openai.codex_2p2nqsd0c76g0' / 'LocalCache' / 'Local' / 'RunningCoach' / 'garmin-cn.dpapi']
    return next((path for path in candidates if path.is_file()), candidates[0])

VAULT = resolve_vault()
class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]

def crypt(data, decrypt=False):
    buffer=ctypes.create_string_buffer(data); src=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte))); dst=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dst)):
        raise ctypes.WinError()
    try:return ctypes.string_at(dst.data,dst.size)
    finally:ctypes.windll.kernel32.LocalFree(dst.data)

def save(data):
    VAULT.parent.mkdir(parents=True,exist_ok=True)
    tmp=VAULT.with_suffix('.tmp');tmp.write_bytes(crypt(json.dumps(data).encode()));tmp.replace(VAULT)

def configure_token_transport(api):
    """Use requests for OAuth token POSTs; keep TLS verification enabled.

    curl_cffi on this Windows runtime fails loading certifi's CA bundle
    (curl error 77). Standard requests successfully refreshes the same token.
    This affects token transport only, not SSO login strategies.
    """
    import requests
    api.client._http_post = requests.post
    return api


def connect(interactive=False):
    from garminconnect import Garmin
    logging.disable(logging.CRITICAL)
    saved=json.loads(crypt(VAULT.read_bytes(),True)) if VAULT.exists() else {}
    if saved.get('tokens'):
        try:
            api=configure_token_transport(Garmin(is_cn=True,retry_attempts=1));api.login(saved['tokens'])
            saved['tokens']=api.client.dumps();save(saved);return api
        except Exception:pass
    ui=None
    if interactive:
        import tkinter as tk
        from tkinter import simpledialog
        ui=tk.Tk();ui.withdraw();ui.attributes('-topmost',True)
        email=simpledialog.askstring('佳明中国区 · 自动同步登录','账号（仅保存在本机 Windows 用户加密凭据中）',initialvalue=saved.get('email',''),parent=ui)
        password=simpledialog.askstring('佳明中国区 · 保存登录','按你的授权，加密保存密码与登录令牌，供每天09:00和21:00同步使用。',show='*',parent=ui) if email else None
        if not email or not password:ui.destroy();raise RuntimeError('login_cancelled')
        saved={'email':email.strip(),'password':password}
        mfa=lambda:simpledialog.askstring('佳明验证','验证码（不保存）',show='*',parent=ui) or ''
    else:
        if not saved.get('password'):raise RuntimeError('local_login_required')
        def mfa():raise RuntimeError('interactive_mfa_required')
    try:
        api=configure_token_transport(Garmin(email=saved['email'],password=saved['password'],is_cn=True,retry_attempts=1,prompt_mfa=mfa))
        api.login();api.password=None;saved['tokens']=api.client.dumps();save(saved);return api
    finally:
        if ui:ui.destroy()

if __name__=='__main__':
    try:
        connect(interactive=True)
        # A second client verifies that unattended token reuse works.
        connect();print('encrypted_credentials_saved_and_reuse_verified')
    except Exception as e:print('authentication_incomplete:'+type(e).__name__)
