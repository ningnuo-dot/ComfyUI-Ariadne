# ComfyUI-Ariadne

Ariadne 视频家族的 ComfyUI 自定义节点包——把无限画布（Daedalus Canvas）里久经实测的 Ariadne 生成线搬进 ComfyUI，不动 ComfyUI 主体。**本地学习使用。**

## 节点家族

| 节点 | 渠道 | 模式 |
| --- | --- | --- |
| Ariadne · Seedance 2.5 视频生成 | 火山方舟直连（主）/ Kie（副） | 全能参考 / 文生 / 首帧 / 首尾帧 / 视频编辑 / 视频延长 |
| Ariadne · Seedance 2.5 视频生成（自由引用） | 同上 | 全能参考 / 文生 / 多模态参考；图像1–3 自由输入，身份/职责由提示词手工指定 |
| Ariadne · Veo 3.1 视频生成 | Kie | 文生 / 首尾帧 / 全能参考 / 延长 |
| Ariadne · 可灵 Kling 3.0 视频生成 | Kie | 文生 / 首帧 / 首尾帧 / 全能参考（@元素名）/ 多镜头 |
| Ariadne · Kie 图生图 | Kie | nano-banana-pro（默认）/ seedream-5-pro / grok-imagine-2 / gpt-image-2 / nano-banana-2 |
| Ariadne · Omni 1.1 参考素材视频 | Kie | 人物/场景/动作/固定角色四路输入（固定角色ID 可连 ComfyUI-Kie 的角色节点） |
| Ariadne · Omni 1.1 首尾帧过渡 | Kie | 首帧必填、尾帧可选 |
| Ariadne · 一瞬入画 | Kie | 视频/多图 → 高保真场景图（gpt-image-2，自动抽帧 + 保真提示词模板） |
| Ariadne · Topaz 视频超分 | Kie | topaz/video-upscale：1× 修复增强 / 2× / 4× 放大，nsfw_checker 可关（官方限 MP4/MOV/MKV ≤50MB） |

## 创作台（v0.3.0 核心）

Seedance 两个版本双击打开**底部创作台**，面板作为 DOM widget 长在节点下方、跟随节点移动缩放，三页协作：

- **创作**：模式页签（不满足条件自动禁用并给原因）＋素材条＋行内胶囊提示词＋单行底栏（参数摘要 / ✧ 一键优化 / 状态历史 / 价格与生成）。
- **提示词工作台**：五段式输入 → OpenAI 兼容优化器流式改写（sd25-pe 技能，Key 只在服务端）→ 确认应用；带历史与过期草稿保护。
- **输出参数**：分辨率 / 画幅（锁定模式自动写自适应）/ 时长 / 渠道 / 格式 / 保存文件夹 / 打开素材文件夹。

行为要点：

- **素材条**：画布连线即接入，瓦片（上传/裁剪产物）在前、连线素材接着编号；**批量图像按上游叶子图展开**——3 张图的批次出 3 个瓦片、各自回源预览，编号与提交时 Python 的展开顺序一致。
- **@引用契约**：`@图片N` 等面板标签提交时自动编译为官方 `@图像N`（方舟）/ `@ImageN`（Kie），并按素材角色追加职责句；自由引用版不预置角色，职责完全由提示词手工指定。
- **生成只跑本节点**：面板生成按钮按节点部分执行（含上游依赖），工作流里其他节点不运行不计费；确认弹窗后才提交。
- **成片持久化**：结果 URL 是时效地址（方舟 24h），成片强制下载落盘后经 VIDEO 输出交付；未接保存节点时自动落 `output/ariadne/` 兜底，新建节点也会自动补一个 SaveVideo。
- **规格预检**：参考视频像素 ≥407696 官方拦截线本地预检；真人素材方舟隐私拦截定向中文翻译；Kie input 字段白名单防 500；编辑/延长模式画幅自动锁定自适应。

## 为什么不是重复造轮子（2026-09-12 全网调研结论）

