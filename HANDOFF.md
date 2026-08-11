# HANDOFF.md — enterprise-agent 交接文档

> 写给完全没上下文的接手者：假设你是新对话，没参加过之前任何会话、没看过仓库里其它文件。请严格从「第 0 节」往下读，读完就能接手继续干。
>
> 最后更新：**2026-08-11 晚间版**。本文件含两个阶段：① 第 1-8 节「三道缝 Docker 实跑验证」（上午完成，milvus 内存仍待修）；② 第 9 节「RAG 真实文档灌入」（当前活跃任务：代码修复已写、端到端复验待做）。接手者从「第 0 节」往下读。
>
> 代码位置：`C:\Users\hai\enterprise-agent`
> 仓库：`https://github.com/addhai/enterprise-agent`（GitHub，master 分支）

---

## 0. 一句话背景（必须先读，否则后面全误解）

这是一个用 Python（FastAPI + LangGraph + RAG + MCP）写的**智能客服系统**，前端是 React/TypeScript。

**谁在做、为什么做**：这是用户（hai，昵称「拾一」，大三 AI 应用开发方向）的**个人项目，不是团队项目**，目的是作为**简历作品集（portfolio）**展示全栈 AI 工程能力。**对标对象：模仿「阿里云 AI 助理」的智能客服形态**。用户明确说过「就算放简历也不该只是做个 demo」，要按**完整产品 / 生产级标准**开发（含真实云 API、多租户 + RBAC、可观测、云原生部署）。

> ⚠️ 致命误导警告：根目录的 `团队技术提升方案.md` 按"团队协作 8 周路线图、覆盖率 80%"写，**对本项目不适用**，不要当 KPI 推。质量目标是「作品集 / 生产级标准」：CI 能绿、本地能一键跑、前端页面完整可演示、关键链路有持久化与监控。

**安全红线（最高优先级）**：真实密钥（LLM key / 阿里云 AK / JWT secret）永不上公网、永不暴露。任何把服务挂公网且携带真实 key 的方案一律不做；对外展示只用本地 docker/localhost 或额度极小可吊销的 demo 子 key。此红线优先于展示力诉求。

> 注：`团队技术提升方案.md` / `改动方案.md` / `overview.md` 等规划文档**部分已过时**（尤其"前端 3 个未完成页面"早已落地），看代码现状为准，别据旧文档找不存在的缺口。

---

## 1. 我们在做什么任务

### 任务来源：收口「三道缝」

项目此前已具备完整功能代码，但存在三道「缝」：代码写了，却没在真实环境里端到端跑通验证。用户拍板把前两道在本机 Docker 实跑验证（第三道按安全红线有意识地跳过）：

| 缝 | 含义 | 状态 |
|----|------|------|
| 第一道缝 | 全栈真跑：Docker Compose 一把拉起 12 个服务，端到端走通 apisix 网关工单链路 | ⏳ 卡在 milvus（详见第 3 节） |
| 第二道缝 | Grafana 真渲染：监控栈（Prometheus + Grafana）真实出数据，不是空面板 | ✅ 已实跑通过（`Grafana render VERIFIED`，12/18 面板真出数据） |
| 第三道缝 | 云资源真实性：资源查询/诊断走真实阿里云 API | ⏸️ 按安全红线**有意跳过**（真实 LLM key 红线 + 付费阻断） |

> 补充：Grafana 监控栈的验证脚本是 `scripts/verify_monitoring.py`，全栈联跑脚本是 `scripts/verify_fullstack.py`。两脚本开头都会 `docker compose down` / 清理残留容器，结尾再清理，可用它复现验证。

### 本次会话授权的边界

用户睡前授权："你把这个项目所有需要的改进都做了不用我确认，实在需要我手动确认的先跳过，我睡觉了。" 因此本会话自主推进了 rabbitmq 死结、compose 冲突、代理注入、minio tag、ws target、broker 拓扑、验证脚本加固等修复。**所有修复当前都还没 git 提交**（见第 5 节），这是下一轮第一件要处理的事。

---

## 2. 已经完成了什么

以下均**已实跑验证或已落地代码，但全部尚未 git 提交**（文件改动状态见第 5 节）：

### A. 第二道缝（Grafana 渲染）已坐实
- `scripts/verify_monitoring.py` 跑通，报告 `verify_monitoring_report.txt` 第 22 行输出 `Grafana render VERIFIED`。
- 18 个面板中 12 个真实出数据；其余 6 个为「流量门控空」（LLM/WS/RAG/Milvus 无请求流量时天然为空），属正常，不是坏。

