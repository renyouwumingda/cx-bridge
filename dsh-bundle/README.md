# dsh-cx-bridge

DSH bundle：把本地 `cx-bridge` MCP 服务（stdio）接进 Harness，提供 4 个工具：

- `cx_status` 看当前待作答题数
- `cx_take_questions` 取走题目
- `cx_submit_answers` 交回答案（合并写入）
- `cx_report` 页面结构诊断

## 安装

用 `plugin_manager` 的 `install_bundle` 安装本目录，不要手写 profile：

```
plugin_manager(action: "install_bundle", target: "<本目录绝对路径>")
```

装完在「已安装的插件」里能看到，可开关。

## 换机器

`cordis.patch.yml` 里两处绝对路径要改成实际位置：`command`（node 可执行文件）与 `args[0]`（`cx-mcp.js` 绝对路径）。

MCP 服务本身要求本机 8790 上的桥接服务在跑（`server.py`），否则工具会报连不上。
