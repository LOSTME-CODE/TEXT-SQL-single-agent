"""
SQL Agent Frontend — ChatGPT-style Gradio UI
=============================================
Run:  python csvagent6.py
Requires:
    pip install gradio langchain-ollama langchain-core pyodbc pandas
"""

import re
import io
import datetime
import pandas as pd
import gradio as gr

# ── LangChain / Ollama ────────────────────────────────────────────────────────
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


#  GLOBAL STATE

_conn      = None
_csv_df    = None
_csv_name  = ""
_llm       = None
_mode      = "db"
_history   = []

def get_llm(model_name: str = "llama3.2:3b"):
    global _llm
    if _llm is None:
        _llm = OllamaLLM(model=model_name)
    return _llm


#  DB CONNECTION

def connect_db(server, database, use_windows_auth, username, password):
    global _conn, _mode, _history
    try:
        import pyodbc
        if use_windows_auth:
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};DATABASE={database};Trusted_Connection=yes;"
            )
        else:
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};DATABASE={database};UID={username};PWD={password};"
            )
        _conn = pyodbc.connect(conn_str)
        _mode = "db"
        _history = []  # ← reset history on new DB connection
        cursor = _conn.cursor()
        cursor.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
        )
        tables = [row[0] for row in cursor.fetchall()]
        table_list = ", ".join(tables) if tables else "(none found)"
        return f"✅ Connected to **{database}**\n\nTables: `{table_list}`", format_history_md(), "", "", "", ""
    except Exception as e:
        _conn = None
        return f" Connection failed:\n```\n{e}\n```", format_history_md(), "", "", "", ""

# ═══════════════════════════════════════════════════════════════════════════════
#  CSV UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════
def load_csv(file_obj):
    global _csv_df, _csv_name, _mode, _history
    if file_obj is None:
        return "No file uploaded.", format_history_md(), "", "", "", ""
    try:
        _csv_df   = pd.read_csv(file_obj.name)
        _csv_name = re.sub(r"[^a-zA-Z0-9_]", "_",
                           file_obj.name.split("/")[-1].replace(".csv", ""))
        _mode     = "csv"
        _history  = []  # ← reset history on new CSV upload
        preview   = _csv_df.head(5).to_string(index=False)
        schema    = str(_csv_df.dtypes)
        return (
            f"✅ Loaded **{_csv_name}** — {len(_csv_df)} rows × {len(_csv_df.columns)} cols\n\n"
            f"**Schema:**\n```\n{schema}\n```\n\n"
            f"**Preview (first 5 rows):**\n```\n{preview}\n```"
        ), format_history_md(), "", "", "", ""
    except Exception as e:
        return f" Failed to load CSV:\n```\n{e}\n```", format_history_md(), "", "", "", ""