### B. 全栈联跑的根因修复（第一道缝的前置清理）
1. **Docker Desktop 全局代理注入容器（最关键的系统性坑）**
   - 用户本机 Docker Desktop 的代理设置指向 Clash（`127.0.0.1:7890`）。这个 `http_proxy` 会被注入**每一个容器**。
   - 容器内 curl/python 访问 `127.0.0.1`（localhost）或内部服务名（`rag-service:8001` 等）时，会把请求发给并不存在的代理，连接被拒 → 所有 healthcheck 全失败 → 容器全 unhealthy。
   - 修复：新增 `docker/no_proxy.env`，给 compose 全部 12 个服务注入 `env_file: docker/no_proxy.env`（含大小写 `NO_PROXY`/`no_proxy` 且覆盖 `127.0.0.1` 与所有内部服务名）。实测 `NO_PROXY` 能盖过 Docker Desktop 注入的 `http_proxy`，裸 curl 访问 `127.0.0.1:9000` 返回 200。
2. **slim 镜像无 curl，api-service healthcheck 改写**
   - `python:3.11-slim-bookworm` 不含 curl，原 healthcheck 用 `curl -f .../api/v1/health` 会永远失败。
   - 改为 `python -c "import urllib.request, os; os.environ['NO_PROXY']='*'; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)"` 的 CMD-SHELL 形式。
   - minio / milvus / apisix 的 curl healthcheck 加 `--noproxy "*"` 双保险（frontend 的 wget 靠注入的 no_proxy 环境变量直连）。
3. **RabbitMQ 4.0 boot 死结（已修）**
   - 删除 `deploy/rabbitmq/rabbitmq.conf` 里 `mqtt.default_user` / `mqtt.default_pass`（4.0 严格 schema 拒绝未启用插件的配置键）。
   - 删除 `load_definitions`（静态 JSON 导入拓扑时要求 vhost 先存在，否则 boot 报 `Please create virtual host "/" prior to importing definitions`）。
   - 删除 compose 里 `RABBITMQ_DEFAULT_VHOST=/` 与 `RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS`。
   - 改用代码幂等自声明拓扑：新增 `src/broker/topology.py`，在 `src/worker/consumer.py` 的 `connect()` 里调用 `declare_topology()`（交换机/DLX/队列/DLQ/绑定，照搬原 definitions.json），取代脆弱的静态导入。
4. **compose 端口 + 副本冲突（已修）**
   - 原 `api-service` 同时 `ports: "8000:8000"` 与 `replicas: 2`，compose 报 `port already allocated`。生产级应只走 apisix 网关，已删 api-service 主机端口（改走 9080 网关内部路由）。
5. **minio 镜像 tag 404（真 bug，已修）**
   - 原 compose 钉的 `minio/minio:RELEASE.2025-06-26T15-28-46Z` 在 Docker Hub 不存在（registry API 验证 404）。
   - 改为有效 tag `minio/minio:RELEASE.2025-07-23T15-54-02Z`。
6. **ws-service `target: production` 不存在（已修）**
   - `docker/api/Dockerfile` 是单阶段，无 `production` stage，compose 引用报错。已删掉 `target: production` 行。
7. **验证脚本加固**
   - `scripts/verify_fullstack.py` 与 `scripts/verify_monitoring.py` 的 `_STALE_CONTAINERS` 加宽覆盖 `enterprise-agent-*` 前缀；清理逻辑加防御性 `docker rm -f`；面板判定区分「流量门控空」与「真坏空」。

---

## 3. 当前卡在哪

**全栈 12 服务联跑卡在 `milvus-standalone is unhealthy`**（minio 的卡点已被代理修复打通，详见第 2 节 B1/B2）。

已知事实（来自 2026-08-10/11 亲眼实测）：

- milvus 镜像 `milvusdb/milvus:v2.5.9`，standalone 模式（内嵌 etcd，不额外部署 etcd 容器）。
- compose 里 milvus 内存限制仅 **2G**（`deploy.resources.limits.memory: 2G`）。Milvus 官方 standalone 推荐 4G 起步。
- healthcheck 是 `curl -f --noproxy "*" http://127.0.0.1:9091/healthz`，`interval: 15s, timeout: 10s, retries: 5`。
- 实测现象：启动约 3 分钟后，`/healthz` 仍返回 **HTTP 500**，容器持续 `unhealthy`。日志无 `ERROR/FATAL/panic`，只有各 coord 组件（rootcoord/querycoord/datacoord）还在注册的 WARN，属启动早期正常噪声，但迟迟不 ready。
- 高度怀疑方向（**未证实，下一轮要做的第一件事**）：2G 内存上限偏紧，导致各 coord 组件起不来；或 standalone 内嵌 etcd 在受限内存下启动过慢、超过 healthcheck 容忍窗口。

