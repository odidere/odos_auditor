import json
import logging
import os
import time
from datetime import datetime
from typing import Dict

# Import Providers
import openai
from google import genai

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OdosSurgeon")


class Surgeon:
    """
    The AI Site Reliability Engineer (SRE).
    Diagnoses both Financial Waste (Bad SQL) and Operational Failure (Pipeline Logs).
    """

    def __init__(self):
        # 1. Initialize OpenAI
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = None
        if self.openai_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_key)

        # 2. Initialize Gemini (New SDK)
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.gemini_client = None
        if self.gemini_key:
            self.gemini_client = genai.Client(api_key=self.gemini_key)

    # --- CAPABILITY 1: PIPELINE FAILURE ANALYSIS (AI SRE) ---
    def diagnose_pipeline_failure(self, error_message: str, stack_trace: str) -> Dict:
        """
        Analyzes raw error logs to find the root cause.
        Strategy: Try LLM first -> Fallback to Heuristic Rules.
        """
        # 1. Try AI Diagnosis if keys are present
        if self.openai_client or self.gemini_client:
            try:
                prompt = self._build_pipeline_prompt(
                    error_message, stack_trace)
                if self.openai_client:
                    return self._call_openai(prompt)
                elif self.gemini_client:
                    return self._call_gemini(prompt)
            except Exception as e:
                logger.warning(
                    f"⚠️ AI Diagnosis Failed: {e}. Falling back to Rules Engine.")

        # 2. Fallback: Heuristic Rules Engine (The "Safety Net")
        return self._heuristic_diagnosis(str(error_message).lower())

    def _heuristic_diagnosis(self, err: str) -> Dict:
        """Hardcoded rules for when AI is unavailable."""
        time.sleep(0.5)  # Simulate thought process

        if "connection" in err or "timeout" in err:
            return {
                "root_cause": "Network Partition / Firewall Drop",
                "confidence": "High",
                "fix_action": "1. Verify Security Group rules allow outbound traffic on port 5432.\n2. Implement 'Exponential Backoff' in your connection retry logic."
            }
        elif "oomkilled" in err or "memory" in err:
            return {
                "root_cause": "Resource Exhaustion (RAM)",
                "confidence": "Very High",
                "fix_action": "The container hit its hard limit. Switch to streaming processing (e.g., `chunksize=1000`) or request a larger instance type."
            }
        elif "deadlock" in err:
            return {
                "root_cause": "Database Concurrency Conflict",
                "confidence": "High",
                "fix_action": "Transactions are accessing rows in different orders. Enforce a strict canonical ordering."
            }
        elif "schemamismatch" in err or "column" in err:
            return {
                "root_cause": "Upstream Schema Drift",
                "confidence": "Medium",
                "fix_action": "The source table changed without notification. Update your dbt model schema contract."
            }
        elif "permission" in err or "access" in err:
            return {
                "root_cause": "IAM / RBAC Violation",
                "confidence": "High",
                "fix_action": "The Service Account lacks privileges. Grant the 'DataEditor' role to the pipeline principal."
            }

        return {
            "root_cause": "Unhandled Application Exception",
            "confidence": "Low",
            "fix_action": "Review the stack trace. Add try/except blocks to handle malformed input data."
        }

    # --- CAPABILITY 2: SQL COST OPTIMIZATION (Whale Hunter) ---
    def optimize_sql(self, query_text: str, task_id: str = "adhoc") -> Dict:
        """
        The Main Router: Tries OpenAI first, falls back to Gemini.
        """
        context = self._build_sql_prompt(query_text)

        # Attempt 1: OpenAI
        try:
            if not self.openai_client:
                raise ValueError("No OpenAI Key")
            logger.info(f"🚑 Surgeon: Optimizing {task_id} using OpenAI...")
            return self._call_openai(context)
        except Exception as e:
            logger.warning(f"⚠️ OpenAI Failed: {e}. Switching to Gemini.")

            # Attempt 2: Gemini
            try:
                if not self.gemini_client:
                    raise ValueError("No Gemini Key")
                logger.info(f"🚑 Surgeon: Optimizing {task_id} using Gemini...")
                return self._call_gemini(context)
            except Exception as e2:
                logger.error(f"❌ All AI Providers failed: {e2}")
                return {
                    "diagnosis": f"System Error: {str(e2)}",
                    "suggested_sql": query_text,
                    "strategy": "None",
                    "estimated_savings_pct": 0
                }

    # --- PROMPT BUILDERS ---
    def _build_pipeline_prompt(self, error: str, trace: str) -> str:
        return f"""
        You are a Site Reliability Engineer (SRE). Analyze this Pipeline Failure.
        
        ERROR: {error}
        TRACE: {trace}
        
        RESPONSE JSON FORMAT:
        {{
            "root_cause": "Technical explanation (max 10 words)",
            "confidence": "High/Medium/Low",
            "fix_action": "Step-by-step fix instructions."
        }}
        """

    def _build_sql_prompt(self, query_text: str) -> str:
        return f"""
        You are a Senior Snowflake Data Engineer. Optimize this SQL for COST.
        
        INPUT QUERY:
        ```sql
        {query_text}
        ```
        
        RESPONSE JSON FORMAT:
        {{
            "diagnosis": "Brief explanation of inefficiency.",
            "suggested_sql": "Optimized SQL code only.",
            "strategy": "Technical name of fix (e.g. Partition Pruning).",
            "estimated_savings_pct": "Integer percentage."
        }}
        """

    # --- AI CLIENT WRAPPERS ---
    def _call_openai(self, prompt: str) -> Dict:
        response = self.openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a JSON-speaking Engineering Expert."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)

    def _call_gemini(self, prompt: str) -> Dict:
        response = self.gemini_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        if not response.text:
            raise ValueError("Empty Gemini Response")
        clean_text = response.text.replace(
            "```json", "").replace("```", "").strip()
        return json.loads(clean_text)

    # --- DATA COLLECTION ---
    def log_for_finetuning(self, original_sql: str, suggested_sql: str, accepted: bool, task_id: str):
        dataset_file = os.getenv(
            "PULSEFLOW_DATASET_PATH", "odos_finetuning_dataset.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "task_id": task_id,
            "input_sql": original_sql,
            "output_sql": suggested_sql,
            "label": 1 if accepted else 0,
            "model_used": "hybrid-router"
        }
        with open(dataset_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"✅ Training data captured for {task_id}")
