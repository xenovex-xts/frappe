import re
import types
import typing

from pypika import JoinType, MySQLQuery, Order, PostgreSQLQuery, SQLLiteQuery, terms
from pypika.dialects import MySQLQueryBuilder, PostgreSQLQueryBuilder, SQLLiteQueryBuilder
from pypika.queries import QueryBuilder, Schema, Table
from pypika.terms import Function

from frappe.query_builder.terms import (
	ParameterizedValueWrapper,
	PostgresParameterizedValueWrapper,
	SQLiteParameterizedValueWrapper,
)
from frappe.utils import get_table_name

# less restrictive version of frappe.core.doctype.doctype.doctype.START_WITH_LETTERS_PATTERN
# to allow table names like __Auth
TABLE_NAME_PATTERN = re.compile(r"^[\w -]*$", flags=re.ASCII)


def _flatten(module):
	import inspect

	from frappe.types import _dict

	new_mod = _dict()
	for name, obj in inspect.getmembers(module, lambda x: not inspect.ismodule(x)):
		if not name.startswith("_"):
			new_mod[name] = obj
	return new_mod


class Base:
	terms = _flatten(terms)
	desc = Order.desc
	asc = Order.asc
	Schema = Schema
	Table = Table

	# Added dynamic type hints for engine attribute
	# which is to be assigned later.
	if typing.TYPE_CHECKING:
		from frappe.database.query import Engine

		engine: Engine

	@staticmethod
	def functions(name: str, *args, **kwargs) -> Function:
		return Function(name, *args, **kwargs)

	@staticmethod
	def DocType(table_name: str, *args, **kwargs) -> Table:
		Base.validate_doctype(table_name)
		table_name = get_table_name(table_name)
		return Table(table_name, *args, **kwargs)

	@classmethod
	def into(cls, table, *args, **kwargs) -> QueryBuilder:
		if isinstance(table, str):
			table = cls.DocType(table)
		return super().into(table, *args, **kwargs)

	@classmethod
	def update(cls, table, *args, **kwargs) -> QueryBuilder:
		if isinstance(table, str):
			table = cls.DocType(table)
		return super().update(table, *args, **kwargs)

	@staticmethod
	def validate_doctype(doctype) -> None:
		from frappe import _, throw

		if not TABLE_NAME_PATTERN.match(doctype):
			throw(_("Invalid DocType: {0}").format(doctype))


class MariaDB(Base, MySQLQuery):
	Field = terms.Field

	_BuilderClasss = MySQLQueryBuilder

	@classmethod
	def _builder(cls, *args, **kwargs) -> "MySQLQueryBuilder":
		return super()._builder(*args, wrapper_cls=ParameterizedValueWrapper, **kwargs)

	@classmethod
	def from_(cls, table, *args, **kwargs):
		if isinstance(table, str):
			table = cls.DocType(table)
		return super().from_(table, *args, **kwargs)


class PostgresQueryBuilder(PostgreSQLQueryBuilder):
	"""Frappe's PostgreSQL query builder.

	Adds portability shims so app code written with MariaDB semantics keeps
	working on PostgreSQL without per-call rewrites.
	"""

	def get_sql(self, *args, **kwargs) -> str:
		# PostgreSQL has no `UPDATE t JOIN t2 ON ... SET ...` form (that syntax
		# is MySQL/MariaDB only); it uses `UPDATE t SET ... FROM t2 WHERE ...`.
		# pypika renders the MySQL form for every dialect, so an update built
		# with .join() is invalid on PostgreSQL. Rewrite inner joins into the
		# FROM + WHERE form here. This only fires for update-with-join queries,
		# which would otherwise fail outright, so the blast radius is limited to
		# queries that are already broken on PostgreSQL.
		if self._update_table is not None and self._joins and self._is_rewritable_update_join():
			return self._update_join_get_sql(*args, **kwargs)
		return super().get_sql(*args, **kwargs)

	def _is_rewritable_update_join(self) -> bool:
		# Only inner joins map cleanly to the UPDATE ... FROM form (which has
		# inner-join semantics). Leave anything else to the default rendering.
		return all(getattr(join, "how", None) == JoinType.inner for join in self._joins)

	def _update_join_get_sql(self, *args, **kwargs) -> str:
		# Temporarily move each joined table into FROM and its ON criterion into
		# WHERE, render with the base builder, then restore state so get_sql
		# stays idempotent (it is re-entered for subqueries, repr, etc.).
		original_joins = self._joins
		original_from = self._from
		original_wheres = self._wheres
		try:
			self._from = [*self._from, *(join.item for join in original_joins)]
			for join in original_joins:
				criterion = getattr(join, "criterion", None)
				if criterion is not None:
					self._wheres = criterion if self._wheres is None else (self._wheres & criterion)
			self._joins = []
			return super().get_sql(*args, **kwargs)
		finally:
			self._joins = original_joins
			self._from = original_from
			self._wheres = original_wheres


class Postgres(Base, PostgreSQLQuery):
	field_translation = types.MappingProxyType({"table_name": "relname", "table_rows": "n_tup_ins"})
	schema_translation = types.MappingProxyType({"tables": "pg_stat_all_tables"})
	# TODO: Find a better way to do this
	# These are interdependent query changes that need fixing. These
	# translations happen in the same query. But there is no check to see if
	# the Fields are changed only when a particular `information_schema` schema
	# is used. Replacing them is not straightforward because the "from_"
	# function can not see the arguments passed to the "select" function as
	# they are two different objects. The quick fix used here is to replace the
	# Field names in the "Field" function.

	_BuilderClasss = PostgresQueryBuilder

	@classmethod
	def _builder(cls, *args, **kwargs) -> "PostgresQueryBuilder":
		return PostgresQueryBuilder(*args, wrapper_cls=PostgresParameterizedValueWrapper, **kwargs)
	@classmethod
	def Field(cls, field_name, *args, **kwargs):
		if field_name in cls.field_translation:
			field_name = cls.field_translation[field_name]
		return terms.Field(field_name, *args, **kwargs)

	@classmethod
	def from_(cls, table, *args, **kwargs):
		if isinstance(table, Table):
			if table._schema:
				if table._schema._name == "information_schema":
					table = cls.schema_translation.get(table._table_name) or table

		elif isinstance(table, str):
			table = cls.DocType(table)

		return super().from_(table, *args, **kwargs)


class SQLite(Base, SQLLiteQuery):
	Field = terms.Field

	_BuilderClasss = SQLLiteQueryBuilder

	@classmethod
	def _builder(cls, *args, **kwargs) -> "SQLLiteQueryBuilder":
		return super()._builder(*args, wrapper_cls=SQLiteParameterizedValueWrapper, **kwargs)

	@classmethod
	def from_(cls, table, *args, **kwargs):
		if isinstance(table, str):
			table = cls.DocType(table)
		return super().from_(table, *args, **kwargs)