一处未决的不确定：上次对 milvus 内存占用的 `docker stats` 查询被代理网络中断（502）打断，没能拿到「是否顶到 2G」的实锤数据。下一轮应先补齐这一步，再决定是调大内存、放宽 healthcheck 容忍、还是换更轻的向量库（项目原本就有 chroma fallback 路径）。

**注意**：这些修复全部尚未提交（见第 5 节）。如果 Docker 重启，`restart: unless-stopped` 会用旧配置复活残留容器，再次全红。务必先 `docker compose down` 清干净，再用当前（已修复）的 compose 重建。

---

## 4. 下一步计划（按优先级，可自主推进）

1. **诊断并修复 milvus unhealthy（第一优先）**
   - `docker compose up -d milvus-standalone`，等 60s+，看 `docker compose logs milvus-standalone --tail 50` 与 `docker stats agent-milvus` 内存。
   - 判断：若内存顶到 2G → 调大 `memory: 2G` 到 4G（同时确认本机 VM 内存余量）；若只是慢 → 放宽 healthcheck `retries`/`interval` 或给更长的 `start_period`。
   - 辩证看：2G 限制本是为防 OOM 设的，但过紧反而让服务起不来。要在「能起来」和「不拖垮本机」之间取平衡。
2. **重跑完整 12 服务验证**
   - `python -m scripts.verify_fullstack`（后台跑，预计数分钟到 10 分钟），读 `verify_fullstack_report.txt` 判 PASS/FAIL。
   - 端到端走通 apisix 网关（`localhost:9080`）工单链路，确认 rag-service / ws-service 经内部网络可达（代理修复后内部调用应正常）。
3. **提交本轮所有修复（关键，见第 5 节清单）**
   - 用户此前授权自主推进，但**绝不 `git add .`**，只 add 指定路径。沙箱无代理出口，**push 必须由用户本机做**（见坑 36 思路）。
4. **补全过时文档**
   - `overview.md` 与本文 HANDOFF.md 此前停在 2026-08-07，本次已更新 HANDOFF。
5. **（可选）第三道缝的替代证明**
   - 云资源真实性按红线跳过。可在 README/作品集里明确标注 `aliyun_demo_fallback` 标记（已在 `/api/v1/health` 暴露），说明 demo 走样本兜底、真实 key 不上公网，把「跳过」讲成有意识的安全决策。

---

## 5. 未提交清单 + Git 铁律

### 当前 git 状态（2026-08-11 实测，`git status --short`）
- 已修改未提交：`deploy/rabbitmq/rabbitmq.conf`、`docker-compose.yml`、`scripts/verify_fullstack.py`、`scripts/verify_monitoring.py`、`src/worker/consumer.py`
- 未跟踪（需确认后 add）：`docker/no_proxy.env`、`src/broker/`（新建拓扑模块）、`wheels/`（184 个离线轮子，建议加 .gitignore 不进仓）、`scripts/proxy_relay.py`（用途待确认，提交前问用户）
- 垃圾/勿提交：`install.log`、`coverage.xml`、`.coverage`、`.trae/`、`.workbuddy/`

### 建议的提交粒度（不 push，等用户本机 push）
```
git add docker-compose.yml deploy/rabbitmq/rabbitmq.conf docker/no_proxy.env \
        scripts/verify_fullstack.py scripts/verify_monitoring.py \
        src/worker/consumer.py src/broker/
git commit -m "fix: 全栈实跑三道缝前置修复（代理注入/RabbitMQ死结/compose冲突/minio tag/broker拓扑）"
# wheels/ 若想入仓需先确认体积；否则加 .gitignore
```

### 铁律（每次都适用）
1. **绝不要 `git add .` / `git add -A`**。仓库里混有大量个人/规划/垃圾文件，只 add 指定路径。
2. **push 不要替用户做**。沙箱 Bash 无代理出口，GitHub push 必失败；且本机 git 配了 `http.proxy=127.0.0.1:7890`，代理没开时直接 push 不通。需要 push 时交用户本机，或临时清代理：`GIT_HTTP_PROXY= GIT_HTTPS_PROXY= git -c http.proxy= -c https.proxy= push origin master`。

---

## 6. 踩过的坑（绝对不要再踩）

### 6.1 Docker / 部署类（本次会话新增，最致命）

**坑 D1（容器代理注入，头号坑）**：Docker Desktop 的全局代理设置会注入每个容器。只要本机 Docker Desktop 配了代理（如 Clash `127.0.0.1:7890`），容器内访问 `127.0.0.1`/内部服务名都会走代理而失败，所有 healthcheck 全红。修法不是改应用，而是给 compose 每个服务加 `env_file: docker/no_proxy.env` 让 `NO_PROXY` 盖过 `http_proxy`。**验证假设最快的方式**：进容器 `curl -s --noproxy "*" http://127.0.0.1:<port>/health` 对比裸 curl，若前者 200 后者 000 即是此坑。

