# Alibaba Cloud Linux 3 小白一键安装文档与脚本

## 摘要

新增面向零基础用户的 Alibaba Cloud Linux 3 部署文档，并提供可直接执行的一键安装脚本。目标是在阿里云 ECS 上自动安装系统依赖、创建 Python 虚拟环境、安装项目依赖、生成 systemd 服务并启动 Streamlit Web 页面。

## 新增文件

- `tocodex-docs/2026-05-13_AlibabaCloudLinux3小白一键安装文档.md`
  - 面向小白用户，按阿里云安全组、远程登录、一键安装、服务管理、模型配置、常见问题排查组织。
  - 提供公网访问地址、端口放行、日志查看、更新和卸载说明。

- `libriscribe/scripts/install_alibaba_linux3.sh`
  - Alibaba Cloud Linux 3 一键安装脚本。
  - 支持环境变量：
    - `APP_DIR`：安装目录，默认 `/opt/libriscribe`。
    - `APP_PORT`：Web 端口，默认 `8501`。
    - `REPO_URL`：代码仓库地址，默认官方仓库。
    - `PIP_INDEX_URL`：pip 镜像源，默认清华源。
  - 自动创建 `/etc/systemd/system/libriscribe.service`。
  - 自动生成 `/opt/libriscribe/start_libriscribe.sh`。

## 备注

当前开发环境是 Windows，因此未直接执行 Linux 安装脚本。已进行文件存在性与关键内容静态检查，并修正脚本依赖列表，补充安装 `curl`。
