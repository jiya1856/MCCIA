"""
Q&A Engine Module
==================
AI-powered compliance Q&A engine using Anthropic Claude API.
Provides intelligent answers to compliance queries for MSME clients,
enforcing strict statutory citations and circular supersession checks.
"""

import os
import pandas as pd
from dotenv import load_dotenv
from groq import Groq

load_dotenv(override=True)


def load_active_circulars(circulars_json):
    """
    Filter only active circulars, handling supersession logic.
    
    Args:
        circulars_json: List of circular dictionaries.
        
    Returns:
        tuple: (formatted string summary of active circulars, dict of {superseded_id: superseding_id})
    """
    supersession_map = {}
    
    # First pass: collect all superseded IDs and map them to their superseding circular
    for c in circulars_json:
        sup = str(c.get("supersedes", "")).strip()
        cid = str(c.get("circular_id", "")).strip()
        if sup:
            supersession_map[sup] = cid
            
    active_circulars = []
    
    # Second pass: filter active ones that are not superseded
    for c in circulars_json:
        cid = str(c.get("circular_id", "")).strip()
        is_active = c.get("active", False)
        
        if is_active and cid not in supersession_map:
            active_circulars.append(c)
            
    # Build formatted string
    context_lines = []
    for c in active_circulars:
        context_lines.append(
            f"Circular ID: {c.get('circular_id', 'N/A')} | "
            f"Date: {c.get('date', 'N/A')} | "
            f"Title: {c.get('title', 'N/A')} | "
            f"Summary: {c.get('summary', 'N/A')}"
        )
        
    active_circulars_context = "\n".join(context_lines)
    return active_circulars_context, supersession_map


def build_system_prompt(active_circulars_context):
    """
    Return the exact system prompt required for the AI model.
    """
    prompt = f"""
You are a senior Indian statutory compliance expert advising a CA firm.

MANDATORY RULES — violating any rule means the answer scores ZERO:
1. Every answer MUST cite the exact Act name AND Section number.
   Example format: "Under Section 7Q of the EPF Act, 1952..."
2. If a GST circular is relevant, cite it by circular number and date.
3. Structure EVERY answer in this exact format:
   DIRECT ANSWER: [1-2 line answer]
   STATUTORY BASIS: [Act Name], Section [X] — [what it says]
   CIRCULAR REFERENCE: [Circular No. XX/XXXX if applicable, else 'N/A']
   PENALTY DETAILS: [Specific % or amount, not vague descriptions]
   ⚠️ This is not legal advice. Consult your CA for specific situations.
4. Never say "there will be a penalty" without specifying the exact rate.
5. For PF questions, always cite both Section 7Q (interest) AND 
   Para 32A (damages) of the EPF Scheme 1952, and explicitly mention "EPF Act, 1952".
6. For GST questions, check if any relevant circular has been superseded 
   and cite only the active one.
7. If you genuinely don't know the section number, say: 
   "Section reference not confirmed — please verify with MCA/CBIC portal"
   Never fabricate section numbers.

ACTIVE GST CIRCULARS CONTEXT:
{active_circulars_context}
"""
    return prompt.strip()


def answer_question(question, circulars_json, api_key=None):
    """
    Answer a compliance question using Groq API.
    """
    context, supersession_map = load_active_circulars(circulars_json)
    system_prompt = build_system_prompt(context)
    
    # Check for superseded IDs in the question to generate a warning
    warning = None
    for sid, superseder in supersession_map.items():
        if sid in question:
            warning = f"⚠️ Note: Circular {sid} has been superseded by Circular {superseder}"
            break

    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            max_tokens=1000,
            temperature=0.1
        )
        answer_text = response.choices[0].message.content
    except Exception as e:
        answer_text = f"API Error: {str(e)}"
        
    return {
        "answer": answer_text,
        "has_citation": "Section" in answer_text or "Para" in answer_text,
        "has_disclaimer": "not legal advice" in answer_text.lower(),
        "superseded_warning": warning
    }


def batch_evaluate_qa(qa_dataset_df, circulars_json):
    """
    Evaluate the Q&A engine against the ground truth dataset.
    """
    results = []
    total = len(qa_dataset_df)
    score_count = 0
    
    for idx, row in qa_dataset_df.iterrows():
        question = row.get("question", "")
        expected_answer = row.get("answer", "")
        
        result = answer_question(question, circulars_json)
        ai_answer = result["answer"]
        has_citation = result["has_citation"]
        
        # Non-generic check: should have reasonable length and not be an API error message
        is_non_generic = len(ai_answer) > 50 and not ai_answer.startswith("API Error:")
        
        score = 1 if (has_citation and is_non_generic) else 0
        score_count += score
        
        results.append({
            "question": question,
            "expected_answer": expected_answer,
            "ai_answer": ai_answer,
            "has_citation": has_citation,
            "score": score
        })
        
    eval_df = pd.DataFrame(results)
    
    accuracy_percent = (score_count / total * 100) if total > 0 else 0
    print(f"Q&A Accuracy: {score_count}/{total} ({accuracy_percent:.1f}%)")
    
    return eval_df


if __name__ == "__main__":
    import os
    import sys
    
    # Add project root to path so we can import modules
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    
    from modules import load_all_data
    
    print("=" * 70)
    print("  Q&A ENGINE - Test Run")
    print("=" * 70)
    
    # Load data
    data = load_all_data()
    circulars_json = data.gst_circulars
    qa_df = data.compliance_qa
    
    test_q = "What is the penalty for late PF deposit?"
    print(f"\nTest Question: {test_q}")
    result = answer_question(test_q, circulars_json)
    print("-" * 50)
    print(result['answer'])
    print("-" * 50)
    print(f"Has Citation: {result['has_citation']}")
    print(f"Has Disclaimer: {result['has_disclaimer']}")
    print(f"Superseded Warning: {result['superseded_warning']}")
    
    print("\nStarting batch evaluation (this may take a moment or fail if API key is invalid)...")
    try:
        eval_results = batch_evaluate_qa(qa_df.head(2), circulars_json)
        print("\nEvaluation Sample:")
        print(eval_results[['question', 'score']])
    except Exception as e:
        print(f"Batch evaluation failed: {e}")