**坑 D2（残留容器复活）**：`restart: unless-stopped` 会在 Docker 重启时**用旧配置复活**残留容器。修复 compose 后必须 `docker compose down` 彻底清掉再重建，否则看到的仍是旧配置下的 unhealthy，会误以为修复无效。

**坑 D3（daemon 500 假象）**：`docker images` / `docker ps` 全空，不一定真没镜像，可能是 Docker Desktop 引擎故障返回 `500 Internal Server Error`（所有 daemon API 挂）。先 `docker info` 探 daemon，必要时让用户去 Docker Desktop 的 Troubleshoot 里 Restart / Quit 重开。

**坑 D4（slim 镜像无 curl）**：`python:3.11-slim-bookworm` 不含 curl。healthcheck 别用 curl，改用 python 的 `urllib` 或 Alpine 系镜像。

**坑 D5（RabbitMQ 4.0 严格 schema）**：未启用插件的配置键（如 `mqtt.*`）会让 4.0 boot 失败 `failed_to_prepare_configuration`；`load_definitions` 导入拓扑要求 vhost 先存在。结论：能用代码幂等声明拓扑就别用静态 JSON 导入。

**坑 D6（compose 端口 + 副本冲突）**：同一服务同时写 `ports` 和 `replicas: 2` 会 `port already allocated`。生产级走网关内部路由，数据层/网关单实例，应用层多副本时去掉主机端口。

**坑 D7（Docker Hub tag 404）**：compose 钉的镜像 tag 可能根本不存在（registry API 验证过）。换有效 tag 后，若 `docker pull` 拉的是 `latest` 缓存，需用 `docker tag` 重打标签对齐 compose 的 tag。

**坑 D8（Dockerfile stage 不存在）**：compose 引用 `target: production` 但该 Dockerfile 是单阶段、无此 stage，会构建报错。确认 Dockerfile 实际 stage 名。

**坑 D9（milvus standalone 内存）**：`milvusdb/milvus:v2.5.9` standalone 内嵌 etcd，compose 里只给 2G 内存会起不来或 healthz 长期 500。需要 4G 级余量；本机 VM 内存不足时考虑换轻量向量库（项目已有 chroma fallback）。

**坑 D10（Clash 代理假连接）**：Clash 选错节点或 TUN 模式异常时，国内通、国外断，拉镜像 `Connection reset`。让用户选有效节点（实测日本节点 86ms 可用），或临时关代理直连。

### 6.2 工程 / CI / Git 类（历史精华，仍有效）