# ═══════════════════════════════════════════════════════════════════════════════
#  SQL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def clean_sql(raw: str) -> str:
    raw = re.sub(r"```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("```", "")
    sql_keywords = ("SELECT", "WITH", "(")
    lines        = raw.strip().splitlines()
    sql_start    = 0
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(sql_keywords):
            sql_start = i
            break
    cleaned = " ".join(lines[sql_start:]).strip()
    if ";" in cleaned:
        cleaned = cleaned[: cleaned.index(";")]
    return cleaned.strip()


def build_sql_prompt(is_csv: bool, db_type: str = "mssql") -> ChatPromptTemplate:
    if is_csv:
        dialect_note = (
            "- This is SQLite (pandas in-memory). Use LIMIT, not TOP.\n"
            "- Table name: {table_name}\n"
        )
    else:
        if db_type == "mssql":
            dialect_note = (
                "- This is Microsoft SQL Server. NEVER use LIMIT. Use TOP instead.\n"
                "  Example: SELECT TOP 1 ename, salary FROM employ ORDER BY salary DESC\n"
            )
        else:
            dialect_note = "- Use standard SQL.\n"

    return ChatPromptTemplate.from_template(
        "You are a SQL expert. Convert the user question into a valid SQL SELECT query.\n\n"
        "Schema (column names and types):\n{schema}\n\n"
        "Rules:\n"
        "- Return ONLY the SQL query. No explanation. No markdown. No backticks.\n"
        "- Use ONLY columns that exist in the schema above.\n"
        "- Always use SELECT (never INSERT, UPDATE, DELETE, DROP).\n"
        "- End the query with a semicolon.\n"
        f"{dialect_note}"
        "- For string comparisons use: WHERE LOWER(col) = LOWER('value')\n"
        "- When using COUNT(*) with other columns, use GROUP BY.\n"
        "- NEVER use subqueries.\n\n"
        "Question: {question}\n\n"
        "Write only the SQL query:"
    )


#  HISTORY HELPERS

def format_history_md() -> str:
    if not _history:
        return "_No queries yet in this session._"
    lines = []
    for i, entry in enumerate(_history, 1):
        lines.append(
            f"**{i}. [{entry['time']}]** {entry['question']}\n\n"
            f"> {entry['answer']}"
        )
    return "\n\n---\n\n".join(lines)

#  PIPELINE

def run_query(question: str, model_name: str, db_type: str):
    global _conn, _csv_df, _csv_name, _mode, _history

    if not question.strip():
        return "", "", " Please enter a question.", format_history_md()

    if _mode == "db" and _conn is None:
        return "", "", " Not connected to a database. Use the Connection tab above.", format_history_md()
    if _mode == "csv" and _csv_df is None:
        return "", "", " No CSV loaded. Upload a CSV file first.", format_history_md()

    try:
        llm = get_llm(model_name)

        if _mode == "csv":
            schema = str(_csv_df.dtypes)
            table  = _csv_name
        else:
            cursor = _conn.cursor()
            cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION"
            )
            rows = cursor.fetchall()
            schema_lines = [f"{r[0]}.{r[1]} ({r[2]})" for r in rows]
            schema = "\n".join(schema_lines)
            table  = ""

        is_csv    = (_mode == "csv")
        sql_tmpl  = build_sql_prompt(is_csv, db_type)
        sql_chain = sql_tmpl | llm | StrOutputParser()

        invoke_kwargs = {"schema": schema, "question": question}
        if is_csv:
            invoke_kwargs["table_name"] = table

        raw_sql   = sql_chain.invoke(invoke_kwargs)
        sql_query = clean_sql(raw_sql)

        if _mode == "csv":
            import sqlite3
            mem_conn = sqlite3.connect(":memory:")
            _csv_df.to_sql(table, mem_conn, index=False, if_exists="replace")
            try:
                result_df = pd.read_sql_query(sql_query, mem_conn)
                result    = [tuple(r) for r in result_df.values.tolist()]
            except Exception as e:
                result = f"SQL_ERROR: {e}"
            finally:
                mem_conn.close()
        else:
            stripped = sql_query.strip().upper()
            if not stripped.startswith("SELECT"):
                result = "ERROR: Only SELECT queries are allowed."
            else:
                try:
                    import pyodbc
                    cursor = _conn.cursor()
                    cursor.execute(sql_query)
                    result = [tuple(row) for row in cursor.fetchall()]
                except Exception as e:
                    result = f"SQL_ERROR: {e}"

        if isinstance(result, str) and result.startswith(("ERROR", "SQL_ERROR")):
            nlp_answer = f" Could not retrieve data.\n\nReason: {result}"
        elif result == []:
            nlp_answer = "No matching records were found."
        else:
            answer_prompt = ChatPromptTemplate.from_template(
                "You are a helpful data assistant. A user asked a question.\n"
                "The database returned the SQL result below.\n\n"
                "Question   : {question}\n"
                "SQL Result : {result}\n\n"
                "Write a clear, natural language answer — concise (1-3 sentences).\n"
                "If the result is empty, say the information was not found."
            )
            answer_chain = answer_prompt | llm | StrOutputParser()
            nlp_answer   = answer_chain.invoke({
                "question": question,
                "result"  : str(result)
            }).strip()

        if isinstance(result, list) and result:
            try:
                result_md = pd.DataFrame(result).to_string(index=False)
            except Exception:
                result_md = str(result)
        else:
            result_md = str(result)

        _history.append({
            "time":     datetime.datetime.now().strftime("%H:%M:%S"),
            "question": question,
            "sql":      sql_query,
            "answer":   nlp_answer,
        })

        return sql_query, result_md, nlp_answer, format_history_md()

    except Exception as e:
        return "", "", f" Pipeline error:\n```\n{e}\n```", format_history_md()


# ═══════════════════════════════════════════════════════════════════════════════
#  ChatGPT-STYLE DARK UI CSS
# ═══════════════════════════════════════════════════════════════════════════════
CSS = """
/* ── Import font ─────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Söhne:wght@400;500;600&display=swap');

/* ── Reset & Root ────────────────────────────────────────────────────────── */
* { box-sizing: border-box; margin: 0; padding: 0; }

body, .gradio-container {
    background: #212121 !important;
    color: #ececec !important;
    font-family: 'Söhne', ui-sans-serif, system-ui, sans-serif !important;
    min-height: 100vh;
}

footer { display: none !important; }

/* ── Hide default gradio header padding ──────────────────────────────────── */
.gradio-container > .main { padding: 0 !important; }

/* ── LAYOUT: sidebar + main ──────────────────────────────────────────────── */
#outer-layout {
    display: flex;
    height: 100vh;
    overflow: hidden;
}

/* ── SIDEBAR ─────────────────────────────────────────────────────────────── */
#sidebar {
    width: 300px;
    min-width: 300px;
    background: #171717;
    border-right: 1px solid #2a2a2a;
    display: flex;
    flex-direction: column;
    padding: 28px 16px 20px 16px;
    overflow-y: auto;
    min-height: 100vh;
    height: 100%;
}

#sidebar-logo {
    font-size: 2rem;
    font-weight: 700;
    color: #ececec;
    padding: 0 8px 6px 8px;
    letter-spacing: -0.02em;
    line-height: 1.2;
}
#sidebar-logo span { color: #10a37f; }

#sidebar-welcome {
    font-size: 0.88rem;
    color: #8e8ea0;
    padding: 0 8px 22px 8px;
    line-height: 1.55;
    border-bottom: 1px solid #2a2a2a;
    margin-bottom: 20px;
}

/* History toggle button */
#history-toggle-btn {
    background: transparent !important;
    border: 1px solid #2f2f2f !important;
    color: #ececec !important;
    border-radius: 8px !important;
    padding: 12px 16px !important;
    font-size: 1rem !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    width: 100% !important;
    text-align: left !important;
    margin-bottom: 14px !important;
    transition: background 0.15s !important;
}
#history-toggle-btn:hover { background: #2a2a2a !important; }

/* History panel inside sidebar */
#sidebar-history {
    flex: 1;
    overflow-y: auto;
    padding-right: 4px;
}
#sidebar-history .prose,
#sidebar-history p,
#sidebar-history h1,
#sidebar-history h2,
#sidebar-history h3,
#sidebar-history span,
#sidebar-history div {
    color: #ececec !important;
    font-size: 0.85rem !important;
    line-height: 1.65 !important;
}
#sidebar-history::-webkit-scrollbar { width: 4px; }
#sidebar-history::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 4px; }

/* ── MAIN AREA ───────────────────────────────────────────────────────────── */
#main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #212121;
}

/* ── TOP BAR (connection) ────────────────────────────────────────────────── */
#top-bar {
    background: #171717;
    border-bottom: 1px solid #2a2a2a;
    padding: 10px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    min-height: 60px;
    flex-shrink: 0;
}

#top-bar .label-wrap,
#top-bar label,
#top-bar .block-label,
#top-bar span {
    color: #ececec !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
}

/* Tabs inside top-bar */
#conn-tabs .tab-nav {
    background: transparent !important;
    border-bottom: 1px solid #2a2a2a !important;
    padding: 0 !important;
}
#conn-tabs .tab-nav button {
    color: #8e8ea0 !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 8px 20px !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    transition: all 0.15s !important;
    letter-spacing: 0.01em !important;
}
#conn-tabs .tab-nav button.selected {
    color: #ececec !important;
    border-bottom: 2px solid #10a37f !important;
}
#conn-tabs .tabitem {
    padding: 12px 0 4px 0 !important;
    background: transparent !important;
}

/* Larger dropdown labels */
#top-bar .block-label,
#top-bar label {
    color: #ececec !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
}
#top-bar select,
#top-bar .wrap-inner,
#top-bar input {
    font-size: 0.95rem !important;
    color: #ececec !important;
}

/* ── BODY (chat answer area) ─────────────────────────────────────────────── */
#body-area {
    flex: 1;
    overflow-y: auto;
    padding: 32px 15% 20px 15%;
    display: flex;
    flex-direction: column;
    gap: 16px;
}
#body-area::-webkit-scrollbar { width: 6px; }
#body-area::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 4px; }

/* Answer card */
#answer-card {
    background: #2a2a2a;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 20px 24px;
}

/* SQL + Result cards side by side */
#sql-result-row {
    display: flex;
    gap: 12px;
}

.result-card {
    flex: 1;
    background: #1a1a1a;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 14px 18px;
}

/* All output textboxes */
#answer-out textarea,
#sql-out textarea,
#result-out textarea {
    background: transparent !important;
    border: none !important;
    color: #ececec !important;
    font-size: 0.9rem !important;
    resize: none !important;
    box-shadow: none !important;
}
#answer-out .block-label,
#sql-out .block-label,
#result-out .block-label {
    color: #8e8ea0 !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    margin-bottom: 6px !important;
}

/* ── BOTTOM INPUT BAR ────────────────────────────────────────────────────── */
#bottom-bar {
    background: #212121;
    padding: 16px 15% 24px 15%;
    flex-shrink: 0;
    border-top: 1px solid #2a2a2a;
}

#question-row {
    display: flex;
    align-items: flex-end;
    gap: 10px;
    background: #2f2f2f;
    border: 1px solid #3f3f3f;
    border-radius: 14px;
    padding: 10px 14px;
    transition: border-color 0.2s;
}
#question-row:focus-within { border-color: #10a37f; }

#question-input textarea {
    background: transparent !important;
    border: none !important;
    color: #ececec !important;
    font-size: 0.95rem !important;
    resize: none !important;
    box-shadow: none !important;
    min-height: 24px !important;
    max-height: 120px !important;
    flex: 1;
}
#question-input textarea::placeholder { color: #6e6e80 !important; }
#question-input .block-label { display: none !important; }
#question-input { flex: 1; }

/* Send button */
#ask-btn {
    background: #10a37f !important;
    border: none !important;
    color: white !important;
    border-radius: 8px !important;
    padding: 8px 18px !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    flex-shrink: 0 !important;
    transition: background 0.15s !important;
    min-width: 70px !important;
    align-self: flex-end !important;
}
#ask-btn:hover { background: #0e9070 !important; }

/* ── Settings row (model + dialect) ─────────────────────────────────────── */
#settings-row {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
    align-items: center;
}
#settings-row .block-label,
#settings-row label,
#settings-row span { color: #8e8ea0 !important; font-size: 0.78rem !important; }
#settings-row select,
#settings-row .wrap-inner {
    background: #2a2a2a !important;
    border: 1px solid #3a3a3a !important;
    color: #ececec !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
}

/* ── Global input/textbox overrides ──────────────────────────────────────── */
input[type="text"],
input[type="password"],
textarea {
    background: #2a2a2a !important;
    border: 1px solid #3a3a3a !important;
    color: #ececec !important;
    border-radius: 8px !important;
}
input[type="text"]::placeholder,
input[type="password"]::placeholder,
textarea::placeholder { color: #6e6e80 !important; }

label, .block-label, span, p, h1, h2, h3, h4 { color: #ececec !important; }

/* Connect / Load buttons */
button.primary { background: #10a37f !important; border-color: #10a37f !important; color: white !important; border-radius: 8px !important; }
button.secondary { background: #2a2a2a !important; border-color: #3a3a3a !important; color: #ececec !important; border-radius: 8px !important; }

/* Checkbox */
input[type="checkbox"] { accent-color: #10a37f !important; }

/* File upload */
.file-preview { background: #1a1a1a !important; border-color: #2f2f2f !important; color: #ececec !important; }

/* Status markdown */
.status-box .prose * { color: #ececec !important; font-size: 0.85rem !important; }

/* Scrollbars global */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #3a3a3a; border-radius: 4px; }

/* Hint text under input */
#bottom-hint { text-align: center; color: #6e6e80 !important; font-size: 0.73rem !important; margin-top: 8px; }
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  BUILD UI
# ═══════════════════════════════════════════════════════════════════════════════
with gr.Blocks(title="Text-SQL Agent", css=CSS, theme=gr.themes.Base()) as demo:

    # ── OUTER LAYOUT: sidebar + main ─────────────────────────────────────────
    with gr.Row(elem_id="outer-layout"):

        # ════════════════════════════════════════════════════════════════
        #  SIDEBAR
        # ════════════════════════════════════════════════════════════════
        with gr.Column(elem_id="sidebar", scale=0):
            gr.HTML('''
                <div id="sidebar-logo">🤖 SQL <span>Agent</span></div>
                <div id="sidebar-welcome">
                    Ask questions in plain English.<br>
                    This bot converts natural language queries into SQL, executes them on the database, and responds with clear, human-readable answers.
                </div>
            ''')

            history_toggle_btn = gr.Button(
                " Query History",
                elem_id="history-toggle-btn",
                variant="secondary"
            )

            with gr.Column(elem_id="sidebar-history", visible=True) as sidebar_history_panel:
                history_md = gr.Markdown("_No queries yet._")

        # ════════════════════════════════════════════════════════════════
        #  MAIN AREA
        # ════════════════════════════════════════════════════════════════
        with gr.Column(elem_id="main-area", scale=1):

            # ── TOP BAR ──────────────────────────────────────────────────
            with gr.Row(elem_id="top-bar"):
                with gr.Column(scale=3, min_width=0):
                    with gr.Tabs(elem_id="conn-tabs"):

                        with gr.Tab(" Database"):
                            with gr.Row():
                                server_tb   = gr.Textbox(
                                    label="Server",
                                    placeholder=r"HOST\SQLEXPRESS",
                                    type="password",
                                    scale=2
                                )
                                database_tb = gr.Textbox(
                                    label="Database",
                                    placeholder="my_db",
                                    scale=1
                                )
                            win_auth_cb = gr.Checkbox(
                                label="Windows Authentication",
                                value=True
                            )
                            with gr.Row(visible=False) as cred_row:
                                username_tb = gr.Textbox(label="Username", scale=1)
                                password_tb = gr.Textbox(label="Password", type="password", scale=1)
                            with gr.Row():
                                connect_btn = gr.Button("Connect", variant="primary", scale=0)
                                db_status   = gr.Markdown(elem_classes=["status-box"], value="")

                            def toggle_creds(use_win):
                                return gr.update(visible=not use_win)
                            win_auth_cb.change(toggle_creds, win_auth_cb, cred_row)

                        with gr.Tab("📂 CSV"):
                            with gr.Row():
                                csv_file     = gr.File(label="Upload CSV", file_types=[".csv"], scale=2)
                                csv_load_btn = gr.Button("Load CSV", variant="primary", scale=0)
                                csv_status   = gr.Markdown(elem_classes=["status-box"], value="")

                # Model + dialect dropdowns in top-right corner of top bar
                with gr.Column(scale=1, min_width=180):
                    model_dd = gr.Dropdown(
                        choices=["llama3.2:3b", "llama3.2:1b","mistral"],
                        value="llama3.2:3b",
                        label="Model",
                    )
                    db_type_dd = gr.Dropdown(
                        choices=["mssql", "other"],
                        value="mssql",
                        label="Dialect",
                    )

            # ── BODY (answer area) ────────────────────────────────────────
            with gr.Column(elem_id="body-area"):
                with gr.Row():
                    with gr.Column(scale=1, elem_id="answer-card"):
                        answer_out = gr.Textbox(
                            label=" Answer",
                            lines=4,
                            interactive=False,
                            placeholder="Your answer will appear here...",
                            elem_id="answer-out"
                        )

                with gr.Row(elem_id="sql-result-row"):
                    with gr.Column(elem_classes=["result-card"]):
                        sql_out = gr.Textbox(
                            label=" Generated SQL",
                            lines=5,
                            interactive=False,
                            placeholder="SQL query will appear here...",
                            elem_id="sql-out"
                        )
                    with gr.Column(elem_classes=["result-card"]):
                        result_out = gr.Textbox(
                            label="Raw Result",
                            lines=5,
                            interactive=False,
                            placeholder="Raw SQL output will appear here...",
                            elem_id="result-out"
                        )

            # ── BOTTOM INPUT BAR ──────────────────────────────────────────
            with gr.Column(elem_id="bottom-bar"):
                with gr.Row(elem_id="question-row"):
                    question_tb = gr.Textbox(
                        label="",
                        placeholder="Ask anything about your data...",
                        lines=1,
                        max_lines=4,
                        elem_id="question-input",
                        show_label=False,
                        container=False
                    )
                    ask_btn = gr.Button("Send", variant="primary", elem_id="ask-btn", scale=0)

                gr.HTML('<div id="bottom-hint">Ollama must be running locally · <code>ollama serve</code></div>')

    # ── CONNECTION WIRING (placed here so all output components are defined) ────
    connect_btn.click(
        connect_db,
        inputs=[server_tb, database_tb, win_auth_cb, username_tb, password_tb],
        outputs=[db_status, history_md, sql_out, result_out, answer_out, question_tb]
    )
    csv_load_btn.click(
        load_csv,
        inputs=csv_file,
        outputs=[csv_status, history_md, sql_out, result_out, answer_out, question_tb]
    )

    # ── HISTORY TOGGLE LOGIC ──────────────────────────────────────────────────
    history_hidden = gr.State(False)

    def toggle_history(current_hidden):
        new_hidden = not current_hidden
        label   = " Query History" if new_hidden else " Hide History"
        content = format_history_md()
        return (
            gr.update(visible=not new_hidden),
            new_hidden,
            label,
            content
        )

    history_toggle_btn.click(
        fn=toggle_history,
        inputs=[history_hidden],
        outputs=[sidebar_history_panel, history_hidden, history_toggle_btn, history_md]
    )

    # ── ASK WIRING ────────────────────────────────────────────────────────────
    ask_btn.click(
        run_query,
        inputs=[question_tb, model_dd, db_type_dd],
        outputs=[sql_out, result_out, answer_out, history_md]
    )
    question_tb.submit(
        run_query,
        inputs=[question_tb, model_dd, db_type_dd],
        outputs=[sql_out, result_out, answer_out, history_md]
    )

# ─── Launch ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7872,
        share=False,
        inbrowser=True,
    )