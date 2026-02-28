## Alembic使用命令

### 初始化数据库
```bash
alembic init alembic
```

### 生成迁移文件
```bash
alembic revision --autogenerate -m "Initial migration"
```

### 应用迁移
```bash
alembic upgrade head
```


迁移完了记得app.models.SQLiteUUID()替换为SQLiteUUID()
要导入from app.models import SQLiteUUID
因为在app.models中定义了SQLiteUUID，所以在alembic中需要导入
