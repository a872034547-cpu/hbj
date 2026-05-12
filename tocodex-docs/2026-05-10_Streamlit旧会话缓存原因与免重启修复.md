# 说明：Streamlit 旧会话缓存导致需要重启的问题

## 原因

这次“重启后就好了”的根因不是模型问题，而是 Streamlit 的运行机制：

- Streamlit 会把页面会话状态保存在 `st.session_state` 中。
- 旧页面中已经创建过一个 `LLMClient` 对象。
- 我修改了 `llm_client.py` 后，Python 进程里的旧对象并不会自动替换成新类逻辑。
- 所以网页还在使用旧的 SDK 调用路径，直到重启进程后才加载新代码。

## 已补的防重启机制

已在 `libriscribe/src/libriscribe/web/app.py` 的 `get_llm_client()` 中加入 `client_code_version` 签名。

以后只要客户端调用逻辑版本升级，签名变化会自动让网页重建 `LLMClient`，不用再手动重启才能生效。

## 验证

已执行：

```cmd
python -m py_compile src\libriscribe\web\app.py src\libriscribe\utils\llm_client.py
```

结果：通过。
