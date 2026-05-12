# LibriScribe 小白安装文档（Alibaba Cloud Linux 3 一键版）

> 适合完全没有 Linux 基础的用户。目标是在阿里云 ECS 上一键安装并启动 LibriScribe 网页写书系统。
>
> 系统：Alibaba Cloud Linux 3
>
> 推荐服务器：2 核 4G 起步，最好 4 核 8G；系统盘建议 40G 以上。
>
> 最终访问地址：`http://你的服务器公网IP:8501`

---

## 0. 你最终会得到什么

安装完成后，服务器会自动运行 LibriScribe Web 页面。你可以在浏览器打开：

```text
http://你的服务器公网IP:8501
```

可以完成：

1. 创建写书项目。
2. 配置 AI 模型 API。
3. 上传资料。
4. 生成大纲。
5. 生成章节正文。
6. 生成前言、结语、参考文献。
7. 导出 Word、PDF、PPTX 等文件。

---

## 1. 阿里云控制台先做 1 件事：放行端口

如果不放行端口，程序即使启动成功，浏览器也打不开。

### 1.1 进入安全组

1. 登录阿里云控制台。
2. 进入 `ECS 云服务器`。
3. 找到你的服务器实例。
4. 点击服务器绑定的 `安全组`。
5. 点击 `入方向` 或 `入方向规则`。
6. 添加规则。

### 1.2 添加 8501 端口规则

规则填写：

| 项目 | 填写 |
|---|---|
| 协议类型 | TCP |
| 端口范围 | `8501/8501` |
| 授权对象 | `0.0.0.0/0` |
| 描述 | `LibriScribe Web` |

> `0.0.0.0/0` 表示公网可访问。正式长期使用时，建议改成你自己的固定 IP，更安全。

---

## 2. 登录服务器

### 2.1 使用阿里云网页终端登录（最简单）

1. 打开阿里云 ECS 实例列表。
2. 找到服务器。
3. 点击 `远程连接`。
4. 选择 `Workbench` 或 `VNC`。
5. 登录后看到黑色命令行窗口即可。

### 2.2 确认是 root 用户

在服务器命令行输入：

```bash
whoami
```

如果返回：

```text
root
```

说明可以直接安装。

如果不是 root，后面的命令前面需要加 `sudo`。

---

## 3. 最推荐：复制一条命令一键安装

> 下面命令适合你已经把本项目代码上传/克隆到服务器，或者使用默认 GitHub 仓库地址下载。

在服务器命令行中复制执行：

```bash
curl -fsSL https://raw.githubusercontent.com/guerra2fernando/libriscribe/main/scripts/install_alibaba_linux3.sh -o /tmp/install_libriscribe.sh && bash /tmp/install_libriscribe.sh
```

如果你使用的是当前二次开发版本、私有仓库或国内镜像，把仓库地址替换成你自己的：

```bash
REPO_URL="https://你的仓库地址/libriscribe.git" bash /tmp/install_libriscribe.sh
```

如果服务器不能访问 GitHub，可以先把项目压缩包上传到服务器，然后使用本文第 4 节“本地脚本安装”。

---

## 4. 本地脚本安装（适合已有项目目录）

如果你已经把项目放在服务器某个目录，例如：

```text
/root/libriscribe
```

进入项目目录：

```bash
cd /root/libriscribe
```

执行项目内一键安装脚本：

```bash
bash scripts/install_alibaba_linux3.sh
```

如果希望安装到指定目录，例如 `/opt/libriscribe`：

```bash
APP_DIR=/opt/libriscribe bash scripts/install_alibaba_linux3.sh
```

如果希望换端口，例如 `8600`：

```bash
APP_PORT=8600 bash scripts/install_alibaba_linux3.sh
```

> 换端口后，阿里云安全组也要放行对应端口。

---

## 5. 一键脚本会自动做什么

脚本文件：[`install_alibaba_linux3.sh`](../libriscribe/scripts/install_alibaba_linux3.sh)

它会自动完成：

1. 安装系统依赖：`python3`、`pip`、`git`、编译工具等。
2. 安装文档解析常用工具：`poppler-utils`、`tesseract` 等。
3. 下载或更新项目代码。
4. 创建 Python 虚拟环境 `.venv`。
5. 安装 `requirements.txt` 中的项目依赖。
6. 生成一键启动脚本：`/opt/libriscribe/start_libriscribe.sh`。
7. 创建系统服务：`libriscribe.service`。
8. 尝试开放服务器本机防火墙 `8501` 端口。
9. 启动 Web 服务。

---

## 6. 安装成功后怎么看地址

安装成功后，命令行会显示类似：

```text
访问地址（二选一）：
  内网地址：http://172.xx.xx.xx:8501
  公网地址：http://你的公网IP:8501
```

你通常应该打开：

```text
http://你的公网IP:8501
```

例如：

```text
http://8.142.xxx.xxx:8501
```

---

## 7. 常用管理命令

### 7.1 查看服务是否正在运行

```bash
systemctl status libriscribe --no-pager
```

如果看到：

```text
active (running)
```

