## Context Map

### Files to Modify
| File | Purpose | Changes Needed |
|------|---------|----------------|
| `backend/app/main.py` | FastAPI 统一入口与 HTTP 中间件 | 启用响应压缩，补充请求耗时与请求 ID 响应头 |
| `backend/app/config.py` | 应用运行参数 | 增加就绪探针缓存与超时配置，并校验正数边界 |
| `backend/app/db/session.py` | 全局异步数据库引擎与连接池 | 启用失效连接预检和连接回收 |
| `backend/server.py` | Finance API 生命周期与健康探针 | 将昂贵探针改为有界超时、短缓存和并发合并 |
| `backend/tests/integration/test_route_mounting.py` | FastAPI 入口集成测试 | 验证请求诊断头和压缩协商 |
| `backend/tests/market_data/test_server_api.py` | 就绪探针测试 | 验证缓存复用、并发合并和失败超时 |
| `backend/tests/unit/test_config_validation.py` | 配置校验测试 | 验证探针配置拒绝非正数 |

### Dependencies (may need updates)
| File | Relationship |
|------|--------------|
| `deploy/docker-compose.prod.yml` | 每 10 秒调用 `/api/ready`，会直接受益于探针缓存 |
| `frontend/nginx.conf` | 将 `/api` 转发到 FastAPI；浏览器自动协商 gzip |
| `frontend/src/api/client.ts` | 所有前端请求共用 FastAPI 入口，无需改变 API 合同 |

### Test Files
| Test | Coverage |
|------|----------|
| `backend/tests/integration/test_route_mounting.py` | 统一入口、挂载路由和 HTTP 中间件 |
| `backend/tests/market_data/test_server_api.py` | 健康探针与生命周期 |
| `backend/tests/unit/test_database_composition.py` | 共享数据库会话和应用生命周期 |
| `backend/tests/unit/test_config_validation.py` | 生产配置与数值边界 |

### Reference Patterns
| File | Pattern |
|------|---------|
| `backend/finance_god/market_data/coordinator.py` | 对相同上游读取进行并发协调 |
| `backend/finance_god/market_data/transport.py` | 外部调用使用显式超时 |
| `backend/app/main.py` | FastAPI 中间件和统一生命周期所有权 |

### Risk Assessment
- [x] Breaking changes to public API：不改变 JSON 合同，仅新增响应头
- [ ] Database migrations needed
- [x] Configuration changes required：新增参数均有生产安全默认值

### Decision
这是结构性修复，不采用只调大容器健康检查超时的临时方案。应在 API
进程内保证昂贵依赖探针只有一个执行者、结果短期复用且总耗时有上限，同时让
连接池主动剔除断开的 PostgreSQL 连接。
