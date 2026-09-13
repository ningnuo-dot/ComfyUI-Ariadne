# 更新记录

## 0.4.0（2026-09-14）

**Ariadne · Topaz 视频超分（Kie）**——无限画布 `ariadne-topaz` 插件移植，为上游视频节点产物做云端放大：

- 新节点 `AriadneTopazUpscale`「Ariadne · Topaz 视频超分（Kie）」：接标准 VIDEO 输入（本包生成节点或 LoadVideo 均可）→ 自动上传 Kie → `topaz/video-upscale` 云端超分 → 成片落 `output/ariadne/Topaz_<taskId>.mp4` 返回 VIDEO。倍数 1×（修复增强，不改尺寸）/ 2×（默认）/ 4×；内容审核 `nsfw_checker` 开关默认开。
- 契约层 `ariadne_core/topaz.py`：字段按官方核对（2026-09-14）——`video_url` + `upscale_factor`（字符串 '1'/'2'/'4'）见 docs.kie.ai OpenAPI；`nsfw_checker`（boolean，默认 true）见官网接入页 kie.ai/topaz-video-upscaler（OpenAPI 页未写全，显式发送保证行为可预期）。上传前本地拦截官方硬限制 MP4/MOV/MKV ≤50MB，早失败不浪费上传。
- 费用预估沿用画布版口径（1×/2× 每秒 8 credits、4× 14，≈¥0.036/credit），并在任务信息中回显 `creditsConsumed` 实耗（`kie.poll_task` 返回补 `creditsConsumed` 字段，向后兼容）。
- 与画布版差异：上传路径沿用本包统一的 `videos/user-uploads`（画布用 `videos/comfyui`，均被 Kie 接受）；无画布侧自动落库/衍生节点逻辑（ComfyUI 由连线与落盘承接）。
- 新增 7 项离线测试（契约纯函数 + poll 实耗透传 + mock 端到端，零付费）；Python 83 项全绿。真实扣费生成待用户亲自触发首验。

## 0.3.0（2026-09-13）

Seedance 2.5 创作台重构（按 `docs/SEEDANCE_WORKBENCH_IMPLEMENTATION_PLAN.md`，API 名与全部输入/输出不变）：