说明正在运行。

### 7.2 查看实时日志

```bash
journalctl -u libriscribe -f
```

按 `Ctrl + C` 可以退出日志查看。

### 7.3 重启服务

```bash
systemctl restart libriscribe
```

### 7.4 停止服务

```bash
systemctl stop libriscribe
```

### 7.5 再次启动服务

```bash
systemctl start libriscribe
```

### 7.6 手动启动

如果 systemd 服务异常，可以手动启动：

```bash
/opt/libriscribe/start_libriscribe.sh
```

---

## 8. 第一次打开网页后怎么配置模型

进入网页后：

1. 打开左侧 `模型设置`。
2. 新增或选择模型档案。
3. 填写：
   - `API Base`
   - `API Key`
   - `模型名称`
4. 点击测试连接。
5. 看到正常回复后再生成大纲或正文。

### 8.1 自定义 OpenAI 兼容平台怎么填

常见格式：

```text
API Base: https://你的中转域名/v1
API Key: sk-xxxxxxxx
模型名称: gpt-4o / deepseek-chat / 你的模型名
```

注意：

- `API Base` 通常要以 `/v1` 结尾。
- 不要填写控制台网页地址。
- 不要填写模型列表页面地址。
- 如果测试只返回 `assistant`，说明接口没有返回真实正文，需要检查模型名或中转兼容性。

---

## 9. 防火墙和安全组排查

如果服务显示运行，但浏览器打不开：

### 9.1 检查服务监听端口

```bash
ss -lntp | grep 8501
```

正常会看到类似：

```text
LISTEN 0  ... 0.0.0.0:8501 ... python
```

### 9.2 检查服务器本机防火墙

```bash
firewall-cmd --list-ports
```

如果没有 `8501/tcp`，执行：

```bash
firewall-cmd --permanent --add-port=8501/tcp
firewall-cmd --reload
```

### 9.3 检查阿里云安全组

确认入方向已经放行：

```text
TCP 8501/8501 0.0.0.0/0
```

---

## 10. 更新项目代码

如果以后代码更新了，执行：

```bash
cd /opt/libriscribe
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
systemctl restart libriscribe
```

---

## 11. 卸载

如果要删除服务：

```bash
systemctl stop libriscribe
systemctl disable libriscribe
rm -f /etc/systemd/system/libriscribe.service
systemctl daemon-reload
rm -rf /opt/libriscribe
```

如果要关闭防火墙端口：

```bash
firewall-cmd --permanent --remove-port=8501/tcp
firewall-cmd --reload
```

---

## 12. 常见问题

### Q1：执行安装命令提示 `curl: command not found`

先安装 curl：

```bash
dnf install -y curl
```

再执行一键安装命令。

### Q2：提示 `git clone` 失败

可能是服务器访问 GitHub 慢或失败。解决办法：

1. 使用国内 Git 镜像。
2. 把项目 zip 上传到服务器。
3. 设置 `REPO_URL` 为你自己的仓库地址。

示例：

```bash
REPO_URL="https://你的仓库地址/libriscribe.git" bash /tmp/install_libriscribe.sh
```

### Q3：依赖安装很慢

脚本默认使用清华 PyPI 源：

```text
https://pypi.tuna.tsinghua.edu.cn/simple
```

如果你想换源：

```bash
PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple" bash scripts/install_alibaba_linux3.sh
```

### Q4：页面打开了，但生成正文失败

优先检查：

1. 模型 API Key 是否有效。
2. API Base 是否正确。
3. 模型名称是否真实存在。
4. 账户余额是否充足。
5. 模型是否支持较长输出。

查看日志：

```bash
journalctl -u libriscribe -f
```

### Q5：测试模型只返回 `assistant`

这不是正常模型回复，通常是 OpenAI-compatible 中转配置错误：

1. `API Base` 填错，没填到 `/v1`。
2. 模型名称不对。
3. 中转平台没有完整兼容 `/chat/completions`。
4. 平台把 role 字段错误返回成了 content。

修复后重新在网页 `模型设置` 中测试连接。

### Q6：服务器重启后网页还会自动运行吗

会。脚本已经创建 systemd 服务，并执行：

```bash
systemctl enable libriscribe
```

服务器重启后会自动启动。

---

## 13. 最短使用流程

安装完成后：

1. 浏览器打开 `http://服务器公网IP:8501`。
2. 进入 `模型设置`，配置 AI 模型。
3. 回到 `项目`，创建新项目。
4. 进入 `资料与检索`，上传资料。
5. 进入 `大纲与结构`，生成或粘贴大纲。
6. 进入 `正文编辑`，生成章节。
7. 进入 `审校与交付` / `导出`，导出 Word 或 PDF。

---

## 14. 小白只需要记住的 5 条命令

```bash
# 查看服务状态
systemctl status libriscribe --no-pager

# 看运行日志
journalctl -u libriscribe -f

# 重启网页服务
systemctl restart libriscribe

# 进入项目目录
cd /opt/libriscribe

# 手动启动网页
/opt/libriscribe/start_libriscribe.sh
```
