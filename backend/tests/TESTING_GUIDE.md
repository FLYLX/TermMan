# 测试指南

本指南提供了TermPaws后端项目的测试结构和使用说明，帮助开发者理解如何编写、运行和维护测试。

## 测试结构

项目的测试按照功能和层次结构组织，主要分为以下几类：

```
tests/
├── api/                  # API接口测试
│   └── routes/          # 按路由分组的API测试
├── crud/                 # 数据访问层测试
├── scripts/              # 脚本和工具测试
├── utils/                # 测试工具函数
├── __init__.py           # 测试包初始化
└── conftest.py           # 测试配置和fixture
```

### 测试类型说明

1. **API测试** (`tests/api/routes/`)
   - 测试API端点的功能和行为
   - 使用FastAPI的TestClient模拟HTTP请求
   - 测试认证、授权和请求/响应处理

2. **CRUD测试** (`tests/crud/`)
   - 测试数据访问层的核心功能
   - 直接测试crud.py中的函数
   - 验证数据库操作的正确性

3. **脚本测试** (`tests/scripts/`)
   - 测试项目中的辅助脚本
   - 验证脚本的功能和行为

4. **测试工具** (`tests/utils/`)
   - 提供测试中使用的辅助函数
   - 如创建随机测试数据、获取认证令牌等

## 运行测试

### 环境准备

确保已经安装了所有依赖：

```bash
# 在项目根目录执行
pip install -r requirements.txt
```

### 运行所有测试

```bash
# 在backend目录执行
python -m pytest
```

### 运行特定测试

```bash
# 运行CRUD测试
python -m pytest tests/crud/

# 运行特定测试文件
python -m pytest tests/crud/test_item_handler.py

# 运行特定测试函数
python -m pytest tests/crud/test_item_handler.py::test_create_item_handler

# 运行测试并显示详细输出
python -m pytest tests/crud/test_item_handler.py -v
```

### 运行测试并生成覆盖率报告

```bash
# 安装覆盖率工具
pip install pytest-cov

# 运行测试并生成覆盖率报告
python -m pytest --cov=app

# 生成HTML格式的覆盖率报告
python -m pytest --cov=app --cov-report=html
```

## 编写新测试

### 编写CRUD测试

1. **导入必要的模块**
   ```python
   from sqlmodel import Session
   from app import crud
   from app.models import ItemHandler, ItemHandlerCreate, ItemHandlerUpdate
   from tests.utils.item_handler import create_random_item_handler
   from tests.utils.utils import random_lower_string
   ```

2. **编写测试函数**
   ```python
   def test_create_item_handler(db: Session) -> None:
       name = random_lower_string()
       item_handler_in = ItemHandlerCreate(name=name)
       item_handler = crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=owner_id)
       assert item_handler.name == name
   ```

### 编写API测试

1. **导入必要的模块**
   ```python
   from fastapi.testclient import TestClient
   from sqlmodel import Session
   from app.models import ItemHandlerCreate
   from tests.utils.item_handler import create_random_item_handler
   from tests.utils.user import authentication_token_from_email
   ```

2. **编写测试函数**
   ```python
   def test_create_item_handler_api(client: TestClient, normal_user_token_headers: dict[str, str]) -> None:
       data = {"name": "Test Handler", "model": "test-model"}
       response = client.post(
           "/api/v1/item-handlers/",
           headers=normal_user_token_headers,
           json=data,
       )
       assert response.status_code == 200
       content = response.json()
       assert content["name"] == data["name"]
   ```

### 创建测试工具函数

1. **在utils目录下创建工具文件**
   ```python
   # tests/utils/item_handler.py
   from sqlmodel import Session
   from app import crud
   from app.models import ItemHandler, ItemHandlerCreate
   from tests.utils.user import create_random_user
   from tests.utils.utils import random_lower_string

   def create_random_item_handler(db: Session) -> ItemHandler:
       user = create_random_user(db)
       assert user.id is not None
       name = random_lower_string()
       item_handler_in = ItemHandlerCreate(name=name)
       return crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=user.id)
   ```

## 测试配置

### conftest.py

`conftest.py`文件包含测试配置和fixture，主要功能：

1. **数据库fixture**：创建测试数据库会话
2. **客户端fixture**：创建FastAPI测试客户端
3. **认证fixture**：提供认证令牌
4. **测试清理**：在测试后清理数据

### 测试数据管理

- 测试使用独立的数据库（默认SQLite内存数据库）
- 每个测试会话开始时创建表
- 测试结束后清理数据，确保测试隔离
- 可以使用`create_random_*`工具函数创建测试数据

## 最佳实践

1. **测试隔离**：每个测试应该独立运行，不依赖其他测试的结果
2. **断言清晰**：使用明确的断言消息，便于调试
3. **测试覆盖**：确保测试覆盖主要功能和边界情况
4. **使用fixture**：利用fixture减少重复代码
5. **测试命名**：使用描述性的测试函数名，如`test_create_item_handler`
6. **避免硬编码**：使用随机数据或配置值，提高测试的可靠性
7. **测试文档**：为复杂的测试添加注释，说明测试目的和预期行为

## 测试示例

### CRUD测试示例

```python
# tests/crud/test_item_handler.py

def test_update_item_handler(db: Session) -> None:
    # 创建测试数据
    item_handler = create_random_item_handler(db)
    
    # 更新数据
    new_name = random_lower_string()
    item_handler_update = ItemHandlerUpdate(name=new_name)
    
    # 执行更新
    updated_item_handler = crud.update_item_handler(
        session=db, 
        db_item_handler=item_handler, 
        item_handler_in=item_handler_update
    )
    
    # 验证结果
    assert updated_item_handler.name == new_name
    assert updated_item_handler.id == item_handler.id
```

### API测试示例

```python
# tests/api/routes/test_item_handlers.py

def test_read_item_handlers(client: TestClient, normal_user_token_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/item-handlers/", headers=normal_user_token_headers)
    assert response.status_code == 200
    content = response.json()
    assert isinstance(content, list)
```

## 常见问题

### 数据库表不存在

**问题**：运行测试时出现`sqlite3.OperationalError: no such table`错误

**解决方案**：确保在`conftest.py`中正确导入了所有模型，并启用了表创建

```python
# conftest.py
from sqlmodel import SQLModel
SQLModel.metadata.create_all(engine)
```

### 认证失败

**问题**：API测试中出现401 Unauthorized错误

**解决方案**：使用正确的认证令牌

```python
# 使用正常用户令牌
headers = normal_user_token_headers

# 使用超级用户令牌
headers = superuser_token_headers
```

### 测试数据冲突

**问题**：测试之间数据冲突

**解决方案**：确保测试使用独立的测试数据，避免硬编码值

```python
# 使用随机数据
name = random_lower_string()
email = random_email()
```

## 结论

良好的测试是保证代码质量和功能正确性的重要手段。遵循本指南，您可以有效地编写、运行和维护项目的测试。如果有任何问题，请参考现有测试代码或咨询团队成员。

---

*最后更新：2026年3月4日*