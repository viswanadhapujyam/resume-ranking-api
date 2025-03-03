from fastapi import FastAPI, UploadFile, File, HTTPException, Body,Form
from fastapi.responses import StreamingResponse
from typing import List
import pdfplumber
import docx
import pandas as pd
import io,json
from groq import Groq
from pydantic import BaseModel
import traceback
import json
import re
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Initialize FastAPI App
app = FastAPI(
    title="Resume Ranking API",
    description="Automates resume ranking based on job descriptions."
)

# Initialize Groq Client
client = Groq(
    api_key=os.environ.get("groq_api")  # Replace with your actual API key
)

# Function to extract text from PDF/DOCX files
def extract_text(file: UploadFile):
    """Extract text from PDF or DOCX file."""
    try:
        print(file)
        print(file.filename)
        if file.filename.endswith(".pdf"):
            with pdfplumber.open(file.file) as pdf:
                text = "\n".join([page.extract_text() or "" for page in pdf.pages])
            
        elif file.filename.endswith(".docx"):
            doc = docx.Document(file.file)
            text = "\n".join([para.text for para in doc.paragraphs])

        else:
            raise HTTPException(status_code=400, detail="Unsupported file format.")
        print(text)
        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

# Function to extract ranking criteria using Groq API
def extract_criteria(text: str):
    """Use Groq API to extract structured job ranking criteria from job description text."""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant that extracts key job ranking criteria "
                        "from job descriptions. Extract ONLY the relevant criteria into a structured JSON format "
                        "with a single key `criteria`, which contains a list of concise ranking criteria. "
                        "Ensure the response is strictly in JSON format with no extra text. \n\n"
                        "### Example Output:\n"
                        "```json\n"
                        "{\n"
                        "  \"criteria\": [\n"
                        "    \"Must have certification XYZ\",\n"
                        "    \"5+ years of experience in Python development\",\n"
                        "    \"Strong background in Machine Learning\"\n"
                        "  ]\n"
                        "}\n"
                        "```\n\n"
                        "Extracted criteria should include:\n"
                        "- Required skills (technical & soft skills)\n"
                        "- Work experience (years, relevant domains, expertise)\n"
                        "- Certifications (mandatory or preferred ones)\n"
                        "- Education qualifications\n\n"
                        "Ensure that criteria are **concise and specific**."
                    ),
                },
                {"role": "user", "content": text},
            ],
            model="llama-3.3-70b-versatile",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in AI processing: {str(e)}")

def extract_json(text):
    """Extracts the JSON content between the outermost { and }."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else None
# Endpoint to extract ranking criteria from job description file
@app.post("/extract-criteria")
async def extract_criteria_endpoint(file: UploadFile = File(...)):
    text = extract_text(file)
    criteria = extract_criteria(text)
    json_criteria = extract_json(criteria)
    print(json_criteria)
    return json.loads(json_criteria)




def score_resume(text: str, criteria: list):
    """Score a resume based on extracted job criteria using LLM evaluation."""
    try:
        # Define the structured prompt
        prompt = (
            "You are an AI assistant evaluating resumes against job criteria. "
            "For each criterion, assign a score from 0 to 5:\n"
            "- 5 = Strong match\n"
            "- 3 = Partial match\n"
            "- 0 = No match\n\n"
            "### Job Criteria:\n"
            f"{json.dumps(criteria, indent=2)}\n\n"
            "### Resume Text:\n"
            f"{text}\n\n"
            "Return a **valid JSON output ONLY** in the following format, with no explanations or extra text:\n"
            "{\n"
            "  \"scores\": {\n"
            "    \"criterion_1\": score,\n"
            "    \"criterion_2\": score,\n"
            "    ...\n"
            "  },\n"
            
            "}"
            "name those criteria exactly, what you rating for, i want output just json format, nothing else , even word 'json' in response, complete json only."
        )

        # Call Groq's LLM API
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )

        # Extract LLM response
        response = chat_completion.choices[0].message.content.strip()
        print("response from llm\n\n\n",response)
        # Remove unwanted "json" keyword if present
        response = re.sub(r'^\s*json\s*', '', response, flags=re.IGNORECASE).strip()

        # Convert to Python dictionary
        scores = json.loads(response)

        print("--"*50)
        print("scores from llm:Data type",type(scores),"its value:",scores)

        print("*"*80)
        print(scores)

        return scores
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {response}") from e
    except Exception as e:
        raise ValueError(f"Error in AI scoring: {str(e)}")



# Pydantic model for input validation
class ScoreRequest(BaseModel):
    criteria: List[str]


@app.post("/score-resumes")
async def score_resumes_endpoint(
    criteria: str = Form(...),  # Accept criteria as a comma-separated string
    files: List[UploadFile] = File(...)
):
    try:
        # Convert criteria string to list
        criteria_list = json.loads(criteria)
        print(criteria_list)
        results = []
        for file in files:
            text = extract_text(file)
            scores = score_resume(text, criteria_list)
            total_score = sum(scores['scores'].values())
            temp_dict={'Candidate': file.filename, 'total_score': total_score}
            for i,j in scores["scores"].items():
                temp_dict[i]=j
            results.append(temp_dict)


            

        df = pd.DataFrame(results)
        output = io.BytesIO()
        df.to_csv(output, index=False)
        output.seek(0)

        return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=resume_scores.csv"})

        return {"results": results}
    except Exception as e:
        print("Error :", e)
        print("traceback error",traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# Run FastAPI app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

