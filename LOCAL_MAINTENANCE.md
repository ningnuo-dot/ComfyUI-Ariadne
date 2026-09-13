# ComfyUI-Ariadne 本地维护说明

2026-09-12 建仓。Ariadne 视频家族 ComfyUI 节点包；独立新仓（非 fork），无上游同步需求。

## 远端

- `origin` = `https://github.com/ningnuo-dot/ComfyUI-Ariadne`（用户 fork 账号下）；本地 master 直接开发，小步提交、中文提交说明，默认不 force push。
- 无 upstream（不是别人的项目的克隆）。

## 运行形态

- 开发源码 = 本目录（`D:\GitHub\ComfyUI-Ariadne`）。
- 运行副本 = **目录联接** `D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne` → 本目录（同 CYBERPUNK-STYLE-DIY 模式：改 JS 刷新页面即生效，改 Python 需重启 ComfyUI；勿把联接当独立目录提交/删除）。
- 卸载 = 删除联接目录即可，本仓库不动。
- 端口 8188（共用 ComfyUI 主安装）；冒烟测试用候选端口 8191 起第二实例，不在运行中实例上验证。

## 密钥与数据边界

- `config.local.json`（本目录，gitignore）：方舟 Key / Kie Key / TOS AK·SK·桶 / 优化器配置。不进 Git、不进日志。
- 环境变量回退：`ARK_API_KEY` / `KIE_API_KEY`。
- 生成素材落 ComfyUI `input/ariadne/`，成片落 `output/ariadne/`——都属 ComfyUI 运行数据，不在本仓库。

## 测试与验收

- 离线单测：`D:\GitHub\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s tests`（83 项，全 mock 不付费）。
- 前端契约单测：`node --test tests/js/ariadne_frontend.test.mjs`（24 项：适配器/优化客户端/胶囊引用切分/画幅锁定/批量展开）。
- 优化器流式链路（零付费）：先起 `python tests/mock_optimizer_server.py 8192`，再经 `/ariadne/config` 临时写入 mock base_url/model/key，POST `/ariadne/optimize` 验 SSE；用后恢复配置（api_key 仅在等于 mock 值时清除）。
- 加载冒烟：候选端口起第二实例 → `/object_info` 查 Ariadne 节点 + `/extensions` 查 ariadne_*.js（5 个模块）。
- 真实付费生成（方舟/Kie 扣费）只能由用户亲自触发；Agent 不得自行 Queue 生成类工作流。
- 前端已知坑：IAB/某些浏览器对 `/extensions/*.js` 的启发式缓存可能吃掉热更新——真实验收须开新标签页或 Ctrl+F5。

## 回退

- 删联接目录即完全卸载；ComfyUI 主体零改动，无回滚需求。
- 版本回退：`git checkout <提交> -- .` 后重启 ComfyUI。

## 已知坑（继承避坑手册）

- `widgets_values` 双序列化必须同时写 named 字段（前端 installCompactSerialization 已处理，改前端勿删）。
- 节点模块一律绝对导入（ComfyUI spec_from_file_location 加载，相对导入失效）。
- `nodeCreated` 有 `app.configuringGraph` 守卫；DOM widget 宽度在 onResize 同步。
- Kie 上传文件名必须带随机后缀（同毫秒撞名 → 按名去重 → 多图坍缩）。
- 换 H3/Krea 生图任务前 `POST /free` 清显存与本包无关（本包走云端 API 不占显存）。