- ComfyUI 核心（comfy_api_nodes）已有 Kling / Gemini Video Omni / Seedance 2.5 的 partner 节点，但**全部走 api.comfy.org 积分代理，不支持自有 Key 直连**。
- 本包的差异化 = **火山方舟自有账户直连**（`doubao-seedance-2-5-260628`，content/role 官方契约）+ TOS 私有桶预签名上传 + Ariadne `@引用` 提示词契约（素材职责句）+ 参考视频截断省钱 + 节点内素材瓦片/胶囊提示词。
- **Omni 不在本包**：官方 Interactions API 已有两条现成路线——核心 `GeminiVideoOmniV2` 节点与本机 `ComfyUI-Kie` 包 `KieOmniVideo`，不重复实现。
- 第三方轮子参考：[ComfyUI-JM-Volcengine-API](https://github.com/juemingai/ComfyUI-JM-Volcengine-API)（Seedance 2.0 时代，无 2.5 omni_reference 契约）、[KlingAIResearch/ComfyUI-KLingAI-API](https://github.com/KlingAIResearch/ComfyUI-KLingAI-API)（官方渠道）、[GoogleCloudPlatform/comfyui-google-genmedia-custom-nodes](https://github.com/GoogleCloudPlatform/comfyui-google-genmedia-custom-nodes)（Vertex 路线）。契约层均以自家画布插件（2026-09 实测口径，含 306 积分计费精确复现）为准移植。

## 安装

```bat
:: 方式一（本机开发推荐）：目录联接，改代码刷新即生效（Python 节点需重启）
mklink /J "D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne" "D:\GitHub\ComfyUI-Ariadne"

:: 方式二：直接克隆/复制到 custom_nodes
git clone https://github.com/ningnuo-dot/ComfyUI-Ariadne "D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne"
```

依赖：仅 ComfyUI 自带环境（requests / PyAV / PIL / aiohttp）+ 系统 PATH 上的 **ffmpeg**（裁剪用）。

## 配置

侧边栏「**Ariadne 设置**」填写（存 `config.local.json`，已 gitignore；也可用环境变量 `ARK_API_KEY` / `KIE_API_KEY`）：

- **火山方舟 Key**（ark.cn-beijing.volces.com，Seedance 方舟渠道）
- **Kie Key**（api.kie.ai，Veo/可灵/图生图/Seedance Kie 渠道）
- **对象存储 TOS**（方舟渠道参考视频必需：视频仅收公网 URL，私有桶经预签名 URL 交付；AK/SK 在 TOS 控制台，配置后点「TOS 试传验证」）
- **提示词优化器**（OpenAI 兼容站点/模型/Key，可选；模型列表可一键拉取）

## 测试（不付费）

```bash
D:\GitHub\ComfyUI\.venv\Scripts\python.exe -m unittest discover -s tests   # 76 项：契约编译/校验/估价/优化器/端到端 mock/注册冒烟，全离线
node --test tests/js/ariadne_frontend.test.mjs                             # 24 项：适配器/优化客户端/画幅锁定/批量展开契约
python tests/mock_optimizer_server.py 8192                                 # 本地 mock 优化器（验证流式/回落/中断）
```

付费生成**必须由用户逐次确认后触发**（Agent 不自行扣费）。

## 边界与待验证

- **更新本包后请 Ctrl+F5 强刷浏览器**（前端模块受浏览器启发式缓存，普通刷新可能拿旧文件）。
- 方舟 `omni_reference_task_type` 显式声明与 data URL 标注帧是否被官方接受：现发送前不下发该字段（与画布版一致）。
- 精准编辑帧标注 UI（画布版 ✦ 标注工具）尚未移植，契约层已支持（`role=annotation` + 时间戳编译）。
- 可灵元素/多镜头 v0.1 用 JSON widget 传参，前端编辑器待补。
- 实测边界以画布版档案为准：`D:\GitHub\ariadne\docs\video-tests\seedance-*`。

## 维护

- 开发目录 = 本仓库；运行副本走目录联接（`D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne`），改 Python 重启 ComfyUI、改 JS 刷新页面即生效。
- 官方手册原文存档与避坑清单：`D:\GitHub\ComfyUI\本地开发手册\`。
- 详见 [LOCAL_MAINTENANCE.md](LOCAL_MAINTENANCE.md) 与 [CHANGELOG.md](CHANGELOG.md)。
