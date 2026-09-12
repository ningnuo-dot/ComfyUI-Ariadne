# 更新记录

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
