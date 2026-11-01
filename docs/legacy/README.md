# 迁移前文档（历史存档）

本目录保存 PySide6 版本（≤ v0.7.0）的架构、打包与部署说明，仅供追溯，**不再描述当前实现**。
当前的架构、分层、接口、迁移与发布说明见上级目录：

- [technical-architecture.md](../technical-architecture.md)
- [layered-design.md](../layered-design.md)
- [api.md](../api.md)
- [migration.md](../migration.md)
- [releasing.md](../releasing.md)

`env.example` 是旧版 `.env` 配置样例；新版本首次启动时若在工作目录发现 `.env` 会自动导入（见 migration.md）。
