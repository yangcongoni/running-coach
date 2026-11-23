"""Local second factor and revocable browser tokens for the owner account."""
import base64
from contextlib import closing
import hashlib
import hmac
import re
import secrets
import sqlite3
import struct
import sys
import time
from pathlib import Path

import web_account
sys.path.append(str(Path(web_account.__file__).resolve().parents[1] / 'garmin_sync'))
from garmin_secure_auth import crypt

TRUST_SECONDS = 90 * 86400
CODE_PERIOD = 30


def store_path():
    return web_account.account_file().with_name('web-second-factor.sqlite3')


def connect(create=False):
    path = store_path()
    uri = path.as_uri() + ('?mode=rwc' if create else '?mode=rw')
    return sqlite3.connect(uri, uri=True, timeout=5)


def new_factor(conn):
    conn.execute('DELETE FROM devices')
    conn.execute('INSERT OR REPLACE INTO factor VALUES(1,?,?,?)',
                 (secrets.token_hex(16), crypt(secrets.token_bytes(20)), -1))


def initialize():
    # Only the host-side tool may create or replace a factor.
    store_path().parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(create=True)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE IF NOT EXISTS factor(id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL, secret BLOB NOT NULL, last_step INTEGER NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS devices(digest TEXT PRIMARY KEY, owner TEXT NOT NULL, label TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL)')
        if not conn.execute('SELECT 1 FROM factor WHERE id=1').fetchone():
            new_factor(conn)


def generation():
    with closing(connect()) as conn:
        row = conn.execute('SELECT generation FROM factor WHERE id=1').fetchone()
        return row[0] if row else None


def local_secret():
    with closing(connect()) as conn:
        return crypt(conn.execute('SELECT secret FROM factor WHERE id=1').fetchone()[0], decrypt=True)


def otp(secret, step):
    digest = hmac.digest(secret, struct.pack('>Q', step), 'sha1')
    offset = digest[-1] & 15
    number = int.from_bytes(digest[offset:offset+4], 'big') & 0x7fffffff
    return f'{number % 1000000:06d}'


def token_digest(token):
    if token and re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()
    return None


def active(owner, epoch, digest=None):
    if not epoch:
        return False
    with closing(connect()) as conn:
        sql = 'SELECT 1 FROM factor WHERE id=1 AND generation=?'
        params = [epoch]
        if digest is not None:
            sql += ' AND EXISTS (SELECT 1 FROM devices WHERE digest=? AND owner=? AND expires>?)'
            params.extend([digest, owner, int(time.time())])
        return bool(conn.execute(sql, params).fetchone())


def verify_code(owner, epoch, code, remember, label, now=None):
    """Consume one time step and optionally issue a device cookie in the same transaction."""
    if not re.fullmatch(r'[0-9]{6}', code):
        return False, None
    now = int(time.time()) if now is None else now
    step = now // CODE_PERIOD
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT secret,last_step FROM factor WHERE id=1 AND generation=?', (epoch,)).fetchone()
        if not row:
            return False, None
        secret = crypt(row[0], decrypt=True)
        matched = next((n for n in (step,step-1,step+1) if n>row[1] and hmac.compare_digest(otp(secret,n),code)), None)
        if matched is None:
            return False, None
        conn.execute('UPDATE factor SET last_step=? WHERE id=1', (matched,))
        token = None
        if remember:
            conn.execute('DELETE FROM devices WHERE expires<=? OR owner<>?', (now, owner))
            token = secrets.token_urlsafe(32)
            conn.execute('INSERT INTO devices VALUES(?,?,?,?,?)', (token_digest(token),owner,label[:64],now,now+TRUST_SECONDS))
        return True, token


def manage():
    import tkinter as tk
    from tkinter import messagebox, ttk
    from urllib.parse import quote, urlencode
    from datetime import datetime
    root = tk.Tk()
    root.title('训练手记 · 登录验证器与常用设备')
    account = web_account.read_account()
    if not account:
        messagebox.showinfo('训练手记', '请先在本机设置公网登录账号。', parent=root)
        root.destroy()
        return
    initialize()
    box = ttk.Frame(root, padding=18)
    box.pack(fill='both',expand=True)
    ttk.Label(box,text='公网账号  '+account['username']).pack(anchor='w')
    def pairing():
        win=tk.Toplevel(root)
        win.title('绑定手机验证器')
        body=ttk.Frame(win,padding=16)
        body.pack()
        secret=base64.b32encode(local_secret()).decode('ascii').rstrip('=')
        ttk.Label(body,text='在手机验证器中选择“添加账号”，扫描二维码或输入下方密钥。').pack()
        uri='otpauth://totp/'+quote('训练手记:'+account['username'],safe='')+'?'+urlencode({'secret':secret,'issuer':'训练手记','digits':6,'period':CODE_PERIOD})
        try:
            import segno
            import io
            buf=io.BytesIO()
            segno.make_qr(uri).save(buf,kind='png',scale=5)
            image=tk.PhotoImage(master=win,data=base64.b64encode(buf.getvalue()).decode())
            label=ttk.Label(body,image=image)
            label.image=image
            label.pack()
        except ImportError:
            pass
        entry=ttk.Entry(body,width=40)
        entry.insert(0,secret)
        entry.configure(state='readonly')
        entry.pack(pady=8)
        ttk.Label(body,text='类型选“基于时间”，6 位数字，每 30 秒更新。').pack()
        ttk.Button(body,text='完成',command=win.destroy).pack(pady=8)

    def show_code():
        secret=local_secret()
        win=tk.Toplevel(root)
        win.title('本机登录验证码')
        label=ttk.Label(win,padding=20)
        label.pack()
        def tick():
            now=int(time.time())
            label.configure(text=otp(secret,now//CODE_PERIOD)+'    '+str(CODE_PERIOD-now%CODE_PERIOD)+' 秒')
            win.after(1000,tick)
        tick()
    ttk.Button(box,text='绑定手机验证器',command=pairing).pack(fill='x',pady=4)
    ttk.Button(box,text='查看本机当前验证码',command=show_code).pack(fill='x')
    ttk.Label(box,text='已记住的浏览器').pack(anchor='w',pady=(14,2))
    listing=tk.Listbox(box,width=58,height=5)
    listing.pack(fill='both')
    ids=[]
    def refresh():
        ids.clear()
        listing.delete(0,'end')
        with closing(connect()) as conn:
            for digest,label,created,expires in conn.execute('SELECT digest,label,created,expires FROM devices WHERE owner=? AND expires>? ORDER BY created DESC',(account['verifier'],int(time.time()))):
                ids.append(digest)
                started=datetime.fromtimestamp(created).strftime('%m-%d %H:%M')
                ends=datetime.fromtimestamp(expires).strftime('%Y-%m-%d')
                listing.insert('end',f'{label}   {started} 添加   {ends} 到期')
    def revoke():
        sel=listing.curselection()
        if sel and messagebox.askyesno('撤销设备','撤销后，此浏览器的登录立即失效。继续吗？',parent=root):
            with closing(connect()) as conn, conn:
                conn.execute('DELETE FROM devices WHERE digest=?',(ids[sel[0]],))
            refresh()
    def reset():
        if messagebox.askyesno('更换验证器密钥','所有已记住的设备和当前登录都会失效。需要用新密钥重新绑定验证器。继续吗？',parent=root):
            with closing(connect()) as conn, conn:
                new_factor(conn)
            refresh()
            pairing()
    tools=ttk.Frame(box)
    tools.pack(fill='x',pady=6)
    for title,cmd in [('刷新',refresh),('撤销选中设备',revoke),('更换验证器密钥',reset)]:
        ttk.Button(tools,text=title,command=cmd).pack(side='left',padx=2)
    refresh()
    root.mainloop()


if __name__=='__main__':
    if sys.argv[1:]==['--initialize']:
        initialize()
    else:
        manage()