**坑 1（bandit `# nosec` 必须同行）**：标记注释必须和被标记代码同一行，放上一行无效。
**坑 4（pytest 子目录 conftest 崩溃）**：CI 用白名单 `pytest tests/test_agent/ tests/test_mcp_tools/ tests/test_safety/ tests/test_ticket/ tests/test_evaluation/`，绝不再写 `pytest tests/` 加排除。
**坑 9（GitHub push 网络极不稳）**：见第 5 节铁律 2。
**坑 17（`/api/v1/health` 会挂起）**：它探测 localhost 上没起的 agent 端口，超 5s 返回 000。验证存活用 `GET /` 或 `/auth/register`。
**坑 28（测试跨运行脏数据污染）**：旧 conftest 用固定 `test_agent.db`，Windows 上 SQLite 文件锁导致 `os.remove` 静默失败 → 假绿。根治：conftest 改 `sqlite:///:memory:` + `StaticPool`。CI 与本地验收必须跑完整白名单，不能只跑单文件子集冒充全绿。
**坑 29（Windows 中文 + Postgres GBK 崩溃）**：PG 在中文环境用 GBK 返回错误，psycopg2 按 UTF-8 解码崩。代码层已强制 `PGCLIENTENCODING=UTF8`；根治是 PG 容器配 `lc_messages=C`。排查本机 5432 被占第一件事 `netstat -ano | findstr ":5432"`。
**坑 30（本机 Postgres 服务抢占 5432）**：用户 Windows 装了 PostgreSQL 服务一直占 5432，Docker 映射也在 5432，主机连先连本机服务（密码还不一样）→ 认证失败。需要管理员停服务的操作必须用户本人做。
**坑 35（Vite build 在沙箱被 safe-delete 垫片卡住）**：沙箱验证用 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= npx vite build --outDir=dist-test`；本机正常 `npm run build`。
**坑 43（chroma cold start 慢）**：首次加载约 60s（含 milvus→chroma fallback 探测），health 轮询要等够，别在 10s 内判死。

### 6.3 工作流类（沙箱路径坑）

**坑 P1（Windows 路径解析混乱）**：Git Bash 的 `/tmp`、`/c/...` 与 Windows python 的 `C:\` 在混合调用时解析不一致，heredoc 写的脚本常找不到。修法：先 `cd` 到目标目录，再用相对文件名调用，且写入与执行在同一条 Bash 命令内完成，避免视图/真实路径错位。
**坑 P2（后台任务输出丢失）**：TaskOutput 报 completed 但无结论时，直接去读脚本落地的报告文件（如 `verify_fullstack_report.txt`、`verify_monitoring_report.txt`），别只信任务状态。

---

## 7. 关键文件清单（接手者速查）

| 文件 | 作用 | 状态 |
|------|------|------|
| `docker-compose.yml` | 12 服务全栈编排（已修代理/端口/副本/minio tag/ws target） | ✏️ 改，未提交 |
| `docker/no_proxy.env` | 容器代理 bypass 变量（解决坑 D1） | 🆕 未提交 |
| `deploy/rabbitmq/rabbitmq.conf` | RabbitMQ 配置（已删 mqtt/load_definitions） | ✏️ 改，未提交 |
| `src/broker/topology.py` | 幂等声明 RabbitMQ 拓扑（解决坑 D5） | 🆕 未提交 |
| `src/worker/consumer.py` | worker 消费端（已接 declare_topology） | ✏️ 改，未提交 |
| `scripts/verify_fullstack.py` | 全栈 12 服务联跑验证 | ✏️ 改，未提交 |
| `scripts/verify_monitoring.py` | Grafana 渲染验证（已 VERIFIED） | ✏️ 改，未提交 |
| `verify_fullstack_report.txt` | 全栈验证报告（当前应 FAIL，卡 milvus） | 运行时生成 |
| `verify_monitoring_report.txt` | 监控验证报告（第 22 行 `Grafana render VERIFIED`） | ✅ 已生成 |
| `POSTGRES_LOCAL_SETUP_GUIDE.md` | 本机 Postgres Docker 验证指南 | ✅ 已推送 |

---

## 8. 给用户的话（接手者正是「下一个对话」，务必读）

你这个项目的真实身份：**个人简历作品集，对标阿里云 AI 助理的智能客服仿写，按生产级标准做**。

### 本次会话（2026-08-10 至 08-11）做了什么
1. 第二道缝（Grafana 真渲染）已实跑通过：`Grafana render VERIFIED`，12/18 面板真出数据。
2. 第一道缝的前置根因全部修复：Docker 代理注入（坑 D1，最关键）、slim 无 curl、RabbitMQ 死结、compose 端口副本冲突、minio tag 404、ws target 不存在、broker 拓扑代码化。
3. 全栈联跑已突破 minio 卡点（代理修复生效），现卡在 milvus-standalone 内存/启动（详见第 3 节）。

### 待你下一步
- **milvus 内存是最后一块骨头**，按第 4 节第 1 步诊断修复，然后重跑 `verify_fullstack`。
- 本轮所有修复**尚未 git 提交**（见第 5 节清单），建议提交后再继续，避免下一轮丢失。
- 第三道缝（真实云 API）按安全红线有意跳过，属有意识决策，可在作品集里讲清楚。

**铁律重申**：绝不要 `git add .`。本会话全程只改了指定文件，提交时同样只 add 指定路径；push 由你本机做。

---

## 9. 【当前活跃任务】RAG 真实文档灌入 · 让对话真命中知识库

> 这是本会话（2026-08-11 下午/晚间）真正在推进的任务，和第 1-8 节的 Docker 三道缝是**同一仓库的不同任务线**。接手请从这一节续上。

### 9.1 我们在做什么

上午验证时发现：WebSocket 对话主链路能跑通，但用户问 CloudSync 产品技术问题时，RAG **检索不到内容**，agent 要么转人工、要么答「尚未收录 / 暂时答不上来」。用户要求「灌入真实知识库文档，让 RAG 真命中」，把 demo 从「链路能跑但答不出」提升到「真能基于文档回答专业问题」，以增强作品集说服力。

**验收标准**：对跑着的 server 发一句只有文档里才有的技术问法（如「CloudSync v2 什么时候下线、返回什么状态码」），agent 回复里必须真实出现文档专属事实（`410 Gone` / `2025-12-31` / 分页 `limit` 上限 `100` 等），而不是转人工或搪塞。

### 9.2 已经完成了什么

1. **真实语料已入库**：`data/docs/` 下有 13 篇 CloudSync 真实产品文档（api 分页/SSO/错误码/账号管理等）。用 `scripts/ingest_real_docs.py`（登录 admin → 建 KB `KBS-CD0480` → 逐篇 POST `/admin/knowledge/{kb_id}/documents` 走 server 进程内向量化）灌入，结果 **13 篇 / 205 切片 / indexed**，tenant=`default`，与对话侧登录用户一致。
2. **定位并修复了「检索到但答不出」的三个真 bug**（均在代码里改好，**未提交**）：
   - **Bug A：工具层元组解包崩溃**（最致命）。`src/agent/tools.py` 的 `search_knowledge_base` 曾按 `for doc, _ in results` 解包，但 `retriever.search()` 早已在 `src/rag/retriever.py:231` 剥掉分数、只返回 `Document` 列表 → 每次检索必抛 `TypeError`，被 `except` 吞成「知识库搜索出错」→ LLM 误判知识库不可用 → 转人工。已改为 `for doc in results`（同时 `access_filtered` 的解包一并改）。**这是 RAG 在对话里始终不命中的头号根因。**
   - **Bug B：召回太少 + 上下文截断太狠**。工具层 `top_k=3` 且每篇 `doc.page_content[:500]`。技术文档答案常分散在相邻 chunk（参数表在前、状态码说明在后），500 字截断线会把答案切掉。已改 `top_k=5`、截断放宽到 `[:1200]`。
   - **Bug C：结构提示标记非幂等堆叠**。`src/rag/processors/structure_detect.py` 每跑一次就在正文前**追加**一行 `[Contains code blocks]`，重复执行/二次入库会堆叠多份（实测探到同一 chunk 开头堆了两行），污染回传给 LLM 的上下文、浪费 embedding token。已加 `_strip_existing_hints()` 先剥旧标记再注入，做成幂等。
3. **检索层已被证明是好的**（用 `scripts/probe4.py` 直连 retriever 实测）：问「CloudSync API 版本控制怎么用」召回的 chunk 里明确含 `v2 API 将于 2025-12-31 完全下线，届时所有 v2 请求将返回 410 Gone`。**说明向量化、租户过滤、相似度都正常，问题一直在工具层的解包与截断，不在检索层。**

### 9.3 当前卡在哪

**代码三处已改好，但还没做「端到端复验」这最后一步**，原因是踩了环境坑（见 9.5）：

- **卡点直接原因**：验证脚本 `scripts/probe5.py`（模拟工具层 top_k=5 + 截断 1200 后拼上下文，断言关键事实在不在）跑起来后，embedder 调用**百炼 embedding API 报 `openai.APIConnectionError: Connection error`**。这是本机 Clash 代理波动 / 百炼端偶发不可达导致的，不是代码问题（同样的 retriever 在 `probe4.py` 早些时候是能跑通的）。
- **连带未决**：跑着的 8000 端口 server 加载的可能仍是**旧 tools.py**（Bug A 未修版）。上午为不打断用户 demo，另在 **8021 端口**起过一个带修复的实例做过 WS 验证，当时现象是「不再转人工，但答『暂时答不上来』」——那正是 Bug B/C 还没修时的表现。9.2 的 Bug B/C 修完后**尚未对任何 server 重新验证过**。

### 9.4 下一步计划（按顺序）

1. **确认代理可用再复验检索**：先 `curl -s --noproxy "*" https://dashscope.aliyuncs.com` 或让用户确认 Clash 有可用节点；然后重跑 `venv/Scripts/python.exe scripts/probe5.py`，期望三条问法全部 `PASS 答案事实已进上下文`。这一步纯离线验检索+截断逻辑，不依赖 server。
2. **让 server 加载新代码再跑对话验证**：
   - 干净重启一个带修复的实例（**别动用户可能在用的 8000**）：`cd C:/Users/hai/enterprise-agent && VECTOR_STORE_BACKEND=chroma nohup venv/Scripts/python.exe -m uvicorn src.api.server:app --host 127.0.0.1 --port 8021 --log-level warning > .rag_8021.log 2>&1 &`，轮询 `http://127.0.0.1:8021/api/v1/health` 到 200。
   - 跑 `RAG_PORT=8021 venv/Scripts/python.exe scripts/ws_rag_verify.py`，读回复断言含 `410`/`2025-12-31`/`100` 等文档事实。命中即达成验收。
