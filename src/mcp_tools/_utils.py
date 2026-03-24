import csv, json
import re
from datetime import datetime
from pathlib import Path
import re
from datetime import datetime
from typing import List, Sequence
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.callbacks import Callbacks
from langchain_ollama import ChatOllama

def remove_prefix_timestamp(s: str) -> str:
    m = re.match(r'^(\d{8})(.*)', s)
    if not m:
        return s

    date_part, rest = m.groups()

    try:
        datetime.strptime(date_part, "%Y%m%d")
        return rest
    except ValueError:
        return s

def infer_sql_type(values):
    """
    Infer a SQL type from a list of string values.
    Empty values are ignored for type inference.
    """
    non_empty = [v.strip() for v in values if v is not None and str(v).strip() != ""]

    if not non_empty:
        return "TEXT"

    def is_bool(v):
        return v.lower() in {"true", "false", "yes", "no", "y", "n", "0", "1"}

    def is_int(v):
        return re.fullmatch(r"[+-]?\d+", v) is not None

    def is_float(v):
        return re.fullmatch(r"[+-]?(\d+\.\d+|\d+|\.\d+)", v) is not None

    def is_date(v):
        date_formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%m/%d/%Y",
            "%d/%m/%Y",
        ]
        for fmt in date_formats:
            try:
                datetime.strptime(v, fmt)
                return True
            except ValueError:
                pass
        return False

    def is_timestamp(v):
        ts_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        for fmt in ts_formats:
            try:
                datetime.strptime(v, fmt)
                return True
            except ValueError:
                pass
        return False

    if all(is_bool(v) for v in non_empty):
        return "BOOLEAN"

    if all(is_int(v) for v in non_empty):
        ints = [int(v) for v in non_empty]
        if all(-(2**31) <= x <= 2**31 - 1 for x in ints):
            return "INTEGER"
        return "BIGINT"

    # float check after int check
    if all(is_float(v) for v in non_empty):
        return "REAL"

    if all(is_timestamp(v) for v in non_empty):
        return "TIMESTAMP"

    if all(is_date(v) for v in non_empty):
        return "DATE"

    return "TEXT"


def sanitize_column_name(name):
    """
    Make a CSV header safer for SQL usage.
    """
    name = name.strip()
    name = re.sub(r"\W+", "_", name)
    if re.match(r"^\d", name):
        name = "_" + name
    return name.lower()


def infer_create_table_from_csv(csv_path, table_name=None, sample_size=1000):
    """
    Infer a SQL CREATE TABLE statement from a CSV file.

    Args:
        csv_path (str): Path to the CSV file.
        table_name (str|None): Name of the SQL table. Defaults to CSV filename stem.
        sample_size (int): Number of rows to sample for type inference.

    Returns:
        str: CREATE TABLE SQL statement.
    """
    csv_path = Path(csv_path)

    if table_name is None:
        table_name = sanitize_column_name(csv_path.stem)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV appears to have no header row.")

        original_columns = reader.fieldnames
        sql_columns = [sanitize_column_name(col) for col in original_columns]

        samples = {col: [] for col in original_columns}

        for i, row in enumerate(reader):
            if i >= sample_size:
                break
            for col in original_columns:
                samples[col].append(row.get(col, ""))

    column_defs = []
    for original_col, sql_col in zip(original_columns, sql_columns):
        sql_type = infer_sql_type(samples[original_col])
        column_defs.append(f'    "{sql_col}" {sql_type}')

    create_stmt = f'CREATE TABLE "{table_name}" (\n' + ",\n".join(column_defs) + "\n);"
    return create_stmt

def extract_json(text: str):
    """
    Extract and return the first valid JSON object or array from a string.
    Raises ValueError if no valid JSON is found.
    """

    # Fast path: already valid JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start_chars = ['{', '[']

    for start_char in start_chars:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue

        stack = []
        for i in range(start_idx, len(text)):
            char = text[i]

            if char in '{[':
                stack.append(char)

            elif char in '}]':
                if not stack:
                    break
                stack.pop()

                if not stack:
                    candidate = text[start_idx:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError("No valid JSON found in input")

class JSONFieldCompressor(BaseDocumentCompressor):
    llm: ChatOllama = None

    def model_post_init(self, compression_model , __context):
        if self.llm is None:
            self.llm = ChatOllama(
                model=compression_model,
                base_url="http://localhost:11434",
            )

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> List[Document]:
        compressed = []
        for doc in documents:
            result = self.llm.invoke(
                f"""{query}

Return only a compact JSON object with the relevant fields, no preamble or explanation.

Input:
{doc.page_content}"""
            )
            compressed.append(Document(page_content=result.content))
        return compressed