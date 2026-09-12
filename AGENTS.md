# ComfyUI-Ariadne Agent 说明

接手本仓库前先读：`LOCAL_MAINTENANCE.md`（远端/联接部署/测试/边界）与 `D:\GitHub\ComfyUI\本地开发手册\避坑经验.md`。

- 契约层源码在 `ariadne_core/`（纯 Python 可独立测试），移植自无限画布插件——改编译行为必须同步跑 `tests/`（41 项含实测计费回归用例）。
- 密钥永远不进 Git；付费生成由用户亲自触发，Agent 只做离线/免费验证。
- ComfyUI 自定义节点开发规则（双序列化、绝对导入、configureGraph 守卫等）见避坑手册，违反任意一条都会产生难查的隐性 bug。