- **紧凑节点**：节点本体只留 7 插座、2 输出、提示词摘要（紧凑态只读、点击直达创作台）、素材摘要行、费用预估、「打开创作台/展开参数」按钮行。低频参数 widget 以 stash 方式从节点物理摘出（实测 `widget.hidden`/`computeSize(0)` 在新前端均不折叠行高），widget 对象保留并记 `__ariadneIndex`；序列化按定义序合并，`widgets_values` 位置顺序与未升级时逐位一致（新前端默认按位恢复）。
- **底部创作台**（`document.body` 级浮层，画布缩放不影响）：与选中 Seedance 节点一一绑定，三页——创作（六模式页签+素材双入口+提示词+@插入+底栏摘要/估价/有声/尾帧/生成确认）、提示词工作台（五段式输入+流式优化+未应用草稿+历史去重 20 条+过期草稿确认保护）、输出参数（分辨率/画幅锁定/时长/渠道/格式/保存目录/高级轮询超时）。
- **流式提示词优化**：`/ariadne/optimize` 升级为 SSE 透传（服务端注入 `resources/sd25-pe.SKILL.md` 原文系统规则，密钥只在服务端；上游非 200 统一报错事件；非流式回落；AbortController 中断保留已生成部分）。新增 `ariadne_core/seedance/optimizer.py` 契约层（五段式输入/聊天体/SSE 半包解析）。
- **前端模块化**：新增 `ariadne_adapter.js`（widget 按名读写/callback 接力/stash 查找/素材聚合/草稿指纹/历史，纯函数可单测）、`ariadne_media.js`（上传/裁剪浮层/瓦片提交共享）、`ariadne_optimizer_client.js`（SSE 客户端）、`ariadne_workbench.js`（创作台）。
- **新增自由引用版节点（09-14 用户要求）**：`AriadneSeedance25Free`「Ariadne · Seedance 2.5 视频生成（自由引用）」——标准版复制的姊妹节点，去掉首帧/尾帧/人物/服装/场景/动作/音频全部预设角色插座，仅 图像1/2/3 三个自由图像输入；role="free" 只编号不加职责句，身份/职责由提示词手工指定。任务类型仅 全能参考/文生视频/多模态参考。创作台面板/胶囊提示词/估价/优化全部复用（模式页签过滤），标准版节点不动；generate 尾部抽取为共享 `_run_generation`。**素材条批量支持**：批量图像（ImageBatch 等）按上游叶子图展开——3 张图的批量出 3 个瓦片、各自回源 LoadImage 预览，编号与 Python 批维展开一致，非加载类上游按 1 张兜底。新增 1 项 Python 端到端 + 2 项前端契约用例（Python 76 / 前端 23 全绿）。
- **修复 Seedance 2.5 对接两处阻断（09-14 付费实测暴露）**：① ENDPOINT 与 ARK_BASE_URL 各含一份 `/api/v3`，拼成 `/api/v3/api/v3/...` 空包 404（任务都建不了），ENDPOINT 改相对路径；② 2.5 返回结构变化：结果视频地址在顶层 `content.video_url`（旧版在 `output.video_url`），旧解析取不到 URL 导致节点空转轮询到 30 分钟超时、成片不落盘——两处都认。另修 test_runtime_offline 端到端用例的 TOS 配置隔离（用户配置真桶后单测会真上传）。
- **修复 Queue 参数整体缺失（09-14 实机首曝）**：新前端 `graphToPrompt` 从活 `node.widgets` 构建 `/prompt` 输入、不走 `onSerialize` 合并，stash 摘出的 10 个参数（prompt/duration/ariadne_assets/task_type/resolution 等）全部缺席，服务端报 `Required input is missing`。修复：包装 `app.graphToPrompt`（queuePrompt 内部为 `this.graphToPrompt` 调用），构建提交体期间临时归还 stash、结束按原折叠态收回；存档双序列化路径不变。**已实机验证生效**：修复后 Queue 校验通过、节点真实执行。
- **画幅锁定自动写自适应（09-14 用户拍板）**：首帧/首尾帧/编辑/延长模式（方舟规格硬性要求 adaptive）进入时自动把画幅改写为自适应并记住原选择（`ariadne.lastAspect` 存 properties 随工作流保存），解锁时还原最近手选——修复「锁定只禁用格子不改值，用户被规格校验卡死还改不了」的缺口。挂三处：模式页签点击、输出参数页渲染（幂等自愈）、节点升级（载入工作流即自愈）；附 3 项 adapter 契约测试（前端契约 21 项全绿）。
- **API 设置统一收敛到侧栏（09-14 迭代）**：侧栏页签更名「Ariadne 设置」，优化器模型框加「拉取」按钮（与创作台原分节同路由）；创作台输出参数页的站点/Key/模型行整体移除，连带清除旧 ⚙ 弹层遗留（状态字段/死函数/失引 CSS）；未配置提示与 config/kie/ark_media/routes 各处报错文案统一改指「Ariadne 设置」（节点 Key 本就统一读 `config.local.json`，无散落输入框）。
- **胶囊引用吞正文修复（09-14 实测反馈）**：优化文案回填后 `@图片1` 连带后续中文整段包进胶囊（「@图片1为准」「@图片1作为首帧」）。根因：胶囊标签清单只认 `cachedTiles`（上传瓦片），纯插座会话（首尾帧连 LoadImage，无瓦片）清单为空，回退正则一路吞到标点。修复：切分逻辑抽为 `ariadne_adapter.js` 纯函数 `splitPromptChips`（悬空编号引用只按「种类词+编号」形状兜底，任何情况不吞正文），创作台与节点本体两处渲染改传 `collectAssets`（瓦片+插座并集）。胶囊纯视觉层，提交给方舟/Kie 的 prompt 一直是纯文本，本次问题不影响计费与生成。前端契约单测新增 4 项（共 18 项）全绿。
- 测试：Python 73 项 + Node `--test` 前端契约 11 项全绿（模式切换不丢值/素材编号/五段式输入/SSE 半包/历史去重上限/过期草稿保护）；`tests/mock_optimizer_server.py` 本地 mock 验证流式/回落/中断（零付费）。

## 0.2.0（2026-09-12）

Ariadne 家族补全（用户拍板：全家桶统一在 Ariadne 分类）：

