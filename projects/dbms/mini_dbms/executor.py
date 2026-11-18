"""Schema validation and SQL execution over append-only table files."""
from pathlib import Path
from itertools import chain
from .parser import parse
from .schema import SCHEMAS
from .storage import TableFile

class IdempotencyConflict(ValueError): pass

class Database:
    def __init__(self,data_dir,tree_max_keys=31):
        self.data_dir=Path(data_dir); self.tables={name:TableFile(self.data_dir,name,schema,tree_max_keys) for name,schema in SCHEMAS.items()}
    def execute(self,sql,params=()):
        statement=parse(sql,params)
        if statement.table not in SCHEMAS: raise ValueError(f"Unknown table: {statement.table}")
        schema=SCHEMAS[statement.table]; table=self.tables[statement.table]
        if statement.kind=="insert":
            if len(set(statement.columns))!=len(statement.columns): raise ValueError("Duplicate column")
            if set(statement.columns)!=set(schema): raise ValueError(f"INSERT must provide exactly these columns: {', '.join(schema)}")
            values=dict(zip(statement.columns,statement.values)); self._validate_values(schema,values)
            return {"insertedId":table.append(values)}
        columns=("id",*schema.keys()) if statement.columns==("*",) else statement.columns
        if statement.columns!=("*",):
            if len(set(columns))!=len(columns): raise ValueError("Duplicate column")
            unknown=set(columns)-(set(schema)|{"id"})
            if unknown: raise ValueError(f"Unknown column: {sorted(unknown)[0]}")
        if statement.where is not None:
            column,value=statement.where
            if column not in schema and column!="id": raise ValueError(f"Unknown column: {column}")
            if column=="id" and (not isinstance(value,int) or isinstance(value,bool)): raise ValueError("id must be INTEGER")
            if column in schema: self._validate_values({column:schema[column]},{column:value})
        return {"rows":table.select(columns,statement.where)}
    def execute_insert_once(self,sql,params=(),key_column=None):
        """Atomically find or append an INSERT by a permanent unique key."""
        statement=parse(sql,params)
        if statement.kind!="insert": raise ValueError("insert-once supports INSERT only")
        if statement.table not in SCHEMAS: raise ValueError(f"Unknown table: {statement.table}")
        schema=SCHEMAS[statement.table]; table=self.tables[statement.table]
        if len(set(statement.columns))!=len(statement.columns) or set(statement.columns)!=set(schema):
            raise ValueError("INSERT must provide exactly these columns")
        if key_column not in schema or key_column not in statement.columns:
            raise ValueError("keyColumn must name an inserted table column")
        values=dict(zip(statement.columns,statement.values)); self._validate_values(schema,values)
        with table.lock:
            table._ensure_ready()
            for row,_ in table.rows:
                if row[key_column]!=values[key_column]: continue
                if all(row[column]==values[column] for column in schema):
                    return {"insertedId":row["id"],"created":False}
                raise IdempotencyConflict("idempotency key already exists with different row contents")
            return {"insertedId":table.append(values),"created":True}
    def execute_many(self,sql,parameter_sets):
        parameter_sets=iter(parameter_sets)
        try: first_params=next(parameter_sets)
        except StopIteration: return {"insertedIds":[],"count":0}
        statement=parse(sql,first_params)
        if statement.kind!="insert": raise ValueError("execute_many supports INSERT only")
        if statement.table not in SCHEMAS: raise ValueError(f"Unknown table: {statement.table}")
        schema=SCHEMAS[statement.table]
        if len(set(statement.columns))!=len(statement.columns) or set(statement.columns)!=set(schema): raise ValueError("INSERT columns must match table schema exactly")
        rows=[]
        for params in chain((first_params,),parameter_sets):
            if len(params)!=len(statement.values): raise ValueError("parameter count mismatch")
            mapped=dict(zip(statement.columns,params)); self._validate_values(schema,mapped); rows.append(mapped)
        ids=self.tables[statement.table].append_many(rows)
        return {"insertedIds":ids,"count":len(ids)}
    @staticmethod
    def _validate_values(schema,values):
        for name,kind in schema.items():
            value=values[name]; valid=isinstance(value,str) if kind=="TEXT" else isinstance(value,int) and not isinstance(value,bool)
            if not valid: raise ValueError(f"{name} must be {kind}")
