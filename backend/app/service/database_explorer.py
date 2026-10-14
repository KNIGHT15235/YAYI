
"""数据库探索服务 - 仅支持 PostgreSQL"""
from typing import List, Dict, Any, Optional
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
import logging
from service.sql_safety import bounded_select, read_only_connection
from service.database_catalog import ALLOWED_TABLES, require_table, catalog_payload

logger = logging.getLogger(__name__)


class DatabaseExplorer:
    """数据库探索器 - 提供只读查询功能"""

    def __init__(self, db: Session):
        self.db = db

    def get_tables(self) -> List[Dict[str, Any]]:
        """只列出已发布的业务数据表，不暴露账户、记忆或研究会话表。"""
        query = text("""
            SELECT
                table_name,
                pg_size_pretty(pg_total_relation_size('public.' || quote_ident(table_name))) as size,
                (SELECT count(*) FROM information_schema.columns
                 WHERE table_name = t.table_name AND table_schema = 'public') as column_count
            FROM information_schema.tables t
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            AND table_name IN :allowed_tables
            ORDER BY table_name
        """)
        query = query.bindparams(bindparam("allowed_tables", expanding=True))
        result = self.db.execute(query, {"allowed_tables": sorted(ALLOWED_TABLES)})
        tables = []
        for row in result:
            # 获取行数（单独查询以避免复杂嵌套）
            require_table(row.table_name)
            count_query = text(f'SELECT count(*) FROM public."{row.table_name}"')
            try:
                count_result = self.db.execute(count_query)
                row_count = count_result.scalar()
            except Exception:
                self.db.rollback()
                raise ValueError("无法读取已发布数据表的行数")

            tables.append({
                "name": row.table_name,
                "size": row.size,
                "column_count": row.column_count,
                "row_count": row_count,
            })
        return tables

    def get_catalog(self) -> Dict[str, Any]:
        return catalog_payload(table["name"] for table in self.get_tables())

    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """获取表结构"""
        # 验证表名安全性
        require_table(table_name)

        # 获取列信息
        columns_query = text("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            ORDER BY ordinal_position
        """)
        columns_result = self.db.execute(columns_query, {"table_name": table_name})
        columns = []
        for row in columns_result:
            columns.append({
                "name": row.column_name,
                "type": row.data_type,
                "max_length": row.character_maximum_length,
                "nullable": row.is_nullable == "YES",
                "default": row.column_default,
            })

        # 获取主键信息
        pk_query = text("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = CAST(:table_name AS regclass) AND i.indisprimary
        """)
        try:
            pk_result = self.db.execute(pk_query, {"table_name": "public." + table_name})
            primary_keys = [row.attname for row in pk_result]
        except Exception:
            self.db.rollback()
            primary_keys = []

        # 获取索引信息
        idx_query = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = :table_name AND schemaname = 'public'
        """)
        try:
            idx_result = self.db.execute(idx_query, {"table_name": table_name})
            indexes = []
            for row in idx_result:
                indexes.append({
                    "name": row.indexname,
                    "definition": row.indexdef,
                })
        except Exception:
            self.db.rollback()
            indexes = []

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_keys": primary_keys,
            "indexes": indexes,
        }

    def get_table_data(
        self,
        table_name: str,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_dir: str = "asc"
    ) -> Dict[str, Any]:
        """获取表数据（分页）"""
        # 验证表名安全性
        require_table(table_name)
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        # 验证排序方向
        order_dir = order_dir.lower()
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        # 获取总行数
        count_query = text(f'SELECT count(*) FROM public."{table_name}"')
        total = self.db.execute(count_query).scalar()

        # 构建查询（使用安全的参数化）
        if order_by and self._is_valid_identifier(order_by):
            data_query = text(f'SELECT * FROM public."{table_name}" ORDER BY "{order_by}" {order_dir} LIMIT :limit OFFSET :offset')
        else:
            data_query = text(f'SELECT * FROM public."{table_name}" LIMIT :limit OFFSET :offset')

        result = self.db.execute(data_query, {"limit": limit, "offset": offset})

        # 获取列名
        columns = list(result.keys())

        # 获取数据
        rows = []
        for row in result:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                # 处理特殊类型
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                elif isinstance(value, bytes):
                    value = f"<binary {len(value)} bytes>"
                row_dict[col] = value
            rows.append(row_dict)

        return {
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def execute_query(self, sql: str, limit: int = 100) -> Dict[str, Any]:
        """执行只读 SQL 查询"""
        sql = bounded_select(sql, qualify_tables=self.db.get_bind().dialect.name == "postgresql")
        limit = max(1, min(limit, 1000))

        try:
            # Independent connection keeps a user's SELECT in a read-only
            # transaction without changing the API session used by authentication.
            with read_only_connection(self.db.get_bind()) as conn:
                result = conn.execute(text(sql), {"_result_limit": limit})
                columns = list(result.keys())
                result_rows = result.fetchall()

            rows = []
            for row in result_rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    value = row[i]
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    elif isinstance(value, bytes):
                        value = f"<binary {len(value)} bytes>"
                    row_dict[col] = value
                rows.append(row_dict)

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
        except Exception as e:
            self.db.rollback()
            logger.warning("Published dataset query failed (%s)", type(e).__name__)
            raise ValueError("查询执行失败，请检查已开放表的字段和 SQL 语法") from None

    def _is_valid_identifier(self, name: str) -> bool:
        """验证标识符是否安全"""
        if not name:
            return False
        # 只允许字母、数字、下划线
        import re
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))
