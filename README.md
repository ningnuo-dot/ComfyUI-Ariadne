# ComfyUI-Ariadne

Ariadne 视频家族的 ComfyUI 自定义节点包——把无限画布（Daedalus Canvas）里久经实测的 Ariadne 生成线搬进 ComfyUI，不动 ComfyUI 主体。**本地学习使用。**

| 节点 | 渠道 | 模式 |
| --- | --- | --- |
| Ariadne · Seedance 2.5 视频生成 | 火山方舟直连（主）/ Kie（副） | 全能参考 / 文生 / 首帧 / 首尾帧 / 视频编辑 / 视频延长 |
| Ariadne · Veo 3.1 视频生成 | Kie | 文生 / 首尾帧 / 全能参考 / 延长 |
| Ariadne · 可灵 Kling 3.0 视频生成 | Kie | 文生 / 首帧 / 首尾帧 / 全能参考（@元素名）/ 多镜头 |
| Ariadne · Kie 图生图 | Kie | nano-banana-pro（默认）/ seedream-5-pro / grok-imagine-2 / gpt-image-2 / nano-banana-2 |

## 为什么不是重复造轮子（2026-09-12 全网调研结论）

- ComfyUI 核心（comfy_api_nodes）已有 Kling / Gemini Video Omni / Seedance 2.5 的 partner 节点，但**全部走 api.comfy.org 积分代理，不支持自有 Key 直连**。
- 本包的差异化 = **火山方舟自有账户直连**（`doubao-seedance-2-5-260628`，content/role 官方契约）+ TOS 私有桶预签名上传 + Ariadne `@引用` 提示词契约（素材职责句）+ 参考视频截断省钱 + 节点内素材瓦片/胶囊提示词。
- **Omni 不在本包**：官方 Interactions API 已有两条现成路线——核心 `GeminiVideoOmniV2` 节点与本机 `ComfyUI-Kie` 包 `KieOmniVideo`，不重复实现。
- 第三方轮子参考：[ComfyUI-JM-Volcengine-API](https://github.com/juemingai/ComfyUI-JM-Volcengine-API)（Seedance 2.0 时代，无 2.5 omni_reference 契约）、[KlingAIResearch/ComfyUI-KLingAI-API](https://github.com/KlingAIResearch/ComfyUI-KLingAI-API)（官方渠道）、[GoogleCloudPlatform/comfyui-google-genmedia-custom-nodes](https://github.com/GoogleCloudPlatform/comfyui-google-genmedia-custom-nodes)（Vertex 路线）。契约层均以自家画布插件（2026-09 实测口径，含 306 积分计费精确复现）为准移植。

## 特色（自无限画布版完整继承）

- **@胶囊提示词**：节点内提示词编辑器，`@` 唤出素材选单，提交时自动编译为官方 `@图像N`（方舟）/ `@ImageN`（Kie），并追加素材职责句（人物/服装/场景/动作/音频各司其职）。
- **素材瓦片**：节点内「＋素材」上传图/视频/音频（落 `input/ariadne/`），每个瓦片可切职责角色；插座输入（IMAGE/VIDEO/AUDIO）自动追加编号。
- **节点内裁剪（省钱）**：视频瓦片 `✂` 打开卡尺浮层——对齐输出 / 分镜均摊（ffmpeg 场景切点检测 + 水位法摊保留）/ 手动区间三模式；两渠道均按（输入+输出）时长计费，截断即省真金。
- **规格预检**：参考视频像素 ≥407696 官方拦截线本地预检；真人素材方舟隐私拦截的定向中文翻译；Kie input 字段白名单防 500。
- **费用预估**：方舟刊例价（含 1080p 限时折扣）与 Kie 积分价双口径，仅展示不扣费。
- **成片持久化**：结果 URL 是时效地址（方舟 24h），成片强制下载落 `output/ariadne/Seedance版_<taskId>.mp4` 后经 VIDEO 输出接 SaveVideo。

## 安装

```bat
:: 方式一（本机开发推荐）：目录联接，改代码刷新即生效（Python 节点需重启）
mklink /J "D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne" "D:\GitHub\ComfyUI-Ariadne"

:: 方式二：直接克隆/复制到 custom_nodes
git clone https://github.com/ningnuo-dot/ComfyUI-Ariadne "D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne"
```

依赖：仅 ComfyUI 自带环境（requests / PyAV / PIL / aiohttp）+ 系统 PATH 上的 **ffmpeg**（裁剪用）。

## 配置

侧边栏「Ariadne 工作台」填写（存 `config.local.json`，已 gitignore；也可用环境变量 `ARK_API_KEY` / `KIE_API_KEY`）：

- **火山方舟 Key**（ark.cn-beijing.volces.com，Seedance 方舟渠道）
- **Kie Key**（api.kie.ai，Veo/可灵/图生图/Seedance Kie 渠道）
- **对象存储 TOS**（方舟渠道参考视频必需：视频仅收公网 URL，私有桶经预签名 URL 交付；AK/SK 在 TOS 控制台，配置后点「TOS 试传验证」）
- **提示词优化器**（OpenAI 兼容站点/模型/Key，可选）

## 测试（不付费）

```bash
.venv 依赖齐备后：
python -m unittest discover -s tests -v   # 41 项：契约编译/校验/估价/TOS 签名/错误翻译/注册冒烟，全离线
```

付费生成**必须由用户亲自 Queue 触发**（Agent 不自行扣费）。

## 边界与待验证

- 方舟 `omni_reference_task_type` 显式声明与 data URL 标注帧是否被官方接受：待 1 次授权付费实测（现发送前不下发该字段，与画布版一致）。
- 精准编辑帧标注 UI（画布版 ✦ 标注工具）尚未移植，契约层已支持（`role=annotation` + 时间戳编译）。
- 可灵元素/多镜头 v0.1 用 JSON widget 传参，前端编辑器待补。
- 实测边界以画布版档案为准：`D:\GitHub\ariadne\docs\video-tests\seedance-*`。

## 维护

- 开发目录 = 本仓库；运行副本走目录联接（`D:\GitHub\ComfyUI\custom_nodes\ComfyUI-Ariadne`），改 Python 重启 ComfyUI、改 JS 刷新页面即生效。
- 官方手册原文存档与避坑清单：`D:\GitHub\ComfyUI\本地开发手册\`。
- 详见 [LOCAL_MAINTENANCE.md](LOCAL_MAINTENANCE.md) 与 [CHANGELOG.md](CHANGELOG.md)。