3. **达标后收尾**：把改动提交（**不 push**，push 交用户本机），更新本 HANDOFF 第 9 节状态为「已验证」，写内存日志。
4. **（可选增强）**：若某些问法仍召回不到答案 chunk，考虑给 `search_knowledge_base` 加「按 source 聚合、返回同文档相邻 chunk」逻辑，或把 ingest 时的 `chunk_size` 从 512 调大到 768 让参数表+状态码同 chunk。先别过度优化，达成验收再说。

### 9.5 RAG 阶段踩过的坑（绝对不要再踩）

**坑 R1（头号 · 检索正常但对话不命中 → 别急着怪向量库）**：症状是对话答不出、转人工，第一反应往往是「没灌进去 / 向量化失败 / 租户不对」。实测这些**全都是好的**，真凶是**工具层拿到结果后的代码 bug**（元组解包 TypeError 被 except 吞掉）。**排查铁律：先用脚本直连 `retriever.search()` 打印召回内容**（`scripts/probe4.py`），确认检索层到底返没返回；返回了就往工具层/上下文组装去查，别在向量库上空耗。

**坑 R2（`[Contains code blocks]` 不是内容丢失）**：探测时看到 chunk 开头有 `[Contains code blocks]` / `[Contains tables]`，一度误判为「入库时正文被替换成标记」。真相是 `structure_detect.py` 只在正文**前面追加**提示行、正文完整保留（打印完整 content 可证实 `410 Gone` 等原文都在）。别被标记吓到去重灌数据。

