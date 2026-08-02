# 文档导航（Documentation Index）

企业智能客服项目的全部文档入口。按**读者角色**分组，按需取用。

> 仓库根的 `docs-update-1~5.md` 是开发过程中的**深度工作笔记/补充材料**（目录全解、架构评估、面试问答、学习笔记、微服务设计），内容详尽但篇幅大，已在本索引末统一标注，建议作为按需查阅的"资料库"而非首读材料。

---

## 🚪 入口（先读这个）
- **[README.md](../README.md)**（仓库根）— 项目门面：一句话定位、一键启动、架构图、技术栈、亮点。Clone 后第一眼。
- **[docs/INDEX.md](INDEX.md)** — 本文件，文档地图。

---

## 👔 给招聘官 / 面试官
- **[docs/resume-project.md](resume-project.md)** — 作品集讲解：这个项目是什么、解决了什么、技术深度拆解、可演示性、能力标签。面试前过一遍。
- **`docs-update-3.md`（仓库根）— [面试问答手册](../docs-update-3.md)** — 50+ 高频面试题与标准答案（项目概述、技术选型、架构、难点、踩坑），面试备战神器。

---

## 🏗️ 给架构师 / 技术负责人
- **[docs/cloud-native-architecture.md](cloud-native-architecture.md)** — 云原生架构设计：容器拆分、K8s/Helm、弹性策略、CI/CD、可观测性。
- **`docs-update-5.md`（仓库根）— [云原生微服务架构设计文档](../docs-update-5.md)** — 微服务拆分、技术栈、服务间通信的完整设计说明。
- **`docs-update-2.md`（仓库根）— [云原生架构完整性评估](../docs-update-2.md)** — 对现有架构的完整性自检与缺口分析。

---

## 🔌 给接入方 / 后端开发者
- **[docs/api.md](api.md)** — **接口协议**：`/ws/chat` 实时对话 WebSocket 协议、`/ws/agent` 坐席协议、REST 端点按域速查、联调示例。对接本系统必读。
- **[docs/CODE_STYLE.md](CODE_STYLE.md)** — 代码规范：类型、命名、异常处理、测试、异步、提交约定。
- **[docs/PR_REVIEW_CHECKLIST.md](PR_REVIEW_CHECKLIST.md)** — 合并前自检清单（设计/异常/并发/安全/可观测/测试/文档 7 大类）。
- **[docs/TECH_SHARING_2026.md](TECH_SHARING_2026.md)** — 5 期内部分享：确定性单测、异常红线、async 正确性、可观测性、评审文化。

---

## 🗺️ 代码导览 / 学习
- **`docs-update-1.md`（仓库根）— [项目文件目录全解](../docs-update-1.md)** — 逐文件讲解 `src/` 每个模块的职责与关键类，快速建立全局认知。
- **`docs-update-4.md`（仓库根）— [完整学习笔记](../docs-update-4.md)** — 开发过程中的系统学习笔记，覆盖从 0 到 1 的踩坑与原理。

---

## 📌 文档维护说明
- 精选文档统一放在 `docs/`，由本索引串联。
- 根目录 `docs-update-*.md` 为历史工作笔记，命名带日期/序号，新读者无需从头读，按上表"按需查阅"即可。
- 如发现文档与代码不符，以 `src/`（源码）与 `docs/api.md`（接口）为准，并请同步更新对应文档。
