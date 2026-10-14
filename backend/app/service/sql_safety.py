"""Shared validation and result bounds for the two read-only SQL entry points."""
import re
import sqlglot
from sqlglot import exp
from service.database_catalog import ALLOWED_TABLES

# Only ordinary, side-effect-free analytic functions are available to either
# SQL endpoint. A SELECT containing pg_read_file/dblink/etc. is not read-only
# from the user's point of view, even inside a read-only transaction.
SAFE_FUNCTIONS = frozenset({
    "COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "ABS", "CEIL", "FLOOR",
    "COALESCE", "NULLIF", "LOWER", "UPPER", "LENGTH", "TRIM", "LTRIM", "RTRIM",
    "SUBSTRING", "CONCAT", "CONCAT_WS", "REPLACE", "CAST", "TRY_CAST",
    "TIMESTAMP_TRUNC", "DATE_TRUNC", "EXTRACT", "TIME_TO_STR", "DATE", "TS_OR_DS_TO_DATE",
    "CURRENT_DATE", "CURRENT_TIMESTAMP", "ROW_NUMBER", "RANK", "DENSE_RANK",
    "CASE", "IF", "EXISTS", "POWER", "SQRT", "MOD", "STDDEV", "STDDEV_POP", "STDDEV_SAMP",
    "VARIANCE", "VAR_POP", "VAR_SAMP", "BOOL_AND", "BOOL_OR", "STRING_AGG", "GROUP_CONCAT",
})
SAFE_TYPES = frozenset({"CHAR", "VARCHAR", "TEXT", "BOOLEAN", "TINYINT", "SMALLINT", "INT", "BIGINT",
                        "DECIMAL", "FLOAT", "DOUBLE", "DATE", "TIME", "TIMESTAMP", "TIMESTAMPTZ", "INTERVAL"})


def validate_select(sql: str, *, qualify_tables: bool = False) -> str:
    """Return a single SELECT statement, or reject write/multiple statements.

    Database read-only transactions provide the final write barrier. Masking SQL
    literals prevents ordinary values and names such as updated_at being rejected.
    """
    sql = sql.strip()
    if not sql:
        raise ValueError("SQL 语句为空")
    masked = re.sub(
        r"\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*|)\$.*?\$(?P=tag)\$|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"",
        "''", sql, flags=re.DOTALL,
    )
    if "--" in masked or "/*" in masked or "*/" in masked:
        raise ValueError("SQL 中不允许注释")
    if not re.match(r"^SELECT\b", masked, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed")
    if ";" in masked.rstrip(";") or masked.endswith(";;"):
        raise ValueError("不允许多条 SQL 语句")
    forbidden = re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|INTO|COPY|CALL|EXECUTE)\b",
        masked, re.IGNORECASE,
    )
    if forbidden:
        raise ValueError(f"Query contains forbidden keyword: {forbidden.group(1)}")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise ValueError("SQL 语法无法安全解析") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ValueError("仅支持单条 SELECT 查询")
    tree = statements[0]
    if any(isinstance(node, (exp.With, exp.CTE, exp.Into, exp.Lock, exp.Command)) for node in tree.walk()):
        raise ValueError("仅支持无锁定、无临时定义的只读 SELECT 查询")
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or table.catalog:
            raise ValueError("不允许表函数或跨数据库查询")
        name = table.name if table.this.args.get("quoted") else table.name.lower()
        schema = table.args.get("db")
        schema_name = (schema.name if schema.args.get("quoted") else schema.name.lower()) if isinstance(schema, exp.Identifier) else ""
        if name not in ALLOWED_TABLES or schema_name not in {"", "public"}:
            raise ValueError("SQL 包含未开放的数据表或系统表")
        if qualify_tables:
            table.set("db", exp.to_identifier("public"))
    for node in tree.walk():
        if isinstance(node, exp.Func):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
            if name not in SAFE_FUNCTIONS or isinstance(node.parent, exp.Dot):
                raise ValueError("SQL 包含未开放的函数")
        if isinstance(node, exp.DataType) and getattr(node.this, "name", str(node.this)) not in SAFE_TYPES:
            raise ValueError("SQL 包含未开放的数据类型")
        if isinstance(node, (exp.ObjectIdentifier, exp.UDTF)):
            raise ValueError("SQL 包含未开放的表函数或对象标识转换")
    # Execute the parsed expression itself, so validation and the SQL sent to
    # PostgreSQL cannot disagree about parser-sensitive syntax.
    return tree.sql(dialect="postgres")


def bounded_select(sql: str, *, qualify_tables: bool = False) -> str:
    # An outer LIMIT also bounds queries that already contain LIMIT ALL, a large
    # LIMIT, or a LIMIT only inside a subquery.
    return f"SELECT * FROM ({validate_select(sql, qualify_tables=qualify_tables)}) AS readonly_result LIMIT :_result_limit"


def read_only_connection(engine):
    connection = engine.connect()
    if engine.dialect.name == "postgresql":
        connection = connection.execution_options(postgresql_readonly=True)
        try:
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10000'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3000'")
            connection.exec_driver_sql("SET LOCAL search_path = pg_catalog, public, pg_temp")
        except Exception:
            connection.close()
            raise
    return connection