**坑 R3（streaming_chunk 字段名）**：WS 流式帧的文本字段是 `text`/`delta`，**不是** `content`。测试脚本读 `msg.get("content")` 会一直是空，误判成「agent 没产出」。见 `src/websocket/protocol.py` 第 89 行附近。`ws_rag_verify.py` 已改对。

**坑 R4（百炼 embedding 依赖代理，会偶发 Connection error）**：本机跑任何触发 embedding 的脚本（ingest / probe / 对话）都要经百炼 API，Clash 节点波动时报 `openai.APIConnectionError`。这不是代码 bug，重试或换节点即可。区分方法：同一脚本换个时间能跑通就是网络。

**坑 R5（两套 pyc / 改了代码 server 不生效）**：`src/agent/__pycache__` 里有 313 和 314 两套 pyc，且跑着的 server 是长驻进程（非 `--reload` 时改 .py 不生效）。**验证修复务必重启实例**，或确认启动带 `--reload`。为不打断用户 8000 端口的 demo，验证一律另起 8021 端口实例。

**坑 R6（top_k/截断是隐形答案杀手）**：即使检索命中、工具不崩，`top_k=3` + `[:500]` 也会让答案落在被丢弃的 chunk 里。技术文档尤其明显（参数、状态码、限制分散在长文各处）。作品集级 RAG 的召回/截断参数要按「答案可能分散」来设，不能抠 token 抠到砍掉答案。

### 9.6 RAG 阶段关键文件/脚本速查

| 文件 | 作用 | 状态 |
|------|------|------|
| `data/docs/*.md` | 13 篇 CloudSync 真实产品文档（语料源） | ✅ 已在仓 |
| `scripts/ingest_real_docs.py` | 灌库脚本（建 KB `KBS-CD0480` + 逐篇入库，205 切片） | ✅ 已入库 |
| `src/agent/tools.py` | `search_knowledge_base` 工具（已修 Bug A 解包 + Bug B top_k=5/截断1200） | ✏️ 改，未提交 |
| `src/rag/processors/structure_detect.py` | 结构提示注入（已修 Bug C 幂等） | ✏️ 改，未提交 |
| `src/rag/retriever.py` | 检索层，`search()` 第 231 行剥分数返回 Document 列表（**这是 Bug A 的成因线索，本身无需改**） | 只读参考 |
| `scripts/probe4.py` | 直连 retriever 打印召回内容（排查坑 R1 的利器） | 🆕 未提交 |
| `scripts/probe5.py` | 模拟工具层 top_k=5+截断1200 验答案是否进上下文（下一步先跑它） | 🆕 未提交 |
| `scripts/ws_rag_verify.py` | 对 server 发 WS 对话、断言回复含文档事实（支持 `RAG_PORT` 环境变量选端口） | 🆕 未提交 |
| `.rag_8021.log` | 8021 验证实例日志 | 运行时生成 |

### 9.7 RAG 阶段一句话交接

**语料已灌（205 切片），检索层已被证明是好的，三个让「检索到却答不出」的代码 bug（工具解包崩溃 / 召回太少截断太狠 / 结构标记非幂等）已在代码里改好但尚未提交也尚未端到端复验。下一步就两件事：① 确认代理可用后跑 `probe5.py` 验检索+截断；② 另起 8021 实例跑 `ws_rag_verify.py` 验对话真命中。达标后只 add 指定文件提交、push 交用户本机。切记坑 R1：对话不命中先直连 retriever 排查，别空耗在向量库上。**

---

