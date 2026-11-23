"""Single owner account for the public training journal. Configuration is local only."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path


def account_file():
    return Path(os.environ['LOCALAPPDATA']) / 'RunningCoach' / 'web-account.json'


def read_account():
    try:
        with account_file().open(encoding='utf8') as source:
            item = json.load(source)
        if (item['format'] == 1 and len(bytes.fromhex(item['salt'])) == 16
                and len(bytes.fromhex(item['verifier'])) == 32 and isinstance(item['username'], str)):
            return item
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


def derive(password, salt):
    return hashlib.scrypt(password.encode('utf8'), salt=salt, n=32768, r=8, p=1,
                          maxmem=64*1024*1024, dklen=32)


def verify(item, username, password):
    if not item or len(password) > 256 or len(username) > 80:
        return False
    digest = derive(password, bytes.fromhex(item['salt']))
    user_ok = hmac.compare_digest(item['username'].encode('utf8'), username.strip().encode('utf8'))
    return hmac.compare_digest(bytes.fromhex(item['verifier']), digest) and user_ok


def save_account(username, password):
    username = username.strip()
    if not 1 <= len(username) <= 80 or not username.isprintable():
        raise ValueError('用户名请填 1–80 个可显示字符。')
    if not 12 <= len(password) <= 256 or not password.strip():
        raise ValueError('密码请使用 12–256 个字符。')
    salt = secrets.token_bytes(16)
    item = dict(format=1, username=username, salt=salt.hex(), verifier=derive(password, salt).hex())
    dest = account_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=dest.parent, delete=False) as out:
        temp = Path(out.name)
        json.dump(item, out, ensure_ascii=False)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def setup():
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.title('训练手记 · 本机账号设置')
    box = ttk.Frame(root, padding=20)
    box.pack(fill='both', expand=True)
    prior = read_account()
    fields = []
    for title in ('用户名', '新密码（至少 12 个字符）', '确认密码'):
        ttk.Label(box, text=title).pack(anchor='w')
        entry = ttk.Entry(box, width=36, show='*' if fields else '')
        entry.pack(fill='x', pady=(3, 10))
        fields.append(entry)
    if prior:
        fields[0].insert(0, prior['username'])
    def apply():
        if fields[1].get() != fields[2].get():
            messagebox.showerror('设置账号', '两次输入的密码不一致。', parent=root)
            return
        if prior and not messagebox.askyesno('更新账号', '保存后，已登录的设备需要重新登录。继续吗？', parent=root):
            return
        try:
            save_account(fields[0].get(), fields[1].get())
        except (OSError, ValueError) as exc:
            messagebox.showerror('设置账号', str(exc), parent=root)
            return
        messagebox.showinfo('训练手记', '账号已保存，可用它登录电脑和手机。', parent=root)
        root.destroy()
    ttk.Button(box, text='保存账号', command=apply).pack(fill='x')
    root.bind('<Return>', lambda event: apply())
    fields[1 if prior else 0].focus_set()
    root.mainloop()


if __name__ == '__main__':
    setup()
