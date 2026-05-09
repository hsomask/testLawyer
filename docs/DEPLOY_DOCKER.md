# Docker 部署指南（前后端）

架构：**浏览器 → Nginx（静态前端 + 反向代理）→ FastAPI**。同一域名下访问 `/`、`/api`、`/health`，无需在前端写死后端地址。

---

## 一、服务器前置条件

1. **操作系统**：常见 Linux（Ubuntu 22.04 / Debian 12 / AlmaLinux 等）或安装了 Docker Desktop 的 Windows Server。
2. **软件**：  
   - [Docker Engine](https://docs.docker.com/engine/install/) ≥ 24  
   - [Docker Compose](https://docs.docker.com/compose/install/) v2（`docker compose` 命令）
3. **防火墙 / 安全组**：放行你希望对外提供服务的端口（默认 **`80`**；若改端口则放行对应端口）。
4. **资源**：建议 ≥ 1 vCPU、≥ 1 GB 内存（本项目很轻量）。

---

## 二、获取代码

在服务器上：

```bash
git clone <你的仓库地址> workbench
cd workbench
```

或通过 SCP/rsync 上传与本仓库一致的目录（需包含 `Dockerfile.api`、`Dockerfile.web`、`docker-compose.yml`、`docker/nginx.conf`、`legal_calc/`、`main.py`、`pyproject.toml`、`web/` 等）。

---

## 三、构建并启动（推荐）

在项目根目录（含 `docker-compose.yml`）执行：

```bash
docker compose up -d --build
```

- **`api`**：内部监听 `8000`，仅容器网络可达。  
- **`web`**：映射宿主机端口 **`80`** → 容器 `80`（可通过环境变量修改，见下文）。

验证：

```bash
curl -s http://127.0.0.1/health
# 期望：{"status":"ok"}

curl -s http://127.0.0.1/ | head
# 期望：HTML 片段
```

浏览器访问：`http://服务器公网IP/`（若域名已解析则使用域名）。

---

## 四、端口与环境变量

| 变量       | 含义           | 默认 |
|------------|----------------|------|
| `WEB_PORT` | 宿主机映射端口 | `80` |

示例（改用 **8080** 对外）：

```bash
WEB_PORT=8080 docker compose up -d --build
```

---

## 五、HTTPS（生产强烈建议）

Docker 仅提供 HTTP。生产环境建议在前面加一层：

- **云负载均衡 / CDN** 终结 TLS；或  
- **Caddy / Traefik / Nginx** 宿主机反代到 `127.0.0.1:80`，统一证书；或  
- 单独 **`docker-compose`** 里再加一个 **证书容器**（需自行维护域名与证书）。

不在此文档绑定具体云厂商步骤，原则：**对外 443，对内反代到本项目的 `web` 服务端口**。

---

## 六、更新版本

```bash
cd workbench
git pull   # 或其它方式更新代码
docker compose up -d --build
```

---

## 七、日志与排障

```bash
# 查看运行状态
docker compose ps

# 跟踪日志
docker compose logs -f api
docker compose logs -f web

# 仅重建后端
docker compose build api && docker compose up -d api

# 停止并删除容器（不删镜像）
docker compose down
```

常见问题：

1. **`web` 一直 waiting for `api` healthy**  
   - 查看 `docker compose logs api`，确认 `legal_calc/data/lpr_1y_cny.json` 已打进镜像（`Dockerfile.api` 已 `COPY legal_calc`）。

2. **前端能打开但接口 502**  
   - 确认 `docker/nginx.conf` 里 `proxy_pass http://api:8000` 与 compose 里服务名 **`api`** 一致；`docker compose logs web`。

3. **`npm ci` 构建失败**  
   - 确保提交 **`web/package-lock.json`**；本地执行 `cd web && npm install` 后再提交 lock 文件。

---

## 八、仅构建镜像（可选）

```bash
docker build -f Dockerfile.api -t legal-calc-api:latest .
docker build -f Dockerfile.web -t legal-calc-web:latest .
```

推送至私有镜像仓库后，在服务器 `docker pull` + 自行编写 compose 引用镜像标签即可。

---

## 九、安全提示

- 默认 **CORS** 为 `allow_origins=["*"]`，与同域 Nginx 部署一起使用时通常可接受；若前后端分离跨域上线，请改为明确域名。  
- 生产环境建议限制管理入口、配置 **防火墙**、定期 **`docker compose pull` / 重建** 基础镜像。