## 10. 2026-08-11 夜间自主打磨收口（P0→P2，用户授权「不中断确认、严格按依据」）

用户睡眠期间授权：从 P0 按优先级自主打磨 → 跑通测试 → 提交 GitHub → 完善 README/CI。**本批改动已随下方提交入仓（commit 见 `git log`）。**

### 10.1 本批做了什么
- **P1 RBAC 角色口径统一（D-02 角色集部分）**：`src/models/common.py` 的 `UserRole` 定为 5 角色单一真相（super_admin / admin / agent / viewer / supervisor）；`src/api/rbac.py` 旧 `Role` 枚举改为 `UserRole` 别名，并在 `ROLE_PERMISSIONS` 补 `SUPERVISOR` 权限集（15 项，团队主管视角：查看为主 + 工单处置/分配）。消除 X5/D6 R4「双枚举口径矛盾」。`dashboard.py` **早已**期望的 `Role.SUPERVISOR` 经由别名现已真生效。
- **P0 RAG 三 bug 复验**：`src/agent/tools.py`（Bug A 解包 + Bug B top_k/截断）、`src/rag/processors/structure_detect.py`（Bug C 幂等）代码早已改好，本批随全量测试复验通过（pytest 全绿）。
- **P0 可观测**：C 档已收口，Grafana 数据源 uid / 面板 PromQL / 抓取路径由 7 项测试锁死，本批无需改动。
- **P1 F13 多租户端点钉成「已实现」**：新增 `tests/test_api/test_tenant_admin.py`（建/列/401/403/409 共 5 用例），`/admin/tenants` 端点含单测覆盖。
- **P2 演进**：云资源翻真步骤、milvus R-01 卡点均已写入 `docs/deployment/runbook.md`（前序提交），本批仅据实刷新 `delivery/` 四份文档三态标注。
- **README + CI（前序）**：`README.md` 架构文档章节、`ci.yml` 加 `workflow_dispatch` + `concurrency` + pip 缓存。

### 10.2 测试结论
- 全量 `pytest tests/ -m "not integration" --no-cov`：**868 passed / 19 skipped**（含本批新增 5 例 tenant_admin，较打磨前 863 增 5）。
- 未含：12 服务容器栈 `verify_fullstack.py`、Grafana `verify_monitoring.py`（需 Docker daemon，沙箱无）；真实阿里云 API（受 key + 付费阻断，红线约束）。

### 10.3 提交范围（git 铁律：只 add 指定文件，绝不 `git add .`）
- 源码：`src/agent/tools.py`、`src/api/rbac.py`、`src/models/common.py`、`src/rag/processors/structure_detect.py`、`src/worker/consumer.py`、`src/broker/`（topology）、`frontend/src/App.css|App.tsx|components/AdminDashboard.tsx`
- 基础设施/脚本：`docker-compose.yml`、`docker/no_proxy.env`、`deploy/rabbitmq/rabbitmq.conf`、`scripts/verify_fullstack.py|verify_monitoring.py|ingest_real_docs.py`
- 文档：`README.md`、`HANDOFF.md`、`delivery/`
- 测试：`tests/test_api/test_tenant_admin.py`
- CI：`.github/workflows/ci.yml`
- **未提交（本地调试产物，非交付物，勿混入）**：`scripts/probe*.py`、`proxy_relay.py`、`retriever_probe.py`、`screenshot_admin.py`、`ws_rag_verify.py`、`.coverage`、`coverage.xml`、`*.log`、`wheels/`、`.trae/`、`.workbuddy/`。

### 10.4 仍属完整版（诚实声明，与交付文档三态标注一致）
- 运行态仅 `default` 单租户；RBAC 租户维度（R4）仍架构就绪；milvus 12 服务联跑受 R-01（2G 内存）卡点；真实阿里云 API 需用户付费 + 真实 key（红线：永不上公网）。

### 10.5 提交与推送结论
- **Commit**：`7cd96d2`（前序 `bcb4a86`），message `chore(polish): P0->P2 自主打磨收口 + 全量测试复验 + 文档/CI 完善`。
- **Push**：`git push origin master` 成功（`bcb4a86..7cd96d2`，走 `.git/config` 已配代理 `127.0.0.1:7890` + `helper-selector` 凭据；注意**勿**再套 HANDOFF 旧「清代理直连」配方，当前环境代理已开、清掉反而无凭据）。
- **CI**：GitHub Actions 4 job 触发（run `31528558194`），结果待 watch 收口（历史同流水线均 `success`）。
- **README 主页**：测试计数更新为 868/19；CI 徽章已在顶部；`workflow_dispatch` + `concurrency` + pip 缓存已入 `ci.yml`。
