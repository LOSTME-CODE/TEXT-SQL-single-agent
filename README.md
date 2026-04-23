
## 📌 Table of Contents
- <a href="#overview">Overview</a>
- <a href="#Demo">Demo</a>
- <a href="#problem-statement">Problem Statement</a>
- <a href="#tools--technologies">Tools & Technologies</a>
- <a href="#Result">Result</a>
- <a href="#Deployment">Deployment</a>
- <a href="#future-work">Future Work</a>
- <a href="#Methodology">Methodology</a>


# **Text-SQL Single Agent**

Convert Natural Language Questions into SQL Queries and Get Instant Insights from Databases or CSV Files.


<h3><a class="anchor" id="Demo"></a>Demo</h3>



https://github.com/user-attachments/files/27019460/README.1.md


![App Screenshot](https://github.com/LOSTME-CODE/TEXT-SQL-single-agent/blob/0cda6a2d223de1b598ec4adcc92f54d900565b11/Screenshot%202026-04-19%20173833.png)
![App Screenshot](https://github.com/LOSTME-CODE/TEXT-SQL-single-agent/blob/0b2efe1ae9825aba11c9650acd9e18d98e3a2062/Screenshot%202026-04-19%20173933.png)
![App Screenshot](https://github.com/LOSTME-CODE/TEXT-SQL-single-agent/blob/0b2efe1ae9825aba11c9650acd9e18d98e3a2062/Screenshot%202026-04-19%20173957.png)


<h3><a class="anchor" id="overview"></a>Overview</h3>
**Text-SQL Single Agent** is an AI-powered data assistant that allows users to interact with structured data using plain English.  
Instead of writing SQL manually, users can ask questions naturally, and the system automatically generates SQL queries, executes them, and returns results in both raw table format and human-readable summaries.

The project includes UI built with Gradio and supports both:

- SQL Server Databases  
- CSV File Analysis
<h3><a class="anchor" id="problem-statement"></a>Problem Statement</h3>
Many business users, analysts, and non-technical teams need quick access to data but face challenges such as:

- Lack of SQL knowledge  
- Dependency on technical teams  
- Time-consuming manual querying  
- Difficulty understanding raw query results

This project solves that gap by enabling **natural language data interaction

<h3><a class="anchor" id="tools--technologies"></a>Tools & Technologies</h3>


| Category | Tools Used |
|--------|------------|
| Language | Python |
| UI | Gradio |
| LLM Framework | LangChain |
| Local Model | Ollama |
| Database | SQL Server |
| CSV Engine | SQLite (In-Memory) |
| Data Handling | Pandas |
| Query Logic | Regex + Prompt Engineering |

<h3><a class="anchor" id="Result"></a>Result</h3>

Successfully converts 
- English questions into SQL
- Works on SQL Server and CSV files
- Returns raw + summarized answers
- Interactive modern UI experience

<h3><a class="anchor" id="Deployment"></a>Deployment</h3>


To deploy this project run

```bash
  pip install gradio langchain-ollama langchain-core pyodbc pandas
```
Download Ollama and pull model:
```bash
  ollama pull llama3.2:3b
  ollama serve
```
Run Project
```bash
 python csvagent5.py
```



<h3><a class="anchor" id="future-work"></a>Future Work</h3>

- Multi-database support (MySQL, PostgreSQL, Oracle)
- Charts & Visualizations
- Export to Excel / PDF
- Voice Query Input
- Authentication & Roles
- Query Optimization Suggestions
- RAG + SQL Hybrid Assistant
- Multi-turn Memory Chat

  <h3><a class="anchor" id="Methodology"></a>Methodology</h3>
```text
Step 1: Input Source Selection
- Connect SQL Server Database
- Upload CSV File

Step 2: Schema Extraction
- Reads table names
- Reads column names
- Reads data types

Step 3: Natural Language to SQL
User Question → LLM + Schema Context → SQL Query Generation

Example:
Show top 5 employees by salary
SELECT TOP 5 name, salary FROM employees ORDER BY salary DESC;

Step 4: Query Validation
Safety rules applied:
- Only SELECT queries allowed
- No DELETE / UPDATE / DROP
- SQL cleaned before execution

Step 5: Query Execution
- SQL Server via pyodbc

Step 6: NLP Response
Raw output converted into readable answer