- **Ariadne · Omni 1.1 参考素材视频（Kie）**：人物/场景/动作/固定角色四路输入，`<IMAGE_REF_N>/<VIDEO_REF_0>/<CHARACTER_ID_0>` 媒体角色自动前置（编号：人物=0、场景从 1 顺延）；已验证价格表估价（20 行全表，时长取贵/仅图按上界口径）；固定角色ID 兼容 ComfyUI-Kie 角色节点输出。
- **Ariadne · Omni 1.1 首尾帧过渡（Kie）**：首帧必填尾帧可选，与参考素材互斥。
- **Ariadne · 一瞬入画（gpt-image-2，Kie）**：视频按范围均匀抽帧（ffmpeg 取中点帧防黑场，1-8 张）+ 参考图双入口；保真提示词模板（scene/keep_people 两模式）逐句移植；多结果图批量落盘。
- ariadne_core 新增 `media.extract_video_frames`（ffmpeg 抽帧）；新增 11 项契约测试（媒体角色编号/互斥/枚举/估价表/保真模板），共 64 项全绿；8291 冒烟 7 节点注册全过。

## 0.1.1（2026-09-12）

三轮调查员审查（核心层 20 项 + 前端 21 项 + 节点/路由 16 项）+ 实机浏览器可视化自查，共修复 57 项缺陷。重点：

- **P0×7**：Kie 渠道首尾帧编号错位（引用悬空照扣费）；四节点缺 IS_CHANGED（重复 Queue 静默回放旧成片）；optimize/estimate 路由缺 loopback 守卫（SSRF/盗用 Key）；轮询终态漏判 failed；TOS 同名覆盖；前端瓦片身份过滤永假（删除无效+素材重复计费翻倍）；@菜单双 @ 前缀。
- **P1×12**：CSS 挂载路径 404、多节点瓦片状态污染、kling 元素上传类型错误、多镜头估价低估 2.8 倍、blur 化石值覆盖、ark 错误结构崩溃、TOS 编码 403 与句柄泄漏、kling 校验层缺失、veo 组合矩阵不全、routes 模块名劫持、路径穿越收口等。
- **可视化批次**：节点最小宽度+挂载后高度重算+DOM 显式宽度（实机截图发现的溢出/截断）、升级同步化（后台标签 rAF 节流）、裁剪浮层交互加固、无切点提示覆盖修复、删除后提示词标签映射重写。
- 新增 ffmpeg 真实媒体测试与 mock 端到端 generate 测试；**53 项测试全绿**；8291 实例 9 项路由实测 + 浏览器全链路交互验证。
- 已知限制：前端更新后需 Ctrl+F5 强刷（浏览器启发式缓存）。详见 `docs/SELF_TEST_REPORT.md`。

## 0.1.0（2026-09-12）

首个版本。Ariadne 视频家族自无限画布移植 ComfyUI（不动 ComfyUI 主体）：

- **Ariadne · Seedance 2.5 视频生成**：火山方舟直连（content/role 官方契约 + TOS 私有桶预签名/Base64 归一化 + 30 分钟轮询）与 Kie 副渠道（input 白名单 + Kie 自家上传）；全能参考/文生/首帧/首尾帧/编辑/延长全模式；`@图片N` → `@图像N`/`@ImageN` 编号编译 + 素材职责句；官方规格预检（视频像素 ≥407696）与真人拦截定向翻译；方舟刊例/Kie 积分双口径估价（e7d40b79 实测 306=17×(14+4) 回归用例）。
- **Ariadne · Veo 3.1（Kie）**：文生/首尾帧/全能参考/延长，15 行价目表全量照录（未列组合显示 -- 不外推）。
- **Ariadne · 可灵 Kling 3.0（Kie）**：文生/首帧/首尾帧/全能参考（@元素名，图片/视频元素二选一）/多镜头（2-5 镜，总时长=镜头和）。
- **Ariadne · Kie 图生图**：五家服务商注册表（nano-banana-pro 默认；字段名差异由注册表收敛，nano 系 image_input / seedream·grok image_urls / gpt-image 系 input_urls）。
- **前端扩展**：素材瓦片（上传/职责切换/移除）、@胶囊提示词（选单+原子胶囊）、✂ 节点内裁剪浮层（对齐输出/分镜均摊/手动区间，服务端 ffmpeg）、费用预估行、中文标签、widgets_values 双序列化、Ariadne 工作台侧栏（密钥/TOS 试传/优化器配置）。
- **自有路由**：`/ariadne/upload|trim|estimate|config|tos_test|optimize`（loopback 限定 + 幂等注册）。
- **产物持久化**：成片强制落 `output/ariadne/`（时效 URL 禁回写）。
- **测试**：41 项 unittest 全绿（全离线 mock，无任何付费调用）。

已知边界：精准编辑标注 UI、可灵元素/分镜可视化编辑器、提示词优化流式输出待后续版本；方舟 `omni_reference_task_type` 与标注帧 data URL 待付费实测。
