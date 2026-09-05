# Pirlo ⚽

Pirlo (named after the legendary Italian midfielder Andrea Pirlo) is an agentic, self-healing browser automation runner built using clean architecture principles.

Like a soccer match, runs are executed on a **Pitch** following a pre-defined tactical routine called a **Playbook**. Credentials and model endpoints are managed as reusable passing routes called **LLM Links**.

---

## 1. Football Concept Dictionary

* **Pitch**: The runtime environment executing the automation.
* **Play**: An atomic tactical unit representing a single automation step (e.g. `AutopassPlay`).
* **LLM Link**: A connection configuration representing an LLM model, credential, and base URL. Decoupled from playbooks, links allow credentials to be reused.
  * **Playmaker**: The active decision brain (Agent) navigating the page.
  * **Analyst**: The DOM summary and selector healer (Replay) analyzing the layout.

---

## 2. LLM Link CLI Command Group (`pirlo link`)

Configure and verify connection links directly via the command line.

### A. List Connections
```bash
pirlo link list
```
Prints a formatted table of all registered links, their providers, models, and endpoints.

### B. Create or Update a Connection
#### 1. Interactive Setup Wizard
Running this command with no flags launches a dynamic step-by-step setup wizard:
```bash
pirlo link create
```
*Prompts dynamically adjust based on the provider (e.g. standard API key/base URL or future custom keys).*

#### 2. Flag-based Creation (Automation / CI)
```bash
pirlo link create gemini-flash \
  --provider gemini \
  --model "gemini-1.5-flash" \
  --api-key "AIzaSy..." \
  --base-url "https://generativelanguage.googleapis.com/v1beta/openai/" \
  --test
```

### C. Show Link Details
```bash
pirlo link show <name>
```
Displays configuration details for a link. Sensitive attributes like `api_key` are masked automatically (e.g. `AIzaSy*********`).

### D. Verify Connection
```bash
pirlo link test <name>
```
Instantiates the client and sends a minimal token prompt to verify credentials and connectivity immediately.

### E. Delete Connection
```bash
pirlo link delete <name>
```
Removes a link configuration from the storage registry.

---

## 3. Running Autopass Playbooks

To execute a playbook, specify the playmaker link name.

### Example Run:
```bash
pirlo autopass \
  --task "Navigate to booking.com, search for hotels in Munich, and filter by rating > 4" \
  --playmaker gemini-flash \
  --headless
```

### Zero-Setup Fallback (Environment Mappings)
If you run without setting up any links, you can reference the standard provider names (e.g., `gemini-default`, `dashscope-default`). Pirlo will dynamically read standard environment variables (`GEMINI_API_KEY`, `DASHSCOPE_API_KEY`) and fallback to default endpoints out-of-the-box:
```bash
# Works without links.json configuration
export GEMINI_API_KEY="AIzaSy..."
pirlo autopass \
  --task "Search Google" \
  --playmaker gemini-default
```

