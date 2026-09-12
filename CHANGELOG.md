# 更新记录

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
