# 跑步教练

此仓库保存佳明同步程序、训练档案服务、手机界面和离线发布工具。个人训练库及其备份单独保存在本机。首次检出后可以创建空库验证程序。

## 在 Windows 上启动

使用 Python 3.12 或更高版本，在仓库根目录打开两个 PowerShell 窗口。首次使用先执行以下命令创建空库。已有个人数据库时直接启动服务。

```powershell
python outputs/local_archive/init_archive.py
```

第一个窗口启动桌面端，在浏览器打开 http://127.0.0.1:8765 。

```powershell
python outputs/local_archive/server.py
```

第二个窗口启动手机服务，在同一台电脑打开 http://localhost:8876 。在项目电脑上双击根目录的「设置公网登录账号.cmd」，创建或重设唯一的用户名和密码。账号可在电脑和手机使用，密码验证信息仅存于当前 Windows 用户的本地应用数据目录。重设后旧会话失效。

```powershell
python outputs/local_archive/mobile_server.py
```

电脑和手机共用公网入口，登录后可用 /desktop 和 /mobile 选择视图。部署时将已有 HTTPS 反向代理指向电脑上的 127.0.0.1:8876，并在未纳入 Git 的 `outputs/local_archive/archive.local.json` 中设置 `mobile_origin` 为手机浏览器使用的完整来源（包含非默认端口）。服务重启后读取该地址。桌面服务含数据库下载接口，应通过本机或受保护的私人网络访问。

首次公网登录前，在项目电脑双击「登录验证器与常用设备.cmd」，绑定手机验证器或在本机查看当前验证码。新浏览器通过密码和动态验证码后，可选择记住 90 天。普通退出保留该浏览器的信任；在本机工具撤销设备会使对应登录失效。更改密码或更换验证器密钥会使旧会话和旧设备信任失效。验证器密钥由 Windows 当前用户的 DPAPI 保护，设备凭据仅在服务端保存摘要，两者位于项目外。

## 数据与恢复

- 空库使用 schema.sql 中的表结构。迁移已有记录时，关闭写入服务后，从自己的本地备份恢复 `outputs/训练日志.sqlite3` 及需要的来源材料。
- 桌面服务在本机已有 `outputs/local_archive/index.html` 时沿用个人完整模板。新检出默认使用 `archive.html` 的跑步档案视图。个人模板、知识库案例、路线图片、配置和口令需按原位置在本地单独保管。
- 运行 `python outputs/local_archive/export_page.py`，可在 outputs 目录生成网页快照、数据 JSON、完整与轻量 HTML/ZIP。
- 手机服务的训练周期和已核对阈值活动来自数据库。实跑推定区间可从 metadata 的 `archive_field_threshold` 读取，需要包含 session_id、date、low、high，其中配速使用秒/公里。
- 日常只提交 .gitignore 中明确列出的程序文件。GitHub 仓库不含训练记录。

- 专项卡片使用本地目标评估中的可选字段 `focus_topics`。每项包含 `key`、`title`、`date`，可另设 `intro`、`end_date` 和复核节点 `nodes`。
- 食衡是独立应用。仓库包含手机服务调用的 Python 接口，食衡的前端、商品库和模型由本机另行配置。

## 佳明同步

在 Windows 项目环境中安装 `python -m pip install -r requirements.txt`。已有安装可复用该 Windows 用户授权的佳明凭据。运行 `python outputs/garmin_sync/garmin_sync.py --help` 查看批次参数。新环境需要先在本机配置登录，实际同步前核对日期、范围与已有批次。
